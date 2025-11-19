# src/fitlink_backend/routers/events.py
from fastapi import APIRouter, HTTPException, Query, Header, Depends
import time as pytime
import httpx
import httpcore
from typing import List, Optional, Literal
from datetime import datetime, timezone, date, time, timedelta
from pydantic import BaseModel, EmailStr

from fitlink_backend.supabase_client import (
    supabase,              # cliente público (anon)
    supabase_for_token,    # cliente firmado con JWT
    get_admin_client,      # cliente admin (service role)
)

# Import del usuario autenticado (soporta nombre español/inglés del archivo)
from fitlink_backend.dependencies import get_current_user  # <- si se llama 'dependencies.py'

router = APIRouter(prefix="/api/events", tags=["events"])

# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_exec(callable_fn, retries: int = 1):
    """
    Ejecuta `callable_fn()` (debe devolver el objeto que retorna `.execute()`),
    atrapando errores de lectura/timeout de httpx/httpcore. Reintenta `retries`
    veces antes de elevar HTTPException con 502 (bad gateway) para indicar
    problema con PostgREST/Supabase.
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return callable_fn()
        except (httpx.ReadTimeout, httpx.ReadError, httpcore.ReadTimeout, httpcore.ReadError) as e:
            last_exc = e
            if attempt == retries:
                raise HTTPException(status_code=502, detail="Error de conexión con servicio de datos (PostgREST).") from e
            # backoff corto
            pytime.sleep(0.15 * (attempt + 1))
        except Exception as e:
            # otros errores (p. ej. APIError) propagamos como 500 con detalle
            raise HTTPException(status_code=500, detail=str(e)) from e


def _user_id_from(current_user) -> str:
    """
    Extrae el id del usuario ya sea que 'current_user' sea el objeto User de Supabase
    o un dict. Lanza 401 si no puede obtenerse.
    """
    uid = getattr(current_user, "id", None)
    if not uid and isinstance(current_user, dict):
        uid = current_user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="No se pudo obtener el id del usuario")
    return str(uid)

def _bearer(token_header: Optional[str]) -> Optional[str]:
    if not token_header:
        return None
    return token_header.replace("Bearer ", "").strip()

def _uid_from_token(authorization: Optional[str]) -> Optional[str]:
    """
    Devuelve el user_id (UUID) del JWT pasado en Authorization.
    Usa el cliente público para decodificar el token.
    """
    token = _bearer(authorization)
    if not token:
        return None
    try:
        resp = supabase.auth.get_user(token)
        user = getattr(resp, "user", None) or (getattr(resp, "data", {}) or {}).get("user")
        if isinstance(user, dict):
            return user.get("id")
        return getattr(user, "id", None)
    except Exception:
        return None

def _normalize_nivel(nivel: str) -> str:
    """
    Mapea 'Principiante|Intermedio|Avanzado' (o minúsculas) al ENUM de BD en minúsculas.
    """
    mapping = {
        "Principiante": "principiante",
        "Intermedio":   "intermedio",
        "Avanzado":     "avanzado",
        "principiante": "principiante",
        "intermedio":   "intermedio",
        "avanzado":     "avanzado",
    }
    v = mapping.get(nivel)
    if not v:
        raise HTTPException(status_code=422, detail="Nivel inválido")
    return v

# ---------------------------------------------------------------------
# GETs
# ---------------------------------------------------------------------

@router.get("/upcoming")
async def upcoming_events(
    limit: int = Query(20, ge=1, le=100),
) -> List[dict]:
    res = _safe_exec(lambda: (
        supabase.table("eventos")
        .select("*")
        .gte("inicio", _now_iso())
        .eq("estado", "activo")
        .order("inicio", desc=False)
        .limit(limit)
        .execute()
    ))
    return res.data or []

@router.get("/latest")
async def latest_events(
    limit: int = Query(50, ge=1, le=200),
) -> List[dict]:
    res = _safe_exec(lambda: (
        supabase.table("eventos")
        .select("*")
        .eq("estado", "activo")
        .order("inicio", desc=False)
        .limit(limit)
        .execute()
    ))
    return res.data or []

@router.get("")
async def list_events(
    limit: int = Query(50, ge=1, le=200),
    estado: Optional[str] = None,
) -> List[dict]:
    q_builder = lambda: (supabase.table("eventos").select("*").order("inicio", desc=False).limit(limit))
    if estado:
        q_builder = lambda: (supabase.table("eventos").select("*").order("inicio", desc=False).limit(limit).eq("estado", estado))
    res = _safe_exec(lambda: q_builder().execute())
    return res.data or []

# ---------------------------------------------------------------------
# POST /api/events  (crear evento - requiere sesión)
# ---------------------------------------------------------------------

class EventCreate(BaseModel):
    # Mantengo tus campos para compatibilidad con tu UI actual
    nombre: str
    email: Optional[EmailStr] = None   # ← ignorado en BD; se usa el email del token
    descripcion: str
    categoria: str
    municipio: str
    nivel: Literal["Principiante", "Intermedio", "Avanzado"]
    fecha: date          # "YYYY-MM-DD"
    hora: time           # "HH:MM"

@router.post("", status_code=201)
async def create_event(
    payload: EventCreate,
    current_user = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    Crea un evento (requiere login). Combina fecha+hora en 'inicio' (UTC)
    y guarda en la tabla 'eventos'. Garantiza chat por evento usando admin si es necesario.
    Si viene Authorization, inscribe al creador como participante y miembro del chat.
    """
    try:
        # 1) Email desde el usuario autenticado
        email = getattr(current_user, "email", None) or (
            isinstance(current_user, dict) and current_user.get("email")
        )
        if not email:
            raise HTTPException(status_code=401, detail="No se pudo obtener el email del usuario")

        # 2) Validación fecha futura
        inicio_dt = datetime.combine(payload.fecha, payload.hora).replace(tzinfo=timezone.utc)
        if inicio_dt < datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="La fecha y hora deben ser futuras")

        fin_dt = inicio_dt + timedelta(hours=1)  # por ahora duración fija de 1h

        # 3) Validar/normalizar nivel (aunque no lo guardemos todavía)
        _ = _normalize_nivel(payload.nivel)

        # 4) Intentar obtener id de categoría a partir del nombre
        categoria_id = None
        try:
            cat_res = (
                supabase
                .table("categoria")
                .select("id")
                .eq("nombre", payload.categoria)
                .limit(1)
                .execute()
            )
            cat_rows = cat_res.data or []
            if cat_rows:
                categoria_id = cat_rows[0]["id"]
        except Exception:
            categoria_id = None

        # Si no se consigue la categoría, usar 1 como fallback
        if categoria_id is None:
            categoria_id = 1

        # 5) Fila que se inserta en 'eventos'
        row = {
            "categoria": categoria_id,
            "nombre_evento": payload.nombre,
            "descripcion": payload.descripcion,
            "inicio": inicio_dt.isoformat(),
            "fin": fin_dt.isoformat(),
            "cupos": 10,                        # valor por defecto
            "municipio": payload.municipio or "Caracas",
            "precio": 0.0,                      # por ahora eventos gratuitos
            "estado": "activo",
            "creador_email": email,
        }

        # 6) Insertar el evento
        ev_ins = supabase.table("eventos").insert(row).execute()
        data = ev_ins.data or []
        if not data:
            raise HTTPException(status_code=400, detail="No se pudo crear el evento.")
        created = data[0]
        evento_id = created.get("id") or created.get("evento_id")

        # 7) Crear/garantizar chat asociado al evento (como ya lo tenías)
        try:
            admin = get_admin_client()
            title = created.get("descripcion") or f"Chat del evento #{evento_id}"
            admin.table("chats").upsert(
                {
                    "evento_id": evento_id,
                    "title": title,
                    "is_group": True,
                },
                on_conflict="evento_id",
            ).execute()
        except Exception:
            pass

        # 8) Inscribir al creador como participante y miembro del chat
        token = _bearer(authorization)
        user_id = _uid_from_token(authorization)
        if token and user_id:
            sb = supabase_for_token(token)

            sb.table("event_participants").upsert(
                {
                    "evento_id": evento_id,
                    "user_id": user_id,
                    "status": "active",
                    "joined_at": _now_iso(),
                },
                on_conflict="evento_id,user_id",
            ).execute()

            chat_row = (
                sb.table("chats")
                .select("id")
                .eq("evento_id", evento_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            chat_id = chat_row[0]["id"] if chat_row else None

            if chat_id:
                sb.table("chat_members").upsert(
                    {
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "joined_at": _now_iso(),
                    },
                    on_conflict="chat_id,user_id",
                ).execute()

        return created

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------
# Unirse / Dejar evento
# ---------------------------------------------------------------------

@router.post("/{event_id}/join")
async def join_event(
    event_id: int,
    current_user = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    """
    Garantiza chat por evento e inscribe al usuario en:
    - event_participants (evento_id,user_id)
    - chat_members (chat_id,user_id)
    Devuelve chat_id.

    Todas las operaciones que dependen de RLS se hacen con el cliente firmado (JWT).
    La creación del chat (si no existe) se hace con admin para evitar políticas restrictivas.
    """
    # 0) cliente firmado + user_id
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta token")
    sb = supabase_for_token(token)
    user_id = _user_id_from(current_user)

    # 1) validar evento (con RLS si aplica)
    ev_rows = sb.table("eventos").select("id").eq("id", event_id).limit(1).execute().data or []
    if not ev_rows:
        raise HTTPException(status_code=404, detail="Evento no existe")

    # 2) obtener o crear chat del evento
    chat_rows = sb.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
    if chat_rows:
        chat_id = chat_rows[0]["id"]
    else:
        # intenta crear con el usuario; si falla por policy, crea con admin
        try:
            created = sb.table("chats").insert({
                "evento_id": event_id,
                "is_group": True,
                "title": f"Chat del evento #{event_id}",
                "created_by": user_id,
            }).execute().data or []
            chat_id = created[0]["id"] if created else None
        except Exception:
            chat_id = None

        if not chat_id:
            admin = get_admin_client()
            try:
                created = admin.table("chats").insert({
                    "evento_id": event_id,
                    "is_group": True,
                    "title": f"Chat del evento #{event_id}",
                    "created_by": user_id,
                }).execute().data or []
                if created:
                    chat_id = created[0]["id"]
                else:
                    # si la inserción no devolvió fila, intentamos recuperar
                    again = admin.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
                    if not again:
                        raise HTTPException(status_code=500, detail="No se pudo crear ni recuperar el chat del evento")
                    chat_id = again[0]["id"]
            except Exception as e:
                # Manejar caso de inserciones concurrentes que produzcan clave única duplicada
                msg = str(e)
                if 'duplicate key value violates unique constraint' in msg or '23505' in msg:
                    again = admin.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
                    if again:
                        chat_id = again[0]["id"]
                    else:
                        raise HTTPException(status_code=500, detail="Conflicto al crear chat y no se pudo recuperar el registro")
                else:
                    raise HTTPException(status_code=500, detail=f"No se pudo crear ni recuperar el chat del evento: {str(e)}")

    # 3) upsert participante del evento
    sb.table("event_participants").upsert(
        {"evento_id": event_id, "user_id": user_id, "status": "active", "joined_at": _now_iso()},
        on_conflict="evento_id,user_id",
    ).execute()

    # 4) upsert membresía del chat
    sb.table("chat_members").upsert(
        {"chat_id": chat_id, "user_id": user_id, "joined_at": _now_iso()},
        on_conflict="chat_id,user_id",
    ).execute()

    return {"ok": True, "event_id": event_id, "chat_id": chat_id}


@router.post("/{event_id}/leave")
async def leave_event(
    event_id: int,
    current_user = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    """
    El usuario autenticado deja el evento: se elimina su participación
    y su membresía en el chat si existe. Operaciones con cliente firmado (RLS).
    """
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta token")
    sb = supabase_for_token(token)
    user_id = _user_id_from(current_user)

    # obtener chat del evento (si existe)
    chat = sb.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
    chat_id = chat[0]["id"] if chat else None

    if chat_id:
        # borra SOLO tu membresía
        sb.table("chat_members").delete().match({"chat_id": chat_id, "user_id": user_id}).execute()

    # borra SOLO tu participación en el evento
    sb.table("event_participants").delete().match({"evento_id": event_id, "user_id": user_id}).execute()

    return {"ok": True}

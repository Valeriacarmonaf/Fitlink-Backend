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

# Import del usuario autenticado
from fitlink_backend.dependencies import get_current_user 

# Importar función para crear notificaciones
from fitlink_backend.routers.notificaciones import enviar_notificacion

router = APIRouter(prefix="/api/events", tags=["events"])

# ---------------------------------------------------------------------
# Utilidades (Sin cambios)
# ---------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_exec(callable_fn, retries: int = 1):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return callable_fn()
        except (httpx.ReadTimeout, httpx.ReadError, httpcore.ReadTimeout, httpcore.ReadError) as e:
            last_exc = e
            if attempt == retries:
                raise HTTPException(status_code=502, detail="Error de conexión con servicio de datos (PostgREST).") from e
            pytime.sleep(0.15 * (attempt + 1))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e


def _user_id_from(current_user) -> str:
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
# GETs (AQUI ESTA LA CORRECCION)
# ---------------------------------------------------------------------

# NOTA: Usamos "*, Categoria(id, nombre, icono)" para hacer el JOIN
# Si tu tabla de categorías se llama diferente, ajusta el nombre dentro del paréntesis.

# 1. Función upcoming_events
@router.get("/upcoming")
async def upcoming_events(limit: int = Query(20, ge=1, le=100)) -> List[dict]:
    res = _safe_exec(lambda: (
        supabase.table("eventos")
        # 👇 CAMBIO CLAVE AQUÍ: nombre_tabla!nombre_foreign_key
        .select("*, categoria!eventos_categoria_fkey(id, nombre, icono)")
        .gte("inicio", _now_iso())
        .eq("estado", "activo")
        .order("inicio", desc=False)
        .limit(limit)
        .execute()
    ))
    return res.data or []

# 2. Función latest_events
@router.get("/latest")
async def latest_events(limit: int = Query(50, ge=1, le=200)) -> List[dict]:
    res = _safe_exec(lambda: (
        supabase.table("eventos")
        # 👇 CAMBIO CLAVE AQUÍ
        .select("*, categoria!eventos_categoria_fkey(id, nombre, icono)")
        .eq("estado", "activo")
        .order("inicio", desc=False)
        .limit(limit)
        .execute()
    ))
    return res.data or []

# 3. Función list_events
@router.get("")
async def list_events(limit: int = Query(50, ge=1, le=200), estado: Optional[str] = None) -> List[dict]:
    # 👇 CAMBIO CLAVE AQUÍ EN LA BASE QUERY
    base_query = supabase.table("eventos").select("*, categoria!eventos_categoria_fkey(id, nombre, icono)")
    
    q_builder = lambda: base_query.order("inicio", desc=False).limit(limit)
    if estado:
        q_builder = lambda: base_query.order("inicio", desc=False).limit(limit).eq("estado", estado)
        
    res = _safe_exec(lambda: q_builder().execute())
    return res.data or []

# ---------------------------------------------------------------------
# POST /api/events (Resto del código igual)
# ---------------------------------------------------------------------

class EventCreate(BaseModel):
    nombre: str
    email: Optional[EmailStr] = None 
    descripcion: str
    categoria: str
    municipio: str
    nivel: Literal["Principiante", "Intermedio", "Avanzado"]
    fecha: date          
    hora: time           

@router.post("", status_code=201)
async def create_event(
    payload: EventCreate,
    current_user = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
) -> dict:
    try:
        email = getattr(current_user, "email", None) or (
            isinstance(current_user, dict) and current_user.get("email")
        )
        if not email:
            raise HTTPException(status_code=401, detail="No se pudo obtener el email del usuario")

        # 2) Validación fecha futura
        ahora = datetime.now()
        inicio_dt = datetime.combine(payload.fecha, payload.hora)

        if inicio_dt < ahora:
            raise HTTPException(
                status_code=422,
                detail="La fecha y hora deben ser futuras"
            )
        fin_dt = inicio_dt + timedelta(hours=1)  # por ahora duración fija de 1h

        # 3) Validar/normalizar nivel (aunque no lo guardemos todavía)
        _ = _normalize_nivel(payload.nivel)

        # Buscar ID de categoria
        categoria_id = None
        try:
            cat_res = (
                supabase
                .table("categoria") # Ojo: Asegurate si tu tabla es "categoria" o "Categoria"
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

        if categoria_id is None:
            categoria_id = 1

        row = {
            "categoria": categoria_id,
            "nombre_evento": payload.nombre,
            "descripcion": payload.descripcion,
            "inicio": inicio_dt.isoformat(),
            "fin": fin_dt.isoformat(),
            "cupos": 10,
            "municipio": payload.municipio or "Caracas",
            "precio": 0.0,
            "estado": "activo",
            "creador_email": email,
        }

        ev_ins = supabase.table("eventos").insert(row).execute()
        data = ev_ins.data or []
        if not data:
            raise HTTPException(status_code=400, detail="No se pudo crear el evento.")
        created = data[0]
        evento_id = created.get("id") or created.get("evento_id")

        # Chat logic (sin cambios)
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

        # Inscribir creador (sin cambios)
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


@router.post("/{event_id}/join")
async def join_event(
    event_id: int,
    current_user = Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta token")
    sb = supabase_for_token(token)
    user_id = _user_id_from(current_user)

    ev_rows = sb.table("eventos").select("id").eq("id", event_id).limit(1).execute().data or []
    if not ev_rows:
        raise HTTPException(status_code=404, detail="Evento no existe")

    chat_rows = sb.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
    if chat_rows:
        chat_id = chat_rows[0]["id"]
    else:
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
                    again = admin.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
                    if not again:
                         raise HTTPException(status_code=500, detail="No se pudo crear chat")
                    chat_id = again[0]["id"]
            except Exception as e:
                msg = str(e)
                if 'duplicate key' in msg or '23505' in msg:
                    again = admin.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
                    if again:
                         chat_id = again[0]["id"]
                    else:
                         raise HTTPException(status_code=500, detail="Error concurrencia chat")
                else:
                    raise HTTPException(status_code=500, detail=str(e))

    sb.table("event_participants").upsert(
        {"evento_id": event_id, "user_id": user_id, "status": "active", "joined_at": _now_iso()},
        on_conflict="evento_id,user_id",
    ).execute()

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
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta token")
    sb = supabase_for_token(token)
    user_id = _user_id_from(current_user)

    chat = sb.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
    chat_id = chat[0]["id"] if chat else None

    if chat_id:
        sb.table("chat_members").delete().match({"chat_id": chat_id, "user_id": user_id}).execute()

    sb.table("event_participants").delete().match({"evento_id": event_id, "user_id": user_id}).execute()

    return {"ok": True}
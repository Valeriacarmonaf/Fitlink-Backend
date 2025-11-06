# src/fitlink_backend/routers/events.py
from fastapi import APIRouter, HTTPException, Query, Header, Depends
from typing import List, Optional, Literal
from datetime import datetime, timezone, date, time
from pydantic import BaseModel, EmailStr

from fitlink_backend.supabase_client import (
    supabase,              # cliente público (anon)
    supabase_for_token,    # cliente firmado con JWT
    get_admin_client,      # cliente admin (service role)
)
from fitlink_backend.dependencies import get_current_user

router = APIRouter(prefix="/api/events", tags=["events"])

# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

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
        # resp puede ser objeto con .user o dict en .data
        user = getattr(resp, "user", None) or (getattr(resp, "data", {}) or {}).get("user")
        if isinstance(user, dict):
            return user.get("id")
        return getattr(user, "id", None)
    except Exception:
        return None

# ---------------------------------------------------------------------
# GETs
# ---------------------------------------------------------------------
@router.get("/upcoming")
def upcoming_events(limit: int = Query(20, ge=1, le=100)) -> List[dict]:
    res = (
        supabase.table("eventos")
        .select("*")
        .gte("inicio", _now_iso())
        .order("inicio", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data or []

@router.get("")
def list_events(
    limit: int = Query(50, ge=1, le=200),
    estado: Optional[str] = None
) -> List[dict]:
    q = supabase.table("eventos").select("*").order("inicio", desc=False).limit(limit)
    if estado:
        q = q.eq("estado", estado)
    res = q.execute()
    return res.data or []

# ---------------------------------------------------------------------
# POST /api/events  (creación pública con Authorization opcional)
# ---------------------------------------------------------------------
class EventCreate(BaseModel):
    nombre: str
    email: EmailStr
    descripcion: str
    categoria: str
    municipio: str
    nivel: Literal["Principiante", "Intermedio", "Avanzado"]
    fecha: date          # "YYYY-MM-DD"
    hora: time           # "HH:MM"

@router.post("", status_code=201)
async def create_event(payload: EventCreate, authorization: Optional[str] = Header(None)) -> dict:
    """
    Crea un evento público (sin login). Combina fecha+hora en 'inicio' (UTC)
    y guarda en la tabla 'eventos'. Además crea un chat para el evento con cliente admin y, si
    hay usuario autenticado en el header Authorization, lo añade como participante
    del evento y del chat (firmado con el JWT para cumplir RLS).
    """
    try:
        # 1) Combinar fecha + hora en UTC
        inicio_utc = datetime.combine(payload.fecha, payload.hora).replace(tzinfo=timezone.utc).isoformat()

        row = {
            "creador_nombre": payload.nombre,
            "creador_email": payload.email,
            "descripcion": payload.descripcion,
            "categoria": payload.categoria,
            "municipio": payload.municipio,
            "nivel": payload.nivel,
            "inicio": inicio_utc,
            "estado": "activo",
        }

        # 2) Insertar el evento (público)
        ev_ins = supabase.table("eventos").insert(row).execute()
        data = ev_ins.data or []
        if not data:
            raise HTTPException(status_code=400, detail="No se pudo crear el evento.")
        created = data[0]
        evento_id = created.get("id") or created.get("evento_id")

        # 3) Crear chat asociado al evento (ADMIN; evita problemas de RLS/policies)
        try:
            admin = get_admin_client()
            title = created.get("descripcion") or f"Chat del evento #{evento_id}"
            admin.table("chats").insert({
                "evento_id": evento_id,
                "title": title,
                "is_group": True,
            }).execute()
        except Exception:
            # best-effort, si ya existe o policy lo impide, seguimos
            pass

        # 4) Si viene Authorization, inscribir a quien lo creó como participante y miembro del chat
        token = _bearer(authorization)
        user_id = _uid_from_token(authorization)
        if token and user_id:
            sb = supabase_for_token(token)
            # (a) participante del evento (INCLUYENDO user_id para pasar RLS)
            sb.table("event_participants").upsert(
                {"evento_id": evento_id, "user_id": user_id, "status": "active", "joined_at": _now_iso()},
                on_conflict="evento_id,user_id",
            ).execute()
            # (b) encontrar chat del evento
            chat_row = sb.table("chats").select("id").eq("evento_id", evento_id).limit(1).execute().data or []
            chat_id = chat_row[0]["id"] if chat_row else None
            # (c) membresía de chat (INCLUYENDO user_id)
            if chat_id:
                sb.table("chat_members").upsert(
                    {"chat_id": chat_id, "user_id": user_id, "joined_at": _now_iso()},
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
                "created_by": user_id,  # <-- (A) clave: NO nulo
            }).execute().data or []
            chat_id = created[0]["id"] if created else None
        except Exception:
            chat_id = None

        if not chat_id:
            admin = get_admin_client()
            created = admin.table("chats").insert({
                "evento_id": event_id,
                "is_group": True,
                "title": f"Chat del evento #{event_id}",
                "created_by": user_id,  # <-- (A) clave también con admin
            }).execute().data or []
            if not created:
                again = sb.table("chats").select("id").eq("evento_id", event_id).limit(1).execute().data or []
                if not again:
                    raise HTTPException(status_code=500, detail="No se pudo crear ni recuperar el chat del evento")
                chat_id = again[0]["id"]
            else:
                chat_id = created[0]["id"]

    # 3) upsert participante del evento (RLS, **incluyendo user_id**)
    sb.table("event_participants").upsert(
        {"evento_id": event_id, "user_id": user_id, "status": "active", "joined_at": _now_iso()},
        on_conflict="evento_id,user_id",
    ).execute()

    # 4) upsert membresía del chat (RLS, **incluyendo user_id**)
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

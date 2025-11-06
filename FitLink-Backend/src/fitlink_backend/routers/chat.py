# src/fitlink_backend/routers/chat.py
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime

from ..dependencies import get_current_user
from ..models.ChatModels import ChatSummary, MessageCreate, MessageOut, ChatUser
from ..supabase_client import supabase_for_token  # cliente firmado por JWT

router = APIRouter(prefix="/api/chats", tags=["chats"])

# ----------------------------- utils -----------------------------

def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        # Acepta ISO con o sin 'Z'
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None

def _row_to_chat_summary(r: dict) -> ChatSummary:
    # r: fila de la vista v_my_chats
    return ChatSummary(
        id=r["chat_id"],
        title=r.get("title"),
        is_group=r.get("is_group", False),
        image_url=None,
        last_message=r.get("last_message_content"),
        last_time=_parse_dt(r.get("last_message_at")),
        unread=0,  # hook para futuros "no leídos"
    )

def _get_user_id(current_user: Any) -> Optional[str]:
    if current_user is None:
        return None
    if hasattr(current_user, "id") and current_user.id:
        return str(current_user.id)
    if isinstance(current_user, dict):
        return str(current_user.get("id") or current_user.get("user_id") or "")
    return None

def _bearer(token_header: Optional[str]) -> Optional[str]:
    if not token_header:
        return None
    return token_header.replace("Bearer ", "").strip()

# --------------------------- endpoints ---------------------------

@router.get("", response_model=List[ChatSummary])
async def list_my_chats(
    current_user=Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    """
    Lista los chats del usuario autenticado usando la vista v_my_chats.
    Se firma la consulta con el JWT para que RLS (auth.uid()) aplique.
    """
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta token")
    sb = supabase_for_token(token)

    res = sb.table("v_my_chats").select("*").order("last_message_at", desc=True).execute()
    data = res.data or []
    return [_row_to_chat_summary(r) for r in data]


@router.get("/{chat_id}/messages", response_model=List[MessageOut])
async def list_messages(
    chat_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(None, description="ISO-8601 para paginar hacia atrás"),
    current_user=Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    """
    Lista mensajes del chat firmando con el JWT del usuario para que RLS aplique.
    Usa la vista v_chat_messages (o la tabla base) ordenada por created_at DESC.
    """
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta token")
    sb = supabase_for_token(token)

    qb = (
        sb.table("v_chat_messages")
        .select("*")
        .eq("chat_id", str(chat_id))
        .order("created_at", desc=True)
        .limit(limit)
    )
    if before:
        qb = qb.lt("created_at", before)

    res = qb.execute()
    rows = res.data or []

    out: List[MessageOut] = []
    for r in rows:
        sender_id = r["user_id"]
        ures = (
            sb.table("usuarios")
            .select("id, nombre, foto_url")
            .eq("id", str(sender_id))
            .limit(1)
            .execute()
            .data
        )
        u = ures[0] if ures else {"id": sender_id, "nombre": "Usuario", "foto_url": None}
        out.append(
            MessageOut(
                id=r["id"],
                chat_id=r["chat_id"],
                user=ChatUser(**u),
                content=r["content"],
                created_at=_parse_dt(r.get("created_at")),
            )
        )
    return out


@router.post("/{chat_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    chat_id: UUID,
    body: MessageCreate,
    current_user=Depends(get_current_user),
    authorization: Optional[str] = Header(None),
):
    """
    Inserta un mensaje en chat_messages firmando con el JWT del usuario.
    También asegura la membresía (upsert) antes de insertar, para evitar
    fallos por RLS si todavía no existía el registro en chat_members.
    """
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Falta token")
    sb = supabase_for_token(token)

    user_id = _get_user_id(current_user)
    if not user_id:
        raise HTTPException(status_code=401, detail="No autorizado")

    # 1) Asegurar membresía idempotente
    sb.table("chat_members").upsert({
        "chat_id": str(chat_id),
        "user_id": str(user_id),
    }, on_conflict="chat_id,user_id").execute()

    # 2) Insertar mensaje (compatible con supabase-py 2.x; no usar .single()/.select() encadenado)
    payload = {
        "chat_id": str(chat_id),
        "user_id": str(user_id),  # validado por RLS: user_id = auth.uid()
        "content": body.content,
    }
    ins = sb.table("chat_messages").insert(payload).execute()
    if not ins.data or len(ins.data) == 0:
        raise HTTPException(status_code=400, detail="No se pudo insertar el mensaje")
    inserted = ins.data[0]

    # 3) Perfil básico para la respuesta
    ures = (
        sb.table("usuarios")
        .select("id, nombre, foto_url")
        .eq("id", str(user_id))
        .limit(1)
        .execute()
        .data
    )
    u = ures[0] if ures else {"id": user_id, "nombre": "Yo", "foto_url": None}

    return MessageOut(
        id=inserted["id"],
        chat_id=inserted["chat_id"],
        user=ChatUser(**u),
        content=inserted["content"],
        created_at=_parse_dt(inserted.get("created_at")),
    )

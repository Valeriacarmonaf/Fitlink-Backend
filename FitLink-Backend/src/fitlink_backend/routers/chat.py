from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from uuid import UUID
from ..supabase_client import supabase
from ..models.ChatModels import ChatCreate, MessageCreate, ChatSummary, MessageOut, ChatUser
from datetime import datetime

router = APIRouter(prefix="/chats", tags=["chats"])

# Utilidad temporal: extrae user_id de cabecera (cuando tengas auth real, reemplaza)
def get_current_user_id(x_user_id: Optional[str] = None):
    # En producción: valida JWT de Supabase y saca auth.user().id
    if not x_user_id:
        # placeholder: quitar cuando integres auth real
        raise HTTPException(status_code=401, detail="Auth requerida")
    return x_user_id

# --------- LISTA DE CHATS DEL USUARIO ---------
@router.get("", response_model=List[ChatSummary])
def list_my_chats(user_id: str = Depends(get_current_user_id)):
    # chats donde soy miembro
    member_rows = supabase.table("chat_members").select("chat_id").eq("user_id", user_id).execute().data or []
    if not member_rows: 
        return []
    chat_ids = [r["chat_id"] for r in member_rows]
    chat_rows = supabase.table("chats").select("*").in_("id", chat_ids).order("created_at", desc=True).execute().data

    # último mensaje por chat (simple)
    summaries: List[ChatSummary] = []
    for c in chat_rows:
        last = supabase.table("chat_messages").select("*").eq("chat_id", c["id"]).order("created_at", desc=True).limit(1).execute().data
        if last:
            summaries.append(ChatSummary(
                id=c["id"],
                title=c.get("title"),
                is_group=c.get("is_group", False),
                image_url=c.get("image_url"),
                last_message=last[0]["content"],
                last_time=datetime.fromisoformat(last[0]["created_at"].replace("Z","")),
                unread=0
            ))
        else:
            summaries.append(ChatSummary(
                id=c["id"],
                title=c.get("title"),
                is_group=c.get("is_group", False),
                image_url=c.get("image_url"),
                last_message=None,
                last_time=None,
                unread=0
            ))
    return summaries

# --------- CREAR CHAT (DM o grupo) ---------
@router.post("", response_model=ChatSummary)
def create_chat(payload: ChatCreate, user_id: str = Depends(get_current_user_id)):
    # crea chat
    chat_row = supabase.table("chats").insert({
        "title": payload.title,
        "is_group": payload.is_group,
        "created_by": user_id
    }).execute().data[0]

    # agrega creador + miembros
    member_ids = set([user_id] + [str(i) for i in payload.member_ids])
    supabase.table("chat_members").insert([
        {"chat_id": chat_row["id"], "user_id": mid} for mid in member_ids
    ]).execute()

    return ChatSummary(
        id=chat_row["id"],
        title=chat_row.get("title"),
        is_group=chat_row.get("is_group", False),
        image_url=chat_row.get("image_url"),
        last_message=None,
        last_time=None,
        unread=0
    )

# --------- LISTAR MENSAJES (paginado) ---------
@router.get("/{chat_id}/messages", response_model=List[MessageOut])
def list_messages(chat_id: UUID, user_id: str = Depends(get_current_user_id),
                  limit: int = Query(30, ge=1, le=100), before: Optional[str] = None):
    # verifica membresía
    is_member = supabase.table("chat_members").select("chat_id").eq("chat_id", str(chat_id)).eq("user_id", user_id).limit(1).execute().data
    if not is_member:
        raise HTTPException(status_code=403, detail="No eres miembro de este chat")

    q = supabase.table("chat_messages").select("*").eq("chat_id", str(chat_id)).order("created_at", desc=True)
    if before:
        q = q.lt("created_at", before)
    rows = q.limit(limit).execute().data

    # trae info de usuario (mínima) – si tienes tabla usuarios:
    msgs: List[MessageOut] = []
    for r in reversed(rows):  # orden cronológico ascendente en UI
        u = supabase.table("usuarios").select("id,nombre,foto_url").eq("id", r["user_id"]).limit(1).execute().data
        user = u[0] if u else {"id": r["user_id"], "nombre": "Usuario", "foto_url": None}
        msgs.append(MessageOut(
            id=r["id"], chat_id=r["chat_id"],
            user=ChatUser(**user),
            content=r["content"],
            created_at=datetime.fromisoformat(r["created_at"].replace("Z","")),
        ))
    return msgs

# --------- ENVIAR MENSAJE ---------
@router.post("/{chat_id}/messages", response_model=MessageOut)
def send_message(chat_id: UUID, payload: MessageCreate, user_id: str = Depends(get_current_user_id)):
    is_member = supabase.table("chat_members").select("chat_id").eq("chat_id", str(chat_id)).eq("user_id", user_id).limit(1).execute().data
    if not is_member:
        raise HTTPException(status_code=403, detail="No eres miembro de este chat")

    inserted = supabase.table("chat_messages").insert({
        "chat_id": str(chat_id),
        "user_id": user_id,
        "content": payload.content
    }).execute().data[0]

    u = supabase.table("usuarios").select("id,nombre,foto_url").eq("id", user_id).limit(1).execute().data
    user = u[0] if u else {"id": user_id, "nombre": "Yo", "foto_url": None}

    return MessageOut(
        id=inserted["id"], chat_id=inserted["chat_id"],
        user=ChatUser(**user),
        content=inserted["content"],
        created_at=datetime.fromisoformat(inserted["created_at"].replace("Z","")),
    )

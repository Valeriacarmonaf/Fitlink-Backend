from fastapi import APIRouter, Depends, HTTPException
from fitlink_backend.supabase_client import supabase
from fitlink_backend.deps.auth import get_current_user_id

router = APIRouter(prefix="/api/chats", tags=["chats"])

@router.post("/match")
def match_event(event_id: int, user_id: str = Depends(get_current_user_id)):
    # 1) Busca evento
    ev = supabase.table("eventos").select("id, creador_id").eq("id", event_id).single().execute()
    if not ev.data:
        raise HTTPException(status_code=404, detail="Evento no encontrado")

    owner_id = ev.data["creador_id"]
    if owner_id == user_id:
        raise HTTPException(status_code=400, detail="No puedes hacer match con tu propio evento")

    # 2) Busca/crea chat 1:1 (asume tablas chats y chat_members)
    #    - chat 'directo' entre owner_id y user_id
    # Buscar existente
    existing = supabase.rpc(
        "find_direct_chat",  # puedes crear una RPC en SQL o filtrar por convención
        {"u1": user_id, "u2": owner_id}
    ).execute()

    if existing.data and len(existing.data) > 0:
        chat_id = existing.data[0]["id"]
    else:
        # crear chat
        chat = supabase.table("chats").insert({"type": "direct"}).select("id").single().execute()
        chat_id = chat.data["id"]
        supabase.table("chat_members").insert([
            {"chat_id": chat_id, "user_id": user_id},
            {"chat_id": chat_id, "user_id": owner_id},
        ]).execute()

    return {"chatId": chat_id}

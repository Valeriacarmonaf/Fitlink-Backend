from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

# ----- Requests -----
class ChatCreate(BaseModel):
    title: Optional[str] = None
    is_group: bool = False
    member_ids: List[UUID] = []         # además del creador

class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

# ----- Responses -----
class ChatUser(BaseModel):
    id: UUID
    nombre: Optional[str] = None
    foto_url: Optional[str] = None

class ChatSummary(BaseModel):
    id: UUID
    title: Optional[str] = None
    is_group: bool
    image_url: Optional[str] = None
    last_message: Optional[str] = None
    last_time: Optional[datetime] = None
    unread: int = 0

class MessageOut(BaseModel):
    id: UUID
    chat_id: UUID
    user: ChatUser
    content: str
    created_at: datetime

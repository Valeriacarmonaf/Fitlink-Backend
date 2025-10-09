from fastapi import APIRouter, Query
from typing import List, Optional
from datetime import datetime, timezone
from fitlink_backend.supabase_client import supabase

router = APIRouter(prefix="/api/events", tags=["events"])

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

@router.get("/upcoming")
def upcoming_events(limit: int = Query(20, ge=1, le=100)) -> List[dict]:
    res = (supabase.table("eventos")
           .select("*")
           .gte("inicio", _now_iso())
           .order("inicio", desc=False)
           .limit(limit)
           .execute())
    return res.data or []

@router.get("")
def list_events(limit: int = Query(50, ge=1, le=200),
                estado: Optional[str] = None) -> List[dict]:
    q = supabase.table("eventos").select("*").order("inicio", desc=False).limit(limit)
    if estado:
        q = q.eq("estado", estado)
    res = q.execute()
    return res.data or []

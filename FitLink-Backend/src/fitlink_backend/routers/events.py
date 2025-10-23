# src/fitlink_backend/routers/events.py

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Literal
from datetime import datetime, timezone, date, time
from pydantic import BaseModel, EmailStr
from fitlink_backend.supabase_client import supabase

router = APIRouter(prefix="/api/events", tags=["events"])

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

# ---------- GETs que ya tienes ----------
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

# ---------- 🔥 NUEVO: POST /api/events ----------
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
def create_event(payload: EventCreate) -> dict:
    """
    Crea un evento público (sin login). Combina fecha+hora en 'inicio' (UTC)
    y guarda en la tabla 'eventos'.
    """
    try:
        # Combinar fecha + hora y guardarlo en UTC ISO8601
        inicio_utc = datetime.combine(payload.fecha, payload.hora).replace(tzinfo=timezone.utc).isoformat()

        # Ajusta estos nombres si tu tabla usa otros campos
        row = {
            "creador_nombre": payload.nombre,      # <-- cambia a tu columna real si difiere
            "creador_email": payload.email,        # idem
            "descripcion": payload.descripcion,    # o 'nombre_evento' si así la tienes
            "categoria": payload.categoria,
            "municipio": payload.municipio,
            "nivel": payload.nivel,
            "inicio": inicio_utc,
            "estado": "activo",
        }

        res = supabase.table("eventos").insert(row).execute()
        data = (res.data or [])
        if not data:
            raise HTTPException(status_code=400, detail="No se pudo crear el evento.")
        return data[0]

    except HTTPException:
        raise
    except Exception as e:
        # Útil en desarrollo; en prod podrías loguear el error
        raise HTTPException(status_code=500, detail=str(e))

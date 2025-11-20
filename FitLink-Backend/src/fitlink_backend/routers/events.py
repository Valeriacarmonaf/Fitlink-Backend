from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from datetime import datetime, timezone, date, time
from pydantic import BaseModel, EmailStr
from fitlink_backend.supabase_client import supabase

# Importar función para crear notificaciones
from fitlink_backend.routers.notificaciones import enviar_notificacion

router = APIRouter(prefix="/api/events", tags=["events"])


# --------------------- Helpers ---------------------

def _now_iso():
    """Retorna la hora actual en ISO UTC"""
    return datetime.now(timezone.utc).isoformat()


# --------------------- Modelos ---------------------

class EventCreate(BaseModel):
    nombre_evento: str
    descripcion: Optional[str] = None
    categoria: int               # BIGINT en tu tabla
    municipio: str
    fecha: date
    hora: time
    creador_email: EmailStr


# --------------------- GET -------------------------

@router.get("/upcoming")
def upcoming_events(limit: int = Query(20, ge=1, le=100)) -> List[dict]:
    res = (
        supabase.table("eventos")
        .select("*")
        .gte("inicio", _now_iso())
        .neq("estado", "cancelado")
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

    q = (
        supabase.table("eventos")
        .select("*")
        .order("inicio", desc=False)
        .limit(limit)
    )

    if estado:
        q = q.eq("estado", estado)

    res = q.execute()
    return res.data or []


# --------------------- POST: Crear Evento -------------------------

@router.post("", status_code=201)
def create_event(payload: EventCreate):

    try:
        # Convertir fecha + hora a UTC ISO8601
        inicio_utc = datetime.combine(payload.fecha, payload.hora) \
            .replace(tzinfo=timezone.utc).isoformat()

        row = {
            "nombre_evento": payload.nombre_evento,
            "descripcion": payload.descripcion,
            "categoria": payload.categoria,
            "municipio": payload.municipio,
            "inicio": inicio_utc,
            "estado": "activo",
            "creador_email": payload.creador_email
        }

        res = supabase.table("eventos").insert(row).execute()

        data = res.data or []
        if not data:
            raise HTTPException(400, "No se pudo crear el evento")

        evento = data[0]

        # Buscar id del usuario creador
        ures = (
            supabase.table("usuarios")
            .select("id")
            .eq("email", payload.creador_email)
            .maybe_single()
            .execute()
        )

        if ures.data:
            enviar_notificacion(
                usuario_id=ures.data["id"],
                titulo="Evento creado",
                mensaje=f"Tu evento '{evento['nombre_evento']}' ha sido creado.",
                tipo="entreno"
            )

        return evento

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# --------------------- PUT: Confirmar Evento ---------------------

@router.put("/{event_id}/confirmar")
def confirmar_evento(event_id: int):

    try:
        res = (
            supabase.table("eventos")
            .select("*")
            .eq("id", event_id)
            .single()
            .execute()
        )

        evento = res.data
        if not evento:
            raise HTTPException(404, "Evento no encontrado")

        supabase.table("eventos").update(
            {"estado": "confirmado"}
        ).eq("id", event_id).execute()

        # Notificar
        creador_email = evento["creador_email"]

        ures = (
            supabase.table("usuarios")
            .select("id")
            .eq("email", creador_email)
            .maybe_single()
            .execute()
        )

        if ures.data:
            enviar_notificacion(
                usuario_id=ures.data["id"],
                titulo="Entrenamiento confirmado",
                mensaje=f"Tu entrenamiento '{evento['nombre_evento']}' ha sido confirmado.",
                tipo="match"
            )

        return {"status": "ok"}

    except Exception as e:
        raise HTTPException(500, detail=str(e))


# --------------------- PUT: Cancelar Evento ----------------------

@router.put("/{event_id}/cancelar")
def cancelar_evento(event_id: int):

    try:
        res = (
            supabase.table("eventos")
            .select("*")
            .eq("id", event_id)
            .single()
            .execute()
        )

        evento = res.data
        if not evento:
            raise HTTPException(404, "Evento no encontrado")

        supabase.table("eventos").update(
            {"estado": "cancelado"}
        ).eq("id", event_id).execute()

        creador_email = evento["creador_email"]

        ures = (
            supabase.table("usuarios")
            .select("id")
            .eq("email", creador_email)
            .maybe_single()
            .execute()
        )

        if ures.data:
            enviar_notificacion(
                usuario_id=ures.data["id"],
                titulo="Entrenamiento cancelado",
                mensaje=f"Tu entrenamiento '{evento['nombre_evento']}' ha sido cancelado.",
                tipo="entreno"
            )

        return {"status": "ok"}

    except Exception as e:
        raise HTTPException(500, detail=str(e))


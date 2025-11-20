# src/fitlink_backend/routes/notificaciones.py
from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated, Any
from fitlink_backend.supabase_client import supabase
from fitlink_backend.auth import get_current_user

router = APIRouter(
    prefix="/notificaciones",
    tags=["Notificaciones"]
)

# --------------------------------------------
# Utilidad: Enviar notificación desde cualquier ruta
# --------------------------------------------
def enviar_notificacion(usuario_id: str, titulo: str, mensaje: str, tipo="sistema"):
    """
    Inserta una fila en notificaciones. usuario_id debe ser el UUID del usuario (no el email),
    porque la tabla de preferencias y el resto usan usuario_id (uuid).
    """
    try:
        supabase.table("notificaciones").insert({
            "usuario_id": usuario_id,
            "titulo": titulo,
            "mensaje": mensaje,
            "tipo": tipo
        }).execute()
    except Exception as e:
        print(f"Error enviando notificación: {e}")


# --------------------------------------------
# Obtener notificaciones del usuario
# --------------------------------------------
@router.get("/")
async def obtener_notificaciones(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    res = supabase.table("notificaciones") \
        .select("*") \
        .eq("usuario_id", current_user.id) \
        .order("fecha", desc=True) \
        .execute()

    return res.data or []


# --------------------------------------------
# Marcar una notificación como leída
# --------------------------------------------
@router.put("/{notif_id}/leer")
async def marcar_como_leida(
    notif_id: str,
    current_user: Annotated[Any, Depends(get_current_user)]
):
    supabase.table("notificaciones") \
        .update({"leida": True}) \
        .eq("id", notif_id) \
        .eq("usuario_id", current_user.id) \
        .execute()

    return {"status": "ok"}


# --------------------------------------------
# Obtener preferencias
# --------------------------------------------
@router.get("/preferencias")
async def obtener_preferencias(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    res = supabase.table("preferencias_notificaciones") \
        .select("*") \
        .eq("usuario_id", current_user.id) \
        .maybe_single() \
        .execute()

    # Si no existen, creamos las preferencias por defecto
    if not res.data:
        supabase.table("preferencias_notificaciones").insert({
            "usuario_id": current_user.id
        }).execute()

        return {
            "notificar_entrenos": True,
            "notificar_match": True,
            "notificar_sistema": True
        }

    return res.data


# --------------------------------------------
# Guardar preferencias
# --------------------------------------------
@router.put("/preferencias")
async def guardar_preferencias(
    preferencias: dict,
    current_user: Annotated[Any, Depends(get_current_user)]
):
    supabase.table("preferencias_notificaciones") \
        .update(preferencias) \
        .eq("usuario_id", current_user.id) \
        .execute()

    return {"status": "ok"}


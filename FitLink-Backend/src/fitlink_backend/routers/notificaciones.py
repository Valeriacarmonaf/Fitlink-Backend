# src/fitlink_backend/routes/notificaciones.py
from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated, Any

from fitlink_backend.supabase_client import supabase
from fitlink_backend.auth import get_current_user

router = APIRouter(
    prefix="/notificaciones",
    tags=["Notificaciones"]
)


def enviar_notificacion(usuario_id: str, titulo: str, mensaje: str, tipo="sistema"):
    try:
        supabase.table("notificaciones").insert({
            "usuario_id": usuario_id,
            "titulo": titulo,
            "mensaje": mensaje,
            "tipo": tipo
        }).execute()
    except Exception as e:
        print(f"Error enviando notificación: {e}")


@router.get("/")
async def obtener_notificaciones(current_user: Annotated[Any, Depends(get_current_user)]):
    res = (
        supabase.table("notificaciones")
        .select("*")
        .eq("usuario_id", current_user.id)
        .order("fecha", desc=True)
        .execute()
    )
    return res.data or []


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


@router.get("/preferencias")
async def obtener_preferencias(current_user: Annotated[Any, Depends(get_current_user)]):
    res = (
        supabase.table("preferencias_notificaciones")
        .select("*")
        .eq("usuario_id", current_user.id)
        .maybe_single()
        .execute()
    )

    if not res.data:
        supabase.table("preferencias_notificaciones").insert({
            "usuario_id": current_user.id,
            "notificar_entrenos": True,
            "notificar_match": True,
            "notificar_sistema": True,
        }).execute()

        return {
            "notificar_entrenos": True,
            "notificar_match": True,
            "notificar_sistema": True,
        }

    return res.data


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

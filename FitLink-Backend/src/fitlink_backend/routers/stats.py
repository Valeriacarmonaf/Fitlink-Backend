from fastapi import APIRouter
from datetime import datetime, timezone
from typing import Dict
from fitlink_backend.supabase_client import supabase

router = APIRouter(prefix="/api", tags=["stats"])

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

@router.get("/stats")
def stats() -> Dict[str, int]:
    # Usuarios (ajusta el nombre de la tabla si es distinto)
    r_users = supabase.table("usuarios").select("id", count="exact").execute()
    usuarios = r_users.count or 0

    # --- SECCIÓN CORREGIDA ---
    # Contar el total de categorías definidas en la tabla 'categoria'
    r_cats = supabase.table("categoria").select("id", count="exact").execute()
    categorias = r_cats.count or 0
    # --- FIN DE LA CORRECCIÓN ---

    # Próximos eventos (inicio >= ahora)
    r_up = (
        supabase.table("eventos")
        .select("id", count="exact")
        .gte("inicio", _now_iso())
        .execute()
    )
    eventosProximos = r_up.count or 0

    return {"usuarios": usuarios, "categorias": categorias, "eventosProximos": eventosProximos}
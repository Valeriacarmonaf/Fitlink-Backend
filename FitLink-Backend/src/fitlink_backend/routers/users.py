from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated, Any
from fitlink_backend.supabase_client import supabase
from fitlink_backend.dependencies import get_current_user

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def clean_user_data(user: dict):
    """Elimina relaciones anidadas que no queremos enviar al frontend."""
    user.pop("usuario_categoria", None)
    return user


# ---------------------------------------------------------------------------
# CRUD DE USUARIOS
# ---------------------------------------------------------------------------

@router.get("/")
async def list_users():
    """Lista TODOS los usuarios"""
    res = supabase.table("usuarios").select("*").execute()
    return res.data


@router.get("/{user_id}")
async def get_user(user_id: int):
    """Obtiene un solo usuario por ID"""
    res = supabase.table("usuarios").select("*").eq("id", user_id).single().execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return res.data


@router.post("/")
async def create_user(body: dict):
    """Crea un usuario manualmente (para pruebas)."""
    res = supabase.table("usuarios").insert(body).execute()
    return res.data


@router.put("/{user_id}")
async def update_user(user_id: int, body: dict):
    """Actualiza un usuario existente."""
    res = supabase.table("usuarios").update(body).eq("id", user_id).execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return res.data[0]


@router.delete("/{user_id}")
async def delete_user(user_id: int):
    """Elimina un usuario por ID"""
    supabase.table("usuarios").delete().eq("id", user_id).execute()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# SUGERENCIAS DE USUARIOS
# ---------------------------------------------------------------------------

@router.get("/suggestions")
async def get_user_suggestions(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    """
    Obtiene sugerencias de usuarios con 4 niveles de prioridad:
        P1 → mismo municipio + misma habilidad
        P2 → mismo municipio + misma categoría
        P3 → mismo municipio
        P4 → mismas habilidades
        
    Con `usuario_categoria` como tabla relacional.
    """

    try:
        user_id = current_user.id
        user_email = current_user.email

        # -----------------------------
        # Obtener municipio
        # -----------------------------
        profile_res = (
            supabase.table("usuarios")
            .select("municipio")
            .eq("id", user_id)
            .single()
            .execute()
        )

        my_municipio = profile_res.data.get("municipio") if profile_res.data else None

        # -----------------------------
        # Obtener mis habilidades
        # -----------------------------
        my_skills_res = (
            supabase.table("usuario_categoria")
            .select("categoria_id, nivel_id")
            .eq("usuario_email", user_email)
            .execute()
        )

        my_skills_data = my_skills_res.data or []

        my_skill_set = set((s["categoria_id"], s["nivel_id"]) for s in my_skills_data)
        my_category_set = set(s["categoria_id"] for s in my_skills_data)

        # Si no hay municipio ni habilidades, no hay sugerencias
        if not my_municipio and not my_skills_data:
            return []

        # -----------------------------
        # Obtener otros usuarios
        # -----------------------------
        all_other_users_res = (
            supabase.table("usuarios")
            .select("id, nombre, biografia, municipio, foto_url, usuario_categoria(categoria_id, nivel_id)")
            .neq("id", user_id)
            .execute()
        )

        if not all_other_users_res.data:
            return []

        p1, p2, p3, p4 = [], [], [], []

        for user in all_other_users_res.data:
            user_municipio = user.get("municipio")
            user_skills_data = user.get("usuario_categoria", [])

            user_skill_set = set((s["categoria_id"], s["nivel_id"]) for s in user_skills_data)
            user_category_set = set(s["categoria_id"] for s in user_skills_data)

            matches_municipio = (user_municipio == my_municipio) and my_municipio is not None
            shared_skills = my_skill_set & user_skill_set
            shared_categories = my_category_set & user_category_set

            # PRIORIDADES
            if matches_municipio and shared_skills:
                user["suggestion_reason"] = "municipio_y_habilidad"
                p1.append(clean_user_data(user))

            elif matches_municipio and shared_categories:
                user["suggestion_reason"] = "municipio_y_categoria"
                p2.append(clean_user_data(user))

            elif matches_municipio:
                user["suggestion_reason"] = "municipio"
                p3.append(clean_user_data(user))

            elif shared_skills:
                user["suggestion_reason"] = "habilidad"
                p4.append(clean_user_data(user))

        return p1 + p2 + p3 + p4

    except Exception as e:
        print(f"Error inesperado en /users/suggestions: {e}")
        raise HTTPException(500, "Error interno del servidor")

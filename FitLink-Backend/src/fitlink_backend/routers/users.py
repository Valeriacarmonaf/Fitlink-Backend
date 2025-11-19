from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Annotated, Any, Optional
from fastapi.responses import JSONResponse
from typing import Annotated, Any
import datetime

# Importa el cliente de DB y el dependency de auth
from fitlink_backend.supabase_client import supabase
from fitlink_backend.dependencies import get_current_user
from fitlink_backend.supabase_client import get_admin_client

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# Pequeña función para limpiar el objeto de usuario antes de enviarlo
def clean_user_data(user):
    if 'usuario_categoria' in user:
        del user['usuario_categoria'] # No necesitamos enviar esto al frontend
    return user

@router.get("/suggestions")
async def get_user_suggestions(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    """
    Obtiene sugerencias de usuarios, ordenadas por prioridad:
    1. Coincide Municipio, Categoría y Nivel
    2. Coincide Municipio y Categoría (cualquier nivel)
    3. Coincide Solo Municipio
    4. Coincide Solo Categoría y Nivel
    """
    try:
        user_id = current_user.id
        user_email = current_user.email

        # --- 1. Obtener datos del usuario actual ---
        
        # Municipio
        profile_res = supabase.table("usuarios") \
            .select("municipio") \
            .eq("id", user_id) \
            .single() \
            .execute()
        
        my_municipio = profile_res.data.get('municipio') if profile_res.data else None

        # Habilidades (Categoría y Nivel)
        my_skills_res = supabase.table("usuario_categoria") \
            .select("categoria_id, nivel_id") \
            .eq("usuario_email", user_email) \
            .execute()

        my_skills_data = my_skills_res.data or []
        
        # Sets para comparaciones rápidas
        # Set de tuplas: (categoria_id, nivel_id)
        my_skill_set = set(
            (s['categoria_id'], s['nivel_id']) for s in my_skills_data
        )
        # Set de solo IDs de categoría
        my_category_set = set(s['categoria_id'] for s in my_skills_data)

        if not my_municipio and not my_skills_data:
            return [] # No hay nada con qué comparar

        # --- 2. Obtener TODOS los otros usuarios y sus habilidades ---
        # (Filtramos en Python para manejar la lógica de prioridad compleja)
        
        all_other_users_res = supabase.table("usuarios") \
            .select("id, nombre, biografia, municipio, foto_url, usuario_categoria(categoria_id, nivel_id)") \
            .neq("id", user_id) \
            .execute()

        if not all_other_users_res.data:
            return []

        # --- 3. Listas de Prioridad ---
        p1_users = [] # Mismo Municipio, Categoría y Nivel
        p2_users = [] # Mismo Municipio y Categoría (dif. nivel)
        p3_users = [] # Solo Mismo Municipio
        p4_users = [] # Solo Misma Categoría y Nivel

        # --- 4. Clasificar usuarios ---
        for user in all_other_users_res.data:
            user_municipio = user.get('municipio')
            user_skills_data = user.get('usuario_categoria', [])

            user_skill_set = set(
                (s['categoria_id'], s['nivel_id']) for s in user_skills_data
            )
            user_category_set = set(
                s['categoria_id'] for s in user_skills_data
            )

            # Comparaciones
            matches_municipio = (user_municipio == my_municipio) and my_municipio is not None
            shared_skills = my_skill_set.intersection(user_skill_set)
            shared_categories = my_category_set.intersection(user_category_set)
            
            # Asignar a listas de prioridad
            if matches_municipio and shared_skills:
                user['suggestion_reason'] = 'municipio_y_habilidad'
                p1_users.append(clean_user_data(user))
            
            elif matches_municipio and shared_categories:
                user['suggestion_reason'] = 'municipio_y_categoria'
                p2_users.append(clean_user_data(user))
            
            elif matches_municipio:
                user['suggestion_reason'] = 'municipio'
                p3_users.append(clean_user_data(user))
            
            elif shared_skills:
                user['suggestion_reason'] = 'habilidad'
                p4_users.append(clean_user_data(user))

        # --- 5. Combinar y Retornar ---
        # Unimos las listas en orden de prioridad
        return p1_users + p2_users + p3_users + p4_users

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error inesperado en /users/suggestions: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.post("/{user_id}/report", status_code=201)
async def report_user(
    user_id: str,
    current_user: Annotated[Any, Depends(get_current_user)],
    reason: Optional[str] = Body(None, embed=True),
):
    """
    Reporta a un usuario. Si un usuario alcanza 3 o más reportes, lo marca como `is_blocked`.
    """
    try:
        reporter_id = current_user.id
        if reporter_id == user_id:
            raise HTTPException(status_code=400, detail="No puedes reportarte a ti mismo.")

        admin = get_admin_client()

        # Insertar reporte (capturamos excepciones lanzadas por el cliente si la BD rechaza)
        try:
            ins = admin.table("user_reports").insert({
                "reported_id": user_id,
                "reporter_id": reporter_id,
                "reason": reason,
            }).execute()
        except Exception as db_exc:
            # Mensaje de error puede venir como dict/string que contiene el código 23505
            msg = str(db_exc)
            low = msg.lower()
            if '23505' in low or 'duplicate key' in low or 'unique' in low:
                # Ya existe un reporte por ese reporter → devolver 409 con JSON limpio
                reports_res = admin.table("user_reports").select("id").eq("reported_id", user_id).execute()
                reports_count = len(reports_res.data or [])
                return JSONResponse(status_code=409, content={
                    "message": "Ya reportaste a este usuario.",
                    "reports_count": reports_count
                })
            # Otros errores de BD
            print(f"DB insert error al reportar usuario {user_id}: {msg}")
            raise HTTPException(status_code=500, detail="Error al insertar reporte en la base de datos")

        # Si la respuesta de la inserción contiene un error, manejarlo.
        if getattr(ins, 'error', None):
            err_msg = getattr(ins.error, 'message', str(ins.error))
            low = err_msg.lower() if isinstance(err_msg, str) else ''
            # Distinguir conflicto de duplicado (mismo reporter reportando mismo usuario)
            if 'duplicate' in low or '23505' in low or 'unique' in low:
                # Obtener conteo actual y devolver 409 para indicar que ya reportó
                reports_res = admin.table("user_reports").select("id").eq("reported_id", user_id).execute()
                reports_count = len(reports_res.data or [])
                # Devolver JSON limpio y legible para el frontend
                return JSONResponse(status_code=409, content={
                    "message": "Ya reportaste a este usuario.",
                    "reports_count": reports_count
                })
            else:
                raise HTTPException(status_code=500, detail=err_msg)

        # Contar reportes del usuario
        reports_res = admin.table("user_reports").select("id").eq("reported_id", user_id).execute()
        reports_count = len(reports_res.data or [])

        if reports_count >= 3:
            # bloquear usuario
            admin.table("usuarios").update({"is_blocked": True}).eq("id", user_id).execute()

        return {"message": "Reporte registrado", "reports_count": reports_count}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error al reportar usuario {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
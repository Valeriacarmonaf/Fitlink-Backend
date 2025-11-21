from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Annotated, Any, Optional
from fastapi.responses import JSONResponse
from fitlink_backend.supabase_client import supabase
from fitlink_backend.dependencies import get_current_user
from fitlink_backend.supabase_client import get_admin_client

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def clean_user_data(user: dict):
    """Elimina relaciones anidadas que no queremos enviar al frontend."""
    # Mantengo la función aunque se ha simplificado su necesidad
    user.pop("usuario_categoria", None)
    return user

@router.get("/me")
async def get_my_profile_data(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    """
    Obtiene los datos del perfil completo. Ahora lee 'nivel_habilidad' de la tabla 'usuarios'.
    """
    try:
       user_id = current_user.id
      
       select_fields = (
          "id, email, nombre, carnet, biografia, fecha_nacimiento, "
          "municipio, foto_url, cedula, telefono, intereses, nivel_habilidad" # <-- Obtener nivel y intereses
       )

       profile_res = supabase.table("usuarios") \
          .select(select_fields) \
          .eq("id", user_id) \
          .single() \
          .execute()
 
       if not profile_res.data:
          raise HTTPException(status_code=404, detail="Perfil de usuario no encontrado")
      
       user_data = profile_res.data
      
       profile_clean = {
          "id": user_data.get("id"),
          "email": user_data.get("email") or "",
          "nombre": user_data.get("nombre") or "",
          "carnet": user_data.get("carnet") or "",
          "cedula": user_data.get("cedula") or "",
          "biografia": user_data.get("biografia") or "",
          "fecha_nacimiento": user_data.get("fecha_nacimiento") or "",
          "municipio": user_data.get("municipio") or "",
          "foto_url": user_data.get("foto_url") or "",
          "telefono": user_data.get("telefono") or "",
          "nivel_habilidad": user_data.get("nivel_habilidad"), # <-- Nivel ID
          "intereses_seleccionados": user_data.get("intereses") or [] # <-- Intereses
       }
      
       print(f"✅ Perfil preparado - Nivel ID: {profile_clean['nivel_habilidad']}")
       return {"data": profile_clean}

    except HTTPException as e:
       raise e
    except Exception as e:
       print(f"Error inesperado en /users/me (GET): {e}")
       raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.put("/me")
async def update_my_profile(
    profile_data: dict,
    current_user: Annotated[Any, Depends(get_current_user)]
):
    """
    Actualiza el perfil del usuario.
    El nivel de habilidad se guarda directamente en la columna nivel_habilidad de la tabla usuarios.
    """
    try:
        user_id = current_user.id
        
        # 1. Preparar datos para actualizar en la tabla usuarios
        update_data = {}
        fields_to_update = [
            "nombre", "carnet", "cedula", "biografia", "fecha_nacimiento", 
            "municipio", "telefono", "foto_url", "intereses", "nivel_habilidad" # <- Incluir nivel_habilidad
        ]
        
        for field in fields_to_update:
            # NOTA: La clave en el frontend es 'nivel_habilidad', así que la esperamos así.
            if field in profile_data: 
                update_data[field] = profile_data[field]
        
        # 2. Actualizar datos básicos en la tabla usuarios
        if update_data:
            print(f"💾 Actualizando usuario {user_id} con datos: {update_data}")
            
            update_res = supabase.table("usuarios") \
                .update(update_data) \
                .eq("id", user_id) \
                .execute()
            
            if not update_res.data:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

        return {
            "data": update_res.data[0] if update_data else {}, 
            "message": "Perfil actualizado correctamente"
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error actualizando perfil: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")
    
# ---------------------------------------------------------------------------
# Endpoints de Soporte y Sugerencias (Se mantienen sin cambios relevantes)
# ---------------------------------------------------------------------------

@router.get("/categorias")
async def get_categorias():
    """
    Obtiene todas las categorías deportivas disponibles.
    """
    try:
        categorias_res = supabase.table("categoria") \
            .select("id, nombre, icono") \
            .order("nombre") \
            .execute()
        
        return {"data": categorias_res.data or []}
    
    except Exception as e:
        print(f"Error obteniendo categorías: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.get("/niveles")
async def get_niveles_habilidad():
    """
    Obtiene todos los niveles de habilidad disponibles (1-5).
    """
    try:
        niveles_res = supabase.table("niveles_habilidad") \
            .select("id, nombre") \
            .order("id") \
            .execute()
        
        return {"data": niveles_res.data or []}
    
    except Exception as e:
        print(f"Error obteniendo niveles: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.get("/suggestions")
async def get_user_suggestions(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    """
    Obtiene sugerencias de usuarios, usando las columnas 'intereses' y 'nivel_habilidad' 
    de la tabla 'usuarios'. (Esta lógica ya estaba correcta).
    """

    try:
        user_id = current_user.id
        
        # Obtener municipio, intereses y nivel de habilidad del usuario actual
        profile_res = (
            supabase.table("usuarios")
            .select("municipio, intereses, nivel_habilidad")
            .eq("id", user_id)
            .single()
            .execute()
        )

        user_data = profile_res.data
        if not user_data:
            raise HTTPException(status_code=404, detail="Perfil de usuario no encontrado.")

        my_municipio = user_data.get("municipio")
        # 'intereses' es un array de IDs (ej. [1, 5, 8])
        my_category_ids = set(user_data.get("intereses") or []) 
        # 'nivel_habilidad' es un INT (ej. 3)
        my_skill_level = user_data.get("nivel_habilidad")

        # Si no hay municipio, intereses o nivel de habilidad, no hay sugerencias
        if not my_municipio and not my_category_ids and my_skill_level is None:
            return []

        # Obtener otros usuarios
        all_other_users_res = (
            supabase.table("usuarios")
            .select("id, nombre, biografia, municipio, foto_url, intereses, nivel_habilidad")
            .neq("id", user_id)
            .execute()
        )

        if not all_other_users_res.data:
            return []

        p1, p2, p3, p4 = [], [], [], []
        suggested_ids = set()

        for user in all_other_users_res.data:
            user_id_check = user.get("id")
            
            if user_id_check in suggested_ids:
                continue
                
            user_municipio = user.get("municipio")
            user_category_ids = set(user.get("intereses") or [])
            user_skill_level = user.get("nivel_habilidad")

            # Comparaciones
            matches_municipio = (user_municipio == my_municipio) and my_municipio is not None
            matches_skill_level = (user_skill_level == my_skill_level) and my_skill_level is not None
            shared_categories = bool(my_category_ids & user_category_ids)

            # Lógica de Prioridades
            
            # PRIORIDAD 1: mismo municipio + mismo nivel de habilidad
            if matches_municipio and matches_skill_level:
                user["suggestion_reason"] = "municipio_y_nivel_habilidad"
                p1.append(user)
                suggested_ids.add(user_id_check)

            # PRIORIDAD 2: mismo municipio + misma categoría (interés)
            elif matches_municipio and shared_categories:
                user["suggestion_reason"] = "municipio_y_categoria"
                p2.append(user)
                suggested_ids.add(user_id_check)

            # PRIORIDAD 3: mismo municipio
            elif matches_municipio:
                user["suggestion_reason"] = "municipio"
                p3.append(user)
                suggested_ids.add(user_id_check)

            # PRIORIDAD 4: mismo nivel de habilidad
            elif matches_skill_level:
                user["suggestion_reason"] = "nivel_habilidad"
                p4.append(user)
                suggested_ids.add(user_id_check)

        # Combinamos y retornamos los resultados
        return p1 + p2 + p3 + p4

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
    (Se mantiene sin cambios).
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
            msg = str(db_exc)
            low = msg.lower()
            if '23505' in low or 'duplicate key' in low or 'unique' in low:
                reports_res = admin.table("user_reports").select("id").eq("reported_id", user_id).execute()
                reports_count = len(reports_res.data or [])
                return JSONResponse(status_code=409, content={
                    "message": "Ya reportaste a este usuario.",
                    "reports_count": reports_count
                })
            print(f"DB insert error al reportar usuario {user_id}: {msg}")
            raise HTTPException(status_code=500, detail="Error al insertar reporte en la base de datos")

        if getattr(ins, 'error', None):
            err_msg = getattr(ins.error, 'message', str(ins.error))
            low = err_msg.lower() if isinstance(err_msg, str) else ''
            if 'duplicate' in low or '23505' in low or 'unique' in low:
                reports_res = admin.table("user_reports").select("id").eq("reported_id", user_id).execute()
                reports_count = len(reports_res.data or [])
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
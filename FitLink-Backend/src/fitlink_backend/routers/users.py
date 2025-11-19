from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated, Any

# Importa el cliente de DB y el dependency de auth
from fitlink_backend.supabase_client import supabase
from fitlink_backend.dependencies import get_current_user

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# Pequeña función para limpiar el objeto de usuario antes de enviarlo
def clean_user_data(user):
    if 'usuario_categoria' in user:
        del user['usuario_categoria'] # No necesitamos enviar esto al frontend
    return user

@router.get("/me")
async def get_my_profile_data(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    """
    Obtiene los datos del perfil completo del usuario autenticado.
    El nivel deportivo viene de usuario_categoria y categoria.
    """
    try:
        user_id = current_user.id
        user_email = current_user.email
        
        # 1. Obtener datos básicos del usuario (sin nivel_deportivo)
        select_fields = (
            "id, email, nombre, carnet, biografia, fecha_nacimiento, "
            "municipio, foto_url, cedula, telefono, intereses"
            # NOTA: nivel_deportivo no existe en esta tabla
        )

        profile_res = supabase.table("usuarios") \
            .select(select_fields) \
            .eq("id", user_id) \
            .single() \
            .execute()

        if not profile_res.data:
            raise HTTPException(status_code=404, detail="Perfil de usuario no encontrado")
        
        user_data = profile_res.data

        # 2. Obtener el nivel deportivo desde usuario_categoria
        nivel_deportivo = ""
        try:
            # Consultar usuario_categoria para obtener el nivel_id
            nivel_res = supabase.table("usuario_categoria") \
                .select("nivel_id, categoria_id") \
                .eq("usuario_email", user_email) \
                .execute()

            if nivel_res.data and len(nivel_res.data) > 0:
                # Tomar el primer resultado (puede haber múltiples categorías)
                nivel_info = nivel_res.data[0]
                nivel_id = nivel_info.get('nivel_id')
                
                # Mapear nivel_id a nombre de nivel
                nivel_mapping = {
                    1: "principiante",
                    2: "en progreso", 
                    3: "intermedio",
                    4: "avanzado",
                    5: "experto"
                }
                
                nivel_deportivo = nivel_mapping.get(nivel_id, "")
                print(f"🔍 Nivel deportivo encontrado: ID {nivel_id} -> {nivel_deportivo}")
            else:
                print("⚠️ No se encontró nivel deportivo para el usuario")
                
        except Exception as e:
            print(f"❌ Error obteniendo nivel deportivo: {e}")
            nivel_deportivo = ""

        # 3. Estructura que espera el frontend
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
            "nivel_deportivo": nivel_deportivo,  # ← Ahora viene de usuario_categoria
            "intereses_seleccionados": user_data.get("intereses") or []
        }
        
        print(f"✅ Perfil preparado - Nivel deportivo: {nivel_deportivo}")
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
    El nivel deportivo se guarda en usuario_categoria.
    """
    try:
        user_id = current_user.id
        user_email = current_user.email
        
        # 1. Preparar datos para actualizar en la tabla usuarios
        update_data = {}
        fields_to_update = [
            "nombre", "carnet", "cedula", "biografia", "fecha_nacimiento", 
            "municipio", "telefono", "foto_url", "intereses"
        ]
        
        for field in fields_to_update:
            if field in profile_data:
                update_data[field] = profile_data[field]
        
        # 2. Actualizar datos básicos en la tabla usuarios
        if update_data:
            update_res = supabase.table("usuarios") \
                .update(update_data) \
                .eq("id", user_id) \
                .execute()
            
            if not update_res.data:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

        # 3. Manejar la actualización del nivel deportivo en usuario_categoria
        if "nivel_deportivo" in profile_data:
            nivel_id = profile_data["nivel_deportivo"]
            
            # Validar que nivel_id sea un número entre 1-5
            if nivel_id and isinstance(nivel_id, int) and 1 <= nivel_id <= 5:
                try:
                    # Verificar si ya existe una entrada para este usuario
                    existing_entry = supabase.table("usuario_categoria") \
                        .select("categoria_id, nivel_id") \
                        .eq("usuario_email", user_email) \
                        .execute()
                    
                    categoria_id = 1  # Categoría por defecto
                    
                    if existing_entry.data and len(existing_entry.data) > 0:
                        # Actualizar entrada existente
                        categoria_id = existing_entry.data[0]['categoria_id']
                        
                        update_nivel_res = supabase.table("usuario_categoria") \
                            .update({
                                "nivel_id": nivel_id,
                                "categoria_id": categoria_id
                            }) \
                            .eq("usuario_email", user_email) \
                            .eq("categoria_id", categoria_id) \
                            .execute()
                            
                        print(f"✅ Nivel deportivo actualizado: ID {nivel_id}")
                        
                    else:
                        # Crear nueva entrada
                        insert_nivel_res = supabase.table("usuario_categoria") \
                            .insert({
                                "usuario_email": user_email,
                                "categoria_id": categoria_id,
                                "nivel_id": nivel_id
                            }) \
                            .execute()
                            
                        print(f"✅ Nivel deportivo creado: ID {nivel_id}")
                        
                except Exception as e:
                    print(f"❌ Error actualizando nivel deportivo: {e}")
                    # Continuar sin fallar completamente
            else:
                print(f"⚠️ Nivel ID inválido recibido: {nivel_id}")

        return {
            "data": update_res.data[0] if update_data else {}, 
            "message": "Perfil actualizado correctamente"
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error actualizando perfil: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")
    
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
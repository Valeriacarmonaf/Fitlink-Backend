from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated, Any
import datetime

# --- CAMBIO AQUÍ ---
from fitlink_backend.supabase_client import supabase
# --- FIN DEL CAMBIO ---
from fitlink_backend.dependencies import get_current_user

# Crea el router
router = APIRouter(
    prefix="/events", 
    tags=["Suggestions"]
)


@router.get("/suggestions")
async def get_event_suggestions(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    """
    Obtiene sugerencias de eventos (con lógica de prioridad).
    """
    try:
        user_id = current_user.id
        # El email ya no es necesario para obtener las categorías
        # user_email = current_user.email 

        # 1. Obtener el municipio y los intereses (categorías) del perfil
        # Se modificó la selección para obtener tanto 'municipio' como 'intereses'
        profile_res = supabase.table("usuarios") \
            .select("municipio, intereses") \
            .eq("id", user_id) \
            .single() \
            .execute()

        if not profile_res.data:
            raise HTTPException(status_code=404, detail="Perfil de usuario no encontrado.")

        user_municipio = profile_res.data.get('municipio')
        
        # 2. Obtener las IDs de las categorías (intereses) del usuario
        # Se obtiene directamente de la columna 'intereses' de la tabla 'usuarios'
        # El resultado es un array de int8, por lo que ya es la lista de IDs.
        my_category_ids = profile_res.data.get('intereses') or [] 

        # Se elimina la consulta a 'usuario_categoria'

        if not user_municipio and not my_category_ids:
            # Devuelve una lista vacía si no hay municipio ni intereses
            return []

        # --- Lógica de Prioridad ---
        now = datetime.datetime.utcnow().isoformat()
        # Se asegura que la relación con 'categoria' sigue siendo necesaria para obtener el nombre/icono
        select_cols = "*, categoria ( nombre, icono )" 
        
        p1_events = []
        p2_events = []
        p3_events = []
        
        # 1. PRIORIDAD 1: (Municipio Y Categoría)
        if user_municipio and my_category_ids:
            p1_res = supabase.table("eventos") \
                .select(select_cols) \
                .eq("municipio", user_municipio) \
                .in_("categoria", my_category_ids) \
                .gte("inicio", now) \
                .neq("estado", "cancelado") \
                .order("inicio", desc=False) \
                .execute()
            p1_events = p1_res.data or []
            for event in p1_events: 
                event['suggestion_reason'] = 'municipio_y_categoria'

        ids_en_p1 = {event['id'] for event in p1_events}

        # 2. PRIORIDAD 2: (Solo Municipio)
        if user_municipio:
            query = supabase.table("eventos") \
                .select(select_cols) \
                .eq("municipio", user_municipio) \
                .gte("inicio", now) \
                .neq("estado", "cancelado")
            
            if ids_en_p1:
                query = query.not_.in_("id", list(ids_en_p1))
            if my_category_ids:
                # Excluye eventos que coinciden con los intereses
                query = query.not_.in_("categoria", my_category_ids) 

            p2_res = query.order("inicio", desc=False).execute()
            p2_events = p2_res.data or []
            for event in p2_events: 
                event['suggestion_reason'] = 'municipio'

        ids_en_p1_y_p2 = ids_en_p1.union({event['id'] for event in p2_events})

        # 3. PRIORIDAD 3: (Solo Categoría)
        if my_category_ids:
            query = supabase.table("eventos") \
                .select(select_cols) \
                .in_("categoria", my_category_ids) \
                .gte("inicio", now) \
                .neq("estado", "cancelado")

            if ids_en_p1_y_p2:
                query = query.not_.in_("id", list(ids_en_p1_y_p2))
            if user_municipio:
                # Excluye eventos que ya fueron priorizados por municipio (P1 o P2)
                query = query.not_.eq("municipio", user_municipio) 
                
            p3_res = query.order("inicio", desc=False).execute()
            p3_events = p3_res.data or []
            for event in p3_events: 
                event['suggestion_reason'] = 'categoria'
        
        # --- Combinar Resultados ---
        return p1_events + p2_events + p3_events

    except HTTPException as e:
        raise e
    except Exception as e:
        # Se modificó para un mejor manejo de errores.
        print(f"Error inesperado en /events/suggestions: {e}") 
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")
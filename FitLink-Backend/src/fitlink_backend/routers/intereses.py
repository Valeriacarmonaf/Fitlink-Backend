from fastapi import APIRouter, HTTPException
from fitlink_backend.supabase_client import supabase # Importa tu cliente

router = APIRouter(
    prefix="/api/intereses",
    tags=["Intereses"]
)

@router.get("/")
async def get_all_intereses():
    """
    Obtiene la lista completa de intereses (categorías) 
    desde la tabla public.categoria.
    
    El frontend usa 'id', 'nombre' e 'icono'.
    """
    try:
        # 1. Consultar la tabla 'categoria'
        # Seleccionamos id, nombre e icono, ya que el frontend los usa todos
        response = supabase.table("categoria") \
            .select("id, nombre, icono") \
            .order("nombre", desc=False) \
            .execute()

        if not response.data:
            # Si no hay intereses, devolvemos una lista vacía
            return {"data": []}

        # 2. Limpiar datos: asegurar que 'icono' no sea None
        # El frontend renderiza: <span>{interes.icono} {interes.nombre}</span>
        # Si 'icono' es None, lo convertimos a string vacío ""
        clean_data = []
        for item in response.data:
            clean_data.append({
                "id": item.get("id"),
                "nombre": item.get("nombre"), # Este es 'not null' en la BD
                "icono": item.get("icono") or "" # Convertir None a ""
            })

        # 3. Devolver en el formato que el frontend espera
        return {"data": clean_data}
    
    except Exception as e:
        print(f"Error inesperado en /intereses: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")
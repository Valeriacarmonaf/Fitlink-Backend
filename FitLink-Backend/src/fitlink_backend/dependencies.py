from fastapi import Header, HTTPException
from typing import Annotated, Any

# --- CAMBIO AQUÍ ---
# Importa el cliente desde tu nuevo archivo
from fitlink_backend.supabase_client import supabase 
# --- FIN DEL CAMBIO ---

async def get_current_user(authorization: Annotated[str | None, Header()] = None) -> Any:
    """
    Dependencia de FastAPI para obtener el usuario autenticado a partir
    del token 'Authorization: Bearer ...'
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Falta el encabezado de autorización")
    
    token = authorization.replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Token malformado")

    try:
        user_response = supabase.auth.get_user(token)
        
        if user_response.user is None:
            raise HTTPException(status_code=401, detail="Token inválido o sesión expirada")
        
        return user_response.user
    
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Error de autenticación: {str(e)}")
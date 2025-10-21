from pydantic import BaseModel
from typing import Optional
import datetime

class UserSignUp(BaseModel):
    # Datos para el perfil público en la tabla 'usuarios'
    carnet: str
    nombre: str
    biografia: str
    fechaNacimiento: datetime.date
    ciudad: str
    foto: Optional[str] = None
    # Datos para la autenticación segura en Supabase Auth
    email: str
    password: str
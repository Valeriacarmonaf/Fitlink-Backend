from pydantic import BaseModel
from typing import Optional
import datetime

class UserSignUp(BaseModel):
    carnet: str
    nombre: str
    biografia: str
    fechaNacimiento: datetime.date
    ciudad: str
    foto: Optional[str] = None
    email: str
    password: str
from pydantic import BaseModel
import datetime

class UserCreate(BaseModel):
    id: str
    nombre: str
    biografia: str
    fechaNacimiento: datetime.date
    ciudad: str
    foto: str | None = None
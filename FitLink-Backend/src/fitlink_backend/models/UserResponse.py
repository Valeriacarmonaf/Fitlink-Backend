from pydantic import BaseModel
import datetime

class UserResponse(BaseModel):
    id: str
    nombre: str
    biografia: str
    fecha_nacimiento: datetime.date
    municipio: str
    foto_url: str | None = None

    model_config = { "from_attributes": True }
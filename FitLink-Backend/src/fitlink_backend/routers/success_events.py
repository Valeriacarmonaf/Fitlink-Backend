from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr

from fitlink_backend.supabase_client import supabase
from fitlink_backend.dependencies import get_current_user

router = APIRouter(prefix="/api/success-events", tags=["success-events"])

BUCKET = "eventos-exitosos"


# --------- Pydantic I/O ---------
class SuccessEventIn(BaseModel):
    """Payload para crear un evento exitoso SIN archivos (referencia)"""
    titulo: str = Field(..., min_length=3, max_length=120)
    descripcion: str = Field(..., min_length=1, max_length=1500)
    fecha: str = Field(
        ...,
        pattern=r"^(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])/[0-9]{4}$"  # mm/dd/yyyy (Pydantic v2 -> pattern)
    )
    municipio: str = Field(..., min_length=2, max_length=120)


class SuccessEventOut(BaseModel):
    id: int
    titulo: str
    descripcion: str
    fecha: str          
    municipio: str
    fotos: List[str]
    created_at: str
    usuario_email: EmailStr


# --------- Helpers ---------
def _ensure_bucket() -> None:
    """
    Crea el bucket si no existe. Si la key no tiene permiso para crear,
    simplemente continuamos (asumimos que ya existe).
    """
    try:
        buckets = supabase.storage.list_buckets()
        # objetos o dicts, según versión del cliente
        def _name(b):
            return getattr(b, "name", None) or (isinstance(b, dict) and b.get("name"))
        if not any(_name(b) == BUCKET for b in buckets):
            supabase.storage.create_bucket(BUCKET, public=False)
    except Exception:
       
        pass


def _store_file(user_email: str, f: UploadFile) -> str:
    """
    Guarda un archivo en Storage y retorna una URL firmada (1 año).
    """
    _ensure_bucket()
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    safe_name = (f.filename or "file").replace(" ", "_")
    object_path = f"{user_email}/{ts}-{safe_name}"

    data = f.file.read()
    if not data:
        raise HTTPException(status_code=400, detail=f"El archivo {safe_name} está vacío.")

    supabase.storage.from_(BUCKET).upload(
        object_path,
        data,
        file_options={"content-type": f.content_type or "application/octet-stream"}
    )

    signed = supabase.storage.from_(BUCKET).create_signed_url(object_path, 60 * 60 * 24 * 365)
    url = signed.get("signedURL") or signed.get("signedUrl") or ""
    return url or object_path


# --------- Endpoints ---------
@router.get("", response_model=List[SuccessEventOut])
def list_success_events(user: Any = Depends(get_current_user)) -> List[dict]:
    """
    Lista de eventos exitosos (más recientes primero). Requiere usuario autenticado.
    """
    try:
        res = supabase.table("eventos_exitosos").select("*").order("created_at", desc=True).execute()
        return res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=SuccessEventOut)
async def create_success_event(
    titulo: str = Form(...),
    descripcion: str = Form(...),
    fecha: str = Form(..., pattern=r"^(0[1-9]|1[0-2])/(0[1-9]|[12][0-9]|3[01])/[0-9]{4}$"),  # Pydantic v2 -> pattern
    municipio: str = Form(...),
    files: Optional[List[UploadFile]] = File(default=None),
    user: Any = Depends(get_current_user),
):
    """
    Crea un evento exitoso con 0..N fotos.
    - Requiere usuario autenticado.
    - descripcion no puede estar vacía.
    - fecha en formato mm/dd/yyyy (se guarda como string).
    """
    if not descripcion or not descripcion.strip():
        raise HTTPException(status_code=422, detail="La descripción no puede estar vacía.")

    try:
        usuario_email = getattr(user, "email", None) or (user.get("email") if isinstance(user, dict) else None)
        if not usuario_email:
            raise HTTPException(status_code=401, detail="Usuario inválido.")

        fotos_urls: List[str] = []
        if files:
            for f in files:
                try:
                    url = _store_file(usuario_email, f)
                except HTTPException:
                    raise
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Error subiendo archivo {f.filename}: {e}")
                else:
                    fotos_urls.append(url)

        row = {
            "titulo": titulo,
            "descripcion": descripcion,
            "fecha": fecha,
            "municipio": municipio,
            "fotos": fotos_urls,
            "usuario_email": usuario_email,
            "created_at": datetime.utcnow().isoformat(),
        }

        res = supabase.table("eventos_exitosos").insert(row).execute()
        data = res.data or []
        if not data:
            raise HTTPException(status_code=400, detail="No se pudo crear el evento exitoso.")
        return data[0]

    except HTTPException:
        raise
    except Exception as e:
    
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import FastAPI, HTTPException, Body
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import datetime
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

# Rutas
from fitlink_backend.routers import events
from fitlink_backend.routers import stats

# Modelos
from fitlink_backend.models.UserSignUp import UserSignUp
from fitlink_backend.models.UserResponse import UserResponse
from fitlink_backend.models.UserLogin import UserLogin

load_dotenv()

app = FastAPI(title="FitLink Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(stats.router)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SERVICE_ROLE = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SERVICE_ROLE:
    raise RuntimeError("Faltan variables de entorno de Supabase")
supabase: Client = create_client(SUPABASE_URL, SERVICE_ROLE)

if not SUPABASE_URL or not SERVICE_ROLE:
    raise RuntimeError("Faltan variables SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en el .env")

supabase: Client = create_client(SUPABASE_URL, SERVICE_ROLE)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/stats")
def stats():
    # KPIs rápidos (usa head+count para eficiencia)
    users = supabase.table("usuarios").select("id", count="exact", head=True).execute()
    cats  = supabase.table("categoria").select("id", count="exact", head=True).execute()
    evts  = supabase.table("eventos") \
        .select("id", count=None) \
        .neq("estado","cancelado").gte("inicio", __import__("datetime").datetime.utcnow().isoformat()) \
        .execute()
    return {
        "usuarios": users.count or 0,
        "categorias": cats.count or 0,
        "eventosProximos": len(evts.data or []),
    }

@app.get("/events/upcoming")
def events_upcoming(limit: int = 20):
    import datetime
    try:
        # ⚠️ Usamos select("*") para evitar fallos por nombres (Municipio vs municipio, nombre_evento, etc.)
        res = (
            supabase.table("eventos")
            .select("*")
            .neq("estado", "cancelado")
            .gte("inicio", datetime.datetime.utcnow().isoformat())
            .order("inicio", desc=False)
            .limit(limit)
            .execute()
        )
        # SDK v2: res no tiene .error; si hay error lanza APIError antes.
        return res.data or []
    except Exception as e:
        # Devuelve detalle del error para depurar rápido
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users")
def list_users():
    res = supabase.table("usuarios").select(
        "id,nombre,biografia,fecha_nacimiento,municipio,foto_url"
    ).order("nombre").execute()
    if getattr(res, "error", None):
        raise HTTPException(status_code=500, detail=str(res.error))
    return res.data or []


@app.put("/users/{user_id}")
def update_user(user_id: int, payload: dict = Body(...)):
    # payload: {nombre, biografia, fecha_nacimiento, municipio, foto_url}
    res = supabase.table("usuarios").update(payload).eq("id", user_id).execute()
    if res.error:
        raise HTTPException(status_code=500, detail=res.error.message)
    return {"ok": True}


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    res = supabase.table("usuarios").delete().eq("id", user_id).execute()
    if res.error:
        raise HTTPException(status_code=500, detail=res.error.message)
    return {"ok": True}

@app.post("/auth/register", status_code=201, response_model=None)
def register_user(user_data: UserSignUp):
    """
    Registra un usuario en Supabase Auth y crea su perfil en la tabla 'usuarios'.
    Maneja errores con un try/except genérico.
    """
    new_user = None
    try:
        # 1. Crear el usuario en Supabase Auth.
        auth_response = supabase.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password,
        })
        new_user = auth_response.user

        # 2. Crear el perfil en la tabla 'usuarios'.
        profile_data = {
            "id": new_user.id,
            "carnet": user_data.carnet,
            "email": user_data.email,
            "nombre": user_data.nombre,
            "biografia": user_data.biografia,
            "fecha_nacimiento": user_data.fechaNacimiento.isoformat(),
            "municipio": user_data.ciudad,
            "foto_url": user_data.foto
        }
        supabase.table("usuarios").insert(profile_data).execute()

        return {"message": "Usuario registrado. Revisa tu email para confirmar.", "user": new_user.model_dump()}

    except Exception as e:
        error_message = str(e)
        
        # --- ¡MANEJO DE ERRORES MEJORADO! ---
        
        # Primero, revisamos si el error es el que estás viendo.
        if "User already registered" in error_message:
            # Si el email ya existe, es un error de validación simple.
            # No se necesita rollback porque 'new_user' será None.
            raise HTTPException(status_code=400, detail="Este correo electrónico ya está en uso.")
        
        # Si el error es por el carnet duplicado (ejemplo)
        if "usuarios_carnet_key" in error_message:
            error_detail = "Este carnet ya está registrado."
        else:
            # Otro error (ej. RLS, etc.)
            error_detail = error_message

        # --- Lógica de Rollback ---
        # Si el usuario de auth se creó PERO el perfil falló por otra razón
        if new_user and new_user.id:
            try:
                supabase.auth.admin.delete_user(new_user.id)
            except Exception as delete_e:
                # Si el borrado también falla, informamos ambos errores
                raise HTTPException(status_code=500, detail=f"Falló la creación del perfil ({error_detail}) y también falló la limpieza del usuario de auth ({delete_e}).")
        
        # Devolver el error específico (ej. "Este carnet ya está registrado.")
        raise HTTPException(status_code=400, detail=error_detail)


@app.post("/auth/login", response_model=None)
async def login_user(user_data: UserLogin):
    """
    Inicia sesión de un usuario únicamente con su email y contraseña.
    """
    try:
        response = supabase.auth.sign_in_with_password({
            "email": str(user_data.email),
            "password": str(user_data.password),
        })

        return {
            "message": "Login exitoso",
            "session": response.session.model_dump(),
            "user": response.user.model_dump()
        }
    except Exception as e:
        print(f"Error inesperado en login: {e}")
        raise HTTPException(status_code=500, detail="Ocurrió un error inesperado en el servidor.")
    
@app.get("/auth/google", response_model=None)
async def login_with_google(redirect_to: Optional[str] = None):
    """
    Genera y devuelve la URL de Supabase para iniciar sesión con Google.
    """
    final_redirect_to = redirect_to if redirect_to else os.environ["VITE_API_URL"]
    
    supabase_google_oauth_url = (
        f"{os.environ['SUPABASE_URL']}/auth/v1/authorize?"
        f"provider=google&"
        f"redirect_to={final_redirect_to}"
    )
    
    return {"oauth_url": supabase_google_oauth_url}
from fastapi import FastAPI, HTTPException, Body, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Annotated, Any, Optional
from dotenv import load_dotenv
import os
import datetime

# Supabase client
from fitlink_backend.supabase_client import supabase

# Routers
from fitlink_backend.routers import events
from fitlink_backend.routers import stats
from fitlink_backend.routers import suggestions
from fitlink_backend.routers import users
from fitlink_backend.routers.chat import router as chat_router
from fitlink_backend.routes import notificaciones

# Modelos para auth
from fitlink_backend.models.UserSignUp import UserSignUp
from fitlink_backend.models.UserLogin import UserLogin

load_dotenv()

app = FastAPI(title="FitLink Backend")

# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------
origins = [
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Routers
# ---------------------------------------------------------
app.include_router(events.router)
app.include_router(stats.router)
app.include_router(suggestions.router)
app.include_router(users.router)
app.include_router(chat_router)
app.include_router(notificaciones.router)

# ---------------------------------------------------------
# Dependencias
# ---------------------------------------------------------
async def get_current_user(authorization: Annotated[str | None, Header()] = None) -> Any:
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


# ---------------------------------------------------------
# Health Check
# ---------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------
# Eventos públicos (se quedan aquí porque los usas desde el landing)
# ---------------------------------------------------------
@app.get("/events/upcoming")
def events_upcoming(limit: int = 20):
    try:
        res = (
            supabase.table("eventos")
            .select("*, categoria ( nombre, icono )")
            .neq("estado", "cancelado")
            .gte("inicio", datetime.datetime.utcnow().isoformat())
            .order("inicio", desc=False)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------
# CRUD simple de usuarios (manteniendo tus endpoints legacy)
# ---------------------------------------------------------
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


# ---------------------------------------------------------
# Auth: Registro
# ---------------------------------------------------------
@app.post("/auth/register", status_code=201)
def register_user(user_data: UserSignUp):
    try:
        auth_response = supabase.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password,
        })

        if auth_response.user is None:
            error_message = getattr(auth_response.error, 'message', "No se pudo registrar al usuario.")
            raise HTTPException(status_code=400, detail=error_message)

        new_user = auth_response.user

        profile_data = {
            "id": new_user.id,
            "carnet": user_data.carnet,
            "email": new_user.email,
            "nombre": user_data.nombre,
            "biografia": user_data.biografia,
            "fecha_nacimiento": user_data.fechaNacimiento.isoformat(),
            "municipio": user_data.ciudad,
            "foto_url": user_data.foto
        }

        profile_res = supabase.table("usuarios").insert(profile_data).execute()

        if profile_res.error:
            raise HTTPException(
                status_code=500,
                detail=f"Usuario de Auth creado, pero falló la creación del perfil: {profile_res.error.message}"
            )

        return {
            "message": "Usuario registrado. Revisa tu email.",
            "user": new_user.model_dump()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------
# Auth: Login
# ---------------------------------------------------------
@app.post("/auth/login")
async def login_user(user_data: UserLogin):
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
        error_message = str(e).lower()

        if "invalid login credentials" in error_message:
            raise HTTPException(401, "Credenciales inválidas")
        if "email not confirmed" in error_message:
            raise HTTPException(401, "Email no confirmado")
        if "user not found" in error_message:
            raise HTTPException(401, "Usuario no encontrado")
        if "invalid password" in error_message:
            raise HTTPException(401, "Contraseña incorrecta")
        if "too many requests" in error_message:
            raise HTTPException(429, "Demasiados intentos, espera unos minutos")

        raise HTTPException(500, "Error inesperado")


# ---------------------------------------------------------
# Auth: Login con Google
# ---------------------------------------------------------
@app.get("/auth/google")
async def login_with_google(redirect_to: Optional[str] = None):
    final_redirect_to = redirect_to or os.environ["VITE_API_URL"]

    supabase_google_oauth_url = (
        f"{os.environ['SUPABASE_URL']}/auth/v1/authorize?"
        f"provider=google&redirect_to={final_redirect_to}"
    )

    return {"oauth_url": supabase_google_oauth_url}

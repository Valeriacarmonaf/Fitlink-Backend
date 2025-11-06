# src/fitlink_backend/main.py
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from typing import Optional

import os
from dotenv import load_dotenv
from supabase import create_client, Client
import datetime
from fastapi import Depends, Header
from typing import Annotated
from typing import Optional, Any

# Routers
from fitlink_backend.routers import chat as chat_router
from fitlink_backend.routers import events, stats, suggestions, users

# Modelos y cliente (sólo para los endpoints de auth que permanecen aquí)
from fitlink_backend.models.UserSignUp import UserSignUp
from fitlink_backend.models.UserResponse import UserResponse
from fitlink_backend.models.UserLogin import UserLogin
from fitlink_backend.supabase_client import supabase
from fitlink_backend.routers import success_events

load_dotenv()

app = FastAPI(title="FitLink Backend")

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,  # si usas cookies/sesion, y para enviar Authorization con credenciales
    allow_methods=["*"],     # o ["GET","POST","PUT","PATCH","DELETE","OPTIONS"]
    allow_headers=["*", "Authorization", "Content-Type"],
    expose_headers=["*"],    # opcional (si el frontend necesita leer headers)
)

# --- Routers (cada uno ya trae su prefix, no dupliques aquí) ---
app.include_router(chat_router.router)      # /api/chats
app.include_router(events.router)           # /api/events
app.include_router(stats.router)            # /api/stats
app.include_router(suggestions.router)      # /api/events/suggestions (o el que definas)
app.include_router(users.router)            # /api/users
app.include_router(success_events.router)
# Alias útil si alguien llama /stats directo
@app.get("/stats")
async def stats_alias():
    return RedirectResponse(url="/api/stats", status_code=307)

@app.get("/health")
def health():
    return {"ok": True}

# =========================
#  AUTH (se quedan aquí)
# =========================

@app.post("/auth/register", status_code=201)
def register_user(user_data: UserSignUp):
    """
    Registra un usuario en Supabase Auth y crea su perfil en 'usuarios'.
    """
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
        if getattr(profile_res, "error", None):
            raise HTTPException(
                status_code=500,
                detail=f"Usuario de Auth creado, pero falló la creación del perfil: {profile_res.error.message}"
            )

        return {"message": "Usuario registrado. Revisa tu email para confirmar la cuenta.", "user": new_user.model_dump()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/login")
def login_user(user_data: UserLogin):
    """
    Inicia sesión de un usuario con email y contraseña.
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


@app.get("/auth/google")
def login_with_google(redirect_to: Optional[str] = None):
    """
    Devuelve la URL de Supabase para iniciar sesión con Google.
    """
    final_redirect_to = redirect_to if redirect_to else os.environ["VITE_API_URL"]
    supabase_google_oauth_url = (
        f"{os.environ['SUPABASE_URL']}/auth/v1/authorize?"
        f"provider=google&"
        f"redirect_to={final_redirect_to}"
    )
    return {"oauth_url": supabase_google_oauth_url}

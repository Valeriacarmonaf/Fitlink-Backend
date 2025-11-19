# src/fitlink_backend/main.py
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.exception_handlers import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
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
from fitlink_backend.supabase_client import supabase, get_admin_client
from fitlink_backend.routers import success_events
from fitlink_backend.routers import events, chat_match


load_dotenv()

app = FastAPI(title="FitLink Backend")

# Manejador global para mostrar errores de validación detallados
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("\n[VALIDATION ERROR]", exc.errors())
    return JSONResponse(
        status_code=400,
        content={"detail": exc.errors(), "body": exc.body},
    )

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
app.include_router(events.router)
app.include_router(chat_match.router)
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
    print('\n[DEBUG] user_data recibido:', user_data)
    """
    Registra un usuario en Supabase Auth y crea su perfil en 'usuarios'.
    """
    try:
        try:
            #Intentamos enviar user_metadata para que cualquier trigger que cree
            #el perfil en la tabla `usuarios` tenga los datos necesarios.
            # Normalizar tipos para que coincidan con el esquema de la tabla `usuarios`
            carnet_val = None
            try:
                if user_data.carnet is not None and str(user_data.carnet).strip() != "":
                    # intentar convertir a entero para la columna bigint
                    carnet_val = int(str(user_data.carnet).strip())
            except Exception:
                carnet_val = None

            user_metadata = {
                    "carnet": carnet_val,
                    "nombre": user_data.nombre,
                    "biografia": user_data.biografia,
                    "fecha_nacimiento": user_data.fechaNacimiento.isoformat(),
                    "municipio": user_data.ciudad,
                    "foto_url": user_data.foto,
                }
            # La API Python de supabase acepta un único payload como dict.
            signup_payload = {
                "email": user_data.email,
                "password": user_data.password,
                "data": user_metadata,
            }
            auth_response = supabase.auth.sign_up(signup_payload)
            print('\n[DEBUG] auth_response:', auth_response)
            if hasattr(auth_response, 'error') and auth_response.error:
                print('\n[DEBUG] auth_response.error:', getattr(auth_response.error, 'message', str(auth_response.error)))
        except Exception as inner_exc:
            print('\n[DEBUG] EXCEPTION en supabase.auth.sign_up:', inner_exc)
            raise HTTPException(status_code=500, detail=f"Error al llamar a Supabase Auth: {str(inner_exc)}")

        if auth_response.user is None:
            error_message = getattr(auth_response.error, 'message', "No se pudo registrar al usuario.")
            raise HTTPException(status_code=400, detail=error_message)

        new_user = auth_response.user

        profile_data = {
            "id": new_user.id,
            "carnet": carnet_val,
            "email": new_user.email,
            "nombre": user_data.nombre,
            "biografia": user_data.biografia,
            "fecha_nacimiento": user_data.fechaNacimiento.isoformat(),
            "municipio": user_data.ciudad,
            "foto_url": user_data.foto
        }

        # Antes de insertar, comprobamos si ya existe por id o email
        try:
            exists_by_id = supabase.table("usuarios").select("id").eq("id", new_user.id).single().execute()
        except Exception:
            exists_by_id = None

        try:
            exists_by_email = supabase.table("usuarios").select("email").eq("email", new_user.email).single().execute()
        except Exception:
            exists_by_email = None

        # Si el perfil ya existe (por ejemplo, creado automáticamente por un trigger
        # en auth.users), NO devolveremos 409: consideramos el registro de Auth
        # como correcto y seguimos. Esto evita fallos cuando la BD ya creó el perfil.
        profile_exists = bool(getattr(exists_by_id, "data", None) or getattr(exists_by_email, "data", None))
        if profile_exists:
            print('\n[DEBUG] Perfil ya existe en la BD (posible trigger). Omitiendo creación y devolviendo éxito.')
            return {"message": "Usuario registrado. Revisa tu email para confirmar la cuenta.", "user": new_user.model_dump()}

        try:
            # Intentamos usar una función SQL segura en la BD que inserte solo si no existe.
            # Esta función debe existir en la BD: insert_usuario_if_not_exists(p_id uuid, p_email text, p_nombre text, p_carnet bigint, p_biografia text, p_fecha_nacimiento date, p_municipio text, p_foto_url text)
            try:
                admin = get_admin_client()
                rpc_resp = admin.rpc(
                    "insert_usuario_if_not_exists",
                    {
                        "p_id": str(new_user.id),
                        "p_email": new_user.email,
                        "p_nombre": profile_data["nombre"],
                        "p_carnet": profile_data["carnet"],
                        "p_biografia": profile_data["biografia"],
                        "p_fecha_nacimiento": profile_data["fecha_nacimiento"],
                        "p_municipio": profile_data["municipio"],
                        "p_foto_url": profile_data["foto_url"],
                    },
                ).execute()
                print('\n[DEBUG] rpc_resp:', rpc_resp)
                # Si RPC funcionó, asumimos que el perfil fue creado o ya existía.
            except Exception as rpc_exc:
                # Si no existe la función o falla la RPC, hacemos fallback a upsert (más portable)
                print('\n[DEBUG] RPC insert_usuario_if_not_exists falló, haciendo fallback a upsert. Error:', rpc_exc)
                profile_res = get_admin_client().table("usuarios").upsert(profile_data, on_conflict="id").execute()
                print('\n[DEBUG] profile_res (fallback upsert):', profile_res)
                if hasattr(profile_res, 'error') and profile_res.error:
                    print('\n[DEBUG] profile_res.error:', getattr(profile_res.error, 'message', str(profile_res.error)))
                    raise HTTPException(status_code=500, detail=f"Usuario de Auth creado, pero falló la creación del perfil: {getattr(profile_res.error, 'message', str(profile_res.error))}")

        except HTTPException:
            raise
        except Exception as e:
            print('\n[DEBUG] EXCEPTION al insertar perfil:', e)
            raise HTTPException(status_code=500, detail=f"Excepción inesperada al crear perfil: {str(e)}")

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
        # Intentar iniciar sesión; la librería de Supabase puede lanzar excepciones
        # o retornar un objeto con .error. Normalizamos ambos casos.
        try:
            response = supabase.auth.sign_in_with_password({
                "email": str(user_data.email),
                "password": str(user_data.password),
            })
            print("[DEBUG] supabase.auth.sign_in_with_password response:", response)
        except Exception as auth_exc:
            # Mensajes conocidos de la librería
            msg = str(auth_exc)
            print("[DEBUG] supabase.auth.sign_in_with_password raised:", msg)
            if "Invalid login credentials" in msg or "Invalid credentials" in msg or "invalid login" in msg.lower():
                raise HTTPException(status_code=401, detail="Credenciales inválidas")
            # Si no es un error de credenciales, propagar como 500
            raise HTTPException(status_code=500, detail=f"Error en Auth: {msg}")

        user_obj = getattr(response, 'user', None) or None
        # También verificar si la respuesta incluye un error
        resp_err = getattr(response, 'error', None)
        if not user_obj:
            err_msg = None
            if resp_err:
                err_msg = getattr(resp_err, 'message', str(resp_err))
            raise HTTPException(status_code=401, detail=err_msg or "Credenciales inválidas")

        # Verificar bloqueo por reportes en la tabla `usuarios`
        try:
            admin = get_admin_client()
            check = admin.table("usuarios").select("is_blocked").eq("id", user_obj.id).limit(1).execute()
            if check.data and len(check.data) > 0:
                is_blocked = check.data[0].get("is_blocked")
                if is_blocked:
                    # Usuario bloqueado: devolver 403 con mensaje inmutable para frontend
                    raise HTTPException(status_code=403, detail="Cuenta deshabilitada por exceder el límite de reportes. Contacta soporte.")
        except HTTPException:
            raise
        except Exception as e:
            print("Advertencia: no se pudo comprobar bloqueo de usuario:", e)

        return {
            "message": "Login exitoso",
            "session": response.session.model_dump(),
            "user": user_obj.model_dump()
        }
    except HTTPException:
        # Re-lanzar errores HTTP (401,403,...) tal cual para que FastAPI los maneje
        raise
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

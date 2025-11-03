from fastapi import FastAPI, HTTPException, Body
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import datetime
from fastapi.middleware.cors import CORSMiddleware
from fitlink_backend.routers.chat import router as chat_router
from fastapi import Depends, Header
from typing import Annotated
from typing import Optional, Any

# Rutas
from fitlink_backend.routers import events
from fitlink_backend.routers import stats
from fitlink_backend.routers import suggestions

# Modelos
from fitlink_backend.models.UserSignUp import UserSignUp
from fitlink_backend.models.UserResponse import UserResponse
from fitlink_backend.models.UserLogin import UserLogin

from fitlink_backend.supabase_client import supabase

load_dotenv()

app = FastAPI(title="FitLink Backend")

origins = [
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # <-- Usa la lista de orígenes
    allow_credentials=True,
    allow_methods=["*"],      # Permite todos los métodos (GET, POST, etc.)
    allow_headers=["*"],      # Permite todas las cabeceras
)

app.include_router(events.router)
app.include_router(stats.router)
app.include_router(chat_router)
app.include_router(suggestions.router)

async def get_current_user(authorization: Annotated[str | None, Header()] = None) -> Any:
    """
    Dependencia de FastAPI para obtener el usuario autenticado...
    """
    # El resto de la función no cambia
    if not authorization:
        raise HTTPException(status_code=401, detail="Falta el encabezado de autorización")
    
    token = authorization.replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Token malformado")

    try:
        user_response = supabase.auth.get_user(token)
        
        if user_response.user is None:
            raise HTTPException(status_code=401, detail="Token inválido o sesión expirada")
        
        # Sigue devolviendo el objeto 'user' completo
        return user_response.user 
    
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Error de autenticación: {str(e)}")

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

@app.get("/events/suggestions")
async def get_event_suggestions(
    current_user: Annotated[Any, Depends(get_current_user)]
):
    """
    Obtiene sugerencias de eventos para el usuario autenticado.
    LÓGICA ACTUALIZADA:
    1. Buscar eventos en el MISMO MUNICIPIO del usuario.
    2. Buscar eventos cuyo CATEGORIA_ID coincida con las IDs
       de las categorías guardadas por el usuario.
    3. Solo mostrar eventos futuros y no cancelados.
    """
    try:
        user_id = current_user.id
        user_email = current_user.email

        # 1. Obtener el municipio del perfil del usuario
        profile_res = supabase.table("usuarios") \
            .select("municipio") \
            .eq("id", user_id) \
            .single() \
            .execute()

        if not profile_res.data:
            raise HTTPException(status_code=404, detail="Perfil de usuario no encontrado.")

        user_municipio = profile_res.data.get('municipio')
        if not user_municipio:
            raise HTTPException(status_code=400, detail="Tu perfil no tiene un municipio configurado.")

        # 2. Obtener las IDs de las categorías (intereses) del usuario
        my_skills_res = supabase.table("usuario_categoria") \
            .select("categoria_id") \
            .eq("usuario_email", user_email) \
            .execute()

        if not my_skills_res.data:
            return [] # Si no tiene intereses (categorías), no podemos sugerir

        my_category_ids = [skill['categoria_id'] for skill in my_skills_res.data]
        
        # 3. YA NO NECESITAMOS BUSCAR LOS NOMBRES DE LAS CATEGORÍAS.
        #    Podemos filtrar directamente por las IDs (my_category_ids).
        
        # 4. Buscar eventos que coincidan
        now = datetime.datetime.utcnow().isoformat()
        
        events_res = supabase.table("eventos") \
            .select(
                """
                *,
                categoria ( nombre, icono )
                """
            ) \
            .eq("municipio", user_municipio) \
            .in_("categoria_id", my_category_ids) \
            .gte("inicio", now) \
            .neq("estado", "cancelado") \
            .order("inicio", desc=False) \
            .limit(20) \
            .execute()

        # Devuelve los datos o un array vacío (corrigiendo el error 'null')
        return events_res.data or []

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error inesperado en /events/suggestions: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@app.post("/auth/register", status_code=201, response_model=None)
def register_user(user_data: UserSignUp):
    """
    Registra un usuario en Supabase Auth (de forma segura con email/pass)
    y luego crea su perfil público en la tabla 'usuarios' con el carnet.
    """
    try:
        # 1. Crear el usuario en Supabase Auth. La contraseña se hashea aquí.
        auth_response = supabase.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password,
        })

        if auth_response.user is None:
            error_message = getattr(auth_response.error, 'message', "No se pudo registrar al usuario.")
            raise HTTPException(status_code=400, detail=error_message)

        new_user = auth_response.user

        # 2. Si Auth fue exitoso, crea el perfil en tu tabla 'usuarios'.
        #    El 'id' del perfil DEBE ser el mismo que el 'id' de auth.users.
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
            # En un caso real, deberías borrar el usuario de auth si el perfil falla (rollback).
            # Por ahora, solo lanzamos el error.
            raise HTTPException(status_code=500, detail=f"Usuario de Auth creado, pero falló la creación del perfil: {profile_res.error.message}")

        return {"message": "Usuario registrado. Revisa tu email para confirmar la cuenta.", "user": new_user.model_dump()}

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
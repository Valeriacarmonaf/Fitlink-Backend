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
from fitlink_backend.models.UserCreate import UserCreate
from fitlink_backend.models.UserResponse import UserResponse
from fitlink_backend.models.UserLogin import UserLogin

load_dotenv()

app = FastAPI(title="FitLink Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],  # tu frontend local
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router)
app.include_router(stats.router)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SERVICE_ROLE = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

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

@app.post("/users", status_code=201, response_model=None)
def create_user(user_data: UserCreate):
    """
    Crea un nuevo usuario en la base de datos (tabla 'usuarios').
    """
    try:
        # 1. Comprobar si el ID (o email, si cambias el campo) ya existe
        existing = supabase.table("usuarios").select("id").eq("id", user_data.id).execute()

        if existing.data:
            # 409 Conflict: El recurso ya existe.
            # Esto es lo que React recibirá si el ID está duplicado.
            raise HTTPException(
                status_code=409, 
                detail="Este ID ya está en uso. Por favor, intente con otro."
            )

        # 2. Mapear los nombres de React (camelCase) a los nombres de tu DB (snake_case)
        user_to_insert = {
            "id": user_data.id,
            "nombre": user_data.nombre,
            "biografia": user_data.biografia,
            "fecha_nacimiento": user_data.fechaNacimiento,
            "municipio": user_data.ciudad,
            "foto_url": user_data.foto
        }
        
        # 3. Insertar el nuevo usuario en Supabase
        res = supabase.table("usuarios").insert(user_to_insert).execute()

        if res.error:
            raise HTTPException(status_code=500, detail=str(res.error.message))

        # 4. Éxito: Devolver los datos del usuario creado
        return res.data[0]

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error inesperado del servidor: {str(e)}")

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

@app.post("/auth/login")
async def login_user(user_data: UserLogin):
    """
    Inicia sesión de un usuario con email y contraseña.
    """
    try:
        # Aquí usaremos el método 'sign_in_with_password' de Supabase
        # IMPORTANTE: Los datos de usuario se gestionan en la tabla 'auth.users' de Supabase,
        # no en tu tabla 'usuarios'. Tu tabla 'usuarios' es para perfil extendido.
        response = supabase.auth.sign_in_with_password({
            "email": user_data.email,
            "password": user_data.password,
        })

        # Si hay un error de autenticación (ej. credenciales inválidas)
        if response.user is None:
            # Supabase auth devuelve un objeto con user=None y error si falla.
            # El error es un diccionario, así que lo convertimos a string.
            error_message = response.error.message if response.error else "Credenciales inválidas"
            raise HTTPException(status_code=401, detail=error_message)
        
        # Si la autenticación es exitosa, response.session y response.user contendrán los datos
        return {
            "message": "Login exitoso",
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "user": response.user.model_dump() # .model_dump() para Pydantic v2
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@app.get("/auth/google")
async def login_with_google(redirect_to: Optional[str] = None):
    """
    Redirige al cliente a la URL de inicio de sesión de Google a través de Supabase.
    `redirect_to` es la URL en tu frontend a la que Supabase debería redirigir después del login.
    """
    # La URL a la que Supabase redirigirá después de la autenticación.
    # Necesitas que esta URL esté en la lista de URLs de redirección de tu proyecto Supabase.
    # Por ejemplo, "http://localhost:5173/dashboard" o "http://localhost:5173/callback"
    
    # Si no se especifica, usa la URL base de tu frontend.
    # Es crucial que esta URL esté registrada en tus "Redirect URLs" en Supabase Auth Settings.
    final_redirect_to = redirect_to if redirect_to else "http://localhost:5173/"

    # Genera la URL de OAuth de Supabase para Google
    # El método 'get_authorize_url' es más seguro que construirla manualmente.
    # Necesitarás 'gotrue-py' para esto, pero dado que usas el cliente Supabase,
    # ya deberías tener acceso al cliente auth.
    
    # El cliente de Supabase tiene un atributo 'auth' que puede generar estas URLs
    # Usaremos un método que construya la URL de autenticación
    
    # NOTA: Supabase SDK V2 ha cambiado la forma de manejar esto.
    # Ya no hay un 'get_authorize_url' directo para proveedores.
    # En su lugar, el frontend suele redirigir directamente a la URL de Supabase para el proveedor.
    # O, si quieres pasar por FastAPI, tendrías que simular la redirección.
    
    # La forma más directa es que el frontend genere la URL de redirección:
    # `https://{YOUR_PROJECT_REF}.supabase.co/auth/v1/authorize?provider=google&redirect_to=${frontend_url}`
    # Sin embargo, si quieres que FastAPI haga la redirección:

    try:
        # La forma más estándar de hacer esto es que el cliente reciba la URL de Supabase
        # y luego el cliente redirija directamente a esa URL.
        # FastAPI, en este caso, solo serviría para *generar* la URL y devolverla.
        
        # Construye la URL de redirección de Supabase para Google
        # Asegúrate de que '{project_ref}' sea tu ID de proyecto de Supabase
        # y que el 'redirect_to' sea una URL permitida en Supabase Auth -> URL Configuration
        supabase_google_oauth_url = (
            f"{os.environ['SUPABASE_URL']}/auth/v1/authorize?"
            f"provider=google&"
            f"redirect_to={final_redirect_to}"
        )
        
        # Puedes simplemente devolver esta URL al frontend
        return {"oauth_url": supabase_google_oauth_url}
        
        # O, si quieres que FastAPI haga la redirección DIRECTA (menos común para OAuth)
        # from fastapi.responses import RedirectResponse
        # return RedirectResponse(url=supabase_google_oauth_url, status_code=302)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar URL de Google OAuth: {str(e)}")

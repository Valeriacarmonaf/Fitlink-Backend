# src/fitlink_backend/supabase_client.py
import os
from typing import Optional
from dotenv import load_dotenv, find_dotenv
from supabase import create_client, Client

# Carga el .env EN ESTE MÓDULO, antes de leer variables
load_dotenv(find_dotenv(), override=False)

def _getenv(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(
            f"Falta la variable de entorno {name}. "
            f"Define {name} en tu .env o exporta la variable antes de ejecutar el servidor."
        )
    return v

SUPABASE_URL = _getenv("SUPABASE_URL")
# Clave pública para firmar requests "normales" del usuario
SUPABASE_ANON_KEY = _getenv("SUPABASE_ANON_KEY")
# Clave de servicio (opcional). ÚSALA SOLO si necesitas bypass de RLS en tareas admin.
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

def get_admin_client() -> Client:
    """
    Cliente con privilegios altos (bypass RLS) si existe SERVICE_ROLE,
    si no, cae a ANON. Úsalo con MUCHO cuidado.
    """
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    return create_client(SUPABASE_URL, key)

# Cliente global "admin/anon" para endpoints públicos/simples.
supabase: Client = get_admin_client()

def supabase_for_token(jwt_token: str) -> Client:
    """
    Crea un cliente autenticado con el JWT del usuario para que PostgREST
    ejecute las políticas RLS con auth.uid() correctamente.
    """
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.postgrest.auth(jwt_token)
    return client

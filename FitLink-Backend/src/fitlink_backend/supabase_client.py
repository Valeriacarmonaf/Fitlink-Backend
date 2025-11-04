from supabase import create_client, Client # Añadí 'Client' para type hinting
from dotenv import load_dotenv
import os

load_dotenv()
url = os.getenv("SUPABASE_URL")
service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not url or not service_key:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")

# Exportamos el cliente con el type hint
supabase: Client = create_client(url, service_key)
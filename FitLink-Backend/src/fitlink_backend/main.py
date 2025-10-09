from fastapi import FastAPI, HTTPException
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import datetime

load_dotenv()

app = FastAPI(title="FitLink Backend")

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
    res = supabase.table("eventos").select(
        "id,categoria,nombre_event,descripcion,inicio,fin,municipio,precio,estado"
    ).neq("estado","cancelado").gte("inicio", __import__("datetime").datetime.utcnow().isoformat()) \
     .order("inicio", desc=False).limit(limit).execute()
    if res.error:
        raise HTTPException(status_code=500, detail=res.error.message)
    return res.data

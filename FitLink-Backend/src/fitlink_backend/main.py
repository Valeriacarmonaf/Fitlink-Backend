from fastapi import FastAPI, HTTPException
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import datetime
from fastapi.middleware.cors import CORSMiddleware

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

from fastapi import Body

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

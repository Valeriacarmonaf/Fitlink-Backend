# src/fitlink_backend/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta, timezone
from fitlink_backend.supabase_client import supabase
from fitlink_backend.routers.notificaciones import enviar_notificacion
import threading
import time

# Config: minutos antes del inicio en los que avisamos
REMINDERS_MINUTES = [60, 15]  # puedes ajustar (ej. 1440 -> 24h)

# intervalo de chequeo del scheduler (en segundos)
SCHEDULER_INTERVAL_SECONDS = 60

def _now_utc():
    return datetime.now(timezone.utc)

def _to_iso(dt: datetime):
    # supabase stores timestamps without tz in your table but we will work with ISO strings in UTC
    return dt.replace(tzinfo=timezone.utc).isoformat()

def check_and_send_reminders():
    """
    Job que se ejecuta periódicamente y manda recordatorios para eventos próximos.
    Evita duplicados buscando en la tabla 'notificaciones' mensajes creados previamente
    que incluyan la marca 'evento_id:{id}|reminder:{minutes}'.
    """
    try:
        now = _now_utc()

        for minutes in REMINDERS_MINUTES:
            start = now + timedelta(minutes=minutes)
            end = start + timedelta(minutes=1)  # rango de 1 minuto

            # Convertir a string ISO compatibles con tus queries
            start_iso = _to_iso(start)
            end_iso = _to_iso(end)

            # Buscar eventos que empiezan entre start y end y que no estén cancelados
            res = supabase.table("eventos") \
                .select("*") \
                .gte("inicio", start_iso) \
                .lt("inicio", end_iso) \
                .neq("estado", "cancelado") \
                .execute()

            events = res.data or []

            for ev in events:
                event_id = ev.get("id")
                creador_email = ev.get("creador_email")
                nombre_evento = ev.get("nombre_evento") or ev.get("descripcion") or "Entrenamiento"

                if not creador_email or not event_id:
                    continue  # falta información mínima

                # 1) obtener usuario.id por email (tabla usuarios)
                ures = supabase.table("usuarios").select("id").eq("email", creador_email).maybe_single().execute()
                usuario_row = ures.data
                if not usuario_row:
                    # no podemos notificar si no hay usuario asociado
                    continue
                usuario_id = usuario_row.get("id")

                # 2) leer preferencias
                prefs_res = supabase.table("preferencias_notificaciones") \
                    .select("*") \
                    .eq("usuario_id", usuario_id) \
                    .maybe_single() \
                    .execute()
                prefs = prefs_res.data or {}
                # si no hay preferencias -> asumimos true
                if not prefs:
                    notificar_entrenos = True
                else:
                    notificar_entrenos = prefs.get("notificar_entrenos", True)

                if not notificar_entrenos:
                    continue

                # 3) evitar duplicados: buscamos si ya existe notificación para este evento+reminder
                marker = f"evento_id:{event_id}|reminder:{minutes}"
                # obtenemos notificaciones previas del usuario y buscamos marker en el mensaje
                notif_res = supabase.table("notificaciones") \
                    .select("id, mensaje") \
                    .eq("usuario_id", usuario_id) \
                    .execute()
                already = False
                for n in (notif_res.data or []):
                    msg = n.get("mensaje") or ""
                    if marker in msg:
                        already = True
                        break

                if already:
                    continue

                # 4) crear notificación con MARKER dentro del mensaje para poder detectarla luego
                friendly_msg = f"{marker}|Tu entrenamiento '{nombre_evento}' comienza en {minutes} minutos."
                titulo = f"Recordatorio: entrenamiento en {minutes} min"

                enviar_notificacion(usuario_id=usuario_id, titulo=titulo, mensaje=friendly_msg, tipo="recordatorio")

    except Exception as e:
        # Loguear error (no detiene scheduler)
        print("Error en job check_and_send_reminders:", e)

_scheduler = None

def start_scheduler():
    global _scheduler
    if _scheduler:
        return

    _scheduler = BackgroundScheduler()
    # Lanzamos check_and_send_reminders cada SCHEDULER_INTERVAL_SECONDS
    _scheduler.add_job(check_and_send_reminders, 'interval', seconds=SCHEDULER_INTERVAL_SECONDS, id="reminder_job", replace_existing=True)
    _scheduler.start()
    print("Scheduler started with interval", SCHEDULER_INTERVAL_SECONDS, "seconds and reminders", REMINDERS_MINUTES)

def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        print("Scheduler stopped")

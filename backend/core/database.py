"""
core/database.py
Cliente de Supabase. Se instancia una vez (singleton) y se reutiliza.
Usa la SERVICE KEY para operaciones del servidor (insertar métricas, etc.)
"""
from supabase import create_client, Client
from core.config import get_settings

_supabase_client: Client | None = None


def get_supabase() -> Client:
    """
    Retorna el cliente Supabase con service_role key.
    Úsalo SOLO en el backend — nunca expongas esta key al frontend.
    """
    global _supabase_client
    if _supabase_client is None:
        cfg = get_settings()
        _supabase_client = create_client(cfg.supabase_url, cfg.supabase_service_key)
    return _supabase_client


def get_supabase_anon() -> Client:
    """
    Cliente con anon key — para validar JWTs de usuarios autenticados.
    """
    cfg = get_settings()
    return create_client(cfg.supabase_url, cfg.supabase_anon_key)

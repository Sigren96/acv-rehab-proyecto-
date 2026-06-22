"""
core/config.py
Configuración central del backend. Lee variables de entorno desde .env
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str
    supabase_jwt_secret: str

    # Servidor
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_url: str = "http://localhost:3000"

    # Umbrales de fuerza G por nivel de movilidad
    umbral_g_critico:     float = 0.30
    umbral_g_intermedio:  float = 0.55
    umbral_g_recuperado:  float = 0.73

    # Timeout (tmax) por nivel de dificultad en segundos
    tmax_facil:   float = 3.50
    tmax_medio:   float = 1.80
    tmax_dificil: float = 0.80

    # Umbral de velocidad angular sostenida para "Círculos" (grados/segundo)
    umbral_giro_z: float = 30.0

    # Ventana de muestras para detección de giro sostenido (# paquetes consecutivos)
    ventana_giro_paquetes: int = 3

    # Intervalo de muestreo de la Pico en segundos (dt = 50ms)
    dt_muestreo: float = 0.05

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

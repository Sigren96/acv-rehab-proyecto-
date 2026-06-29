"""
main.py
Punto de entrada del servidor FastAPI.
Ejecutar con: uvicorn main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from core.config import get_settings
from routers.api import router

cfg = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Backend ACV-Rehab iniciado correctamente.")
    print(f"   Supabase URL: {cfg.supabase_url}")
    print(f"   Frontend permitido: {cfg.frontend_url}")
    yield
    print("🛑 Backend detenido.")


app = FastAPI(
    title="Sistema de Rehabilitación ACV — UNFV",
    description=(
        "Backend para el Sistema Embebido de Rehabilitación Cognitivo-Motora "
        "para Pacientes con Secuelas de ACV, basado en Estímulos Audiovisuales Discriminatorios."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# En producción cambia allow_origins al dominio exacto de Vercel.
# Incluye dominios de Railway para WebSocket upgrade requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        cfg.frontend_url,
        "https://acv-rehab-proyecto.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # Railway domains (wildcard patterns handled in WebSocket endpoints)
        "https://*.up.railway.app",
        "https://*.railway.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rutas ─────────────────────────────────────────────────────────────────────
app.include_router(router, prefix="/api/v1")


@app.get("/", tags=["Health"])
async def health():
    return {"status": "ok", "sistema": "ACV-Rehab Backend v1.0"}

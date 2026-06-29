"""
main.py
Punto de entrada del servidor FastAPI.
Ejecutar con: uvicorn main:app --reload
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
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

# ── Custom CORS Middleware for WebSocket ─────────────────────────────────────
# This middleware handles CORS for WebSocket upgrade requests which CORSMiddleware doesn't handle
@app.middleware("http")
async def websocket_cors_middleware(request: Request, call_next):
    # Handle preflight OPTIONS requests
    if request.method == "OPTIONS":
        response = Response()
    else:
        response = await call_next(request)
    
    # Get origin from request
    origin = request.headers.get("origin")
    
    # Define allowed origins (including Railway patterns)
    allowed_origins = [
        cfg.frontend_url,
        "https://acv-rehab-proyecto.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    
    # Check if origin matches allowed patterns (including Railway subdomains)
    def is_origin_allowed(origin: str) -> bool:
        if not origin:
            return False
        for allowed in allowed_origins:
            if origin == allowed:
                return True
        # Check Railway subdomains
        if origin.startswith("https://") and (origin.endswith(".up.railway.app") or origin.endswith(".railway.app")):
            return True
        return False
    
    if origin and is_origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Upgrade, Connection, Sec-WebSocket-Key, Sec-WebSocket-Version, Sec-WebSocket-Protocol"
    
    return response


# ── CORS ─────────────────────────────────────────────────────────────────────
# En producción cambia allow_origins al dominio exacto de Vercel.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        cfg.frontend_url,
        "https://acv-rehab-proyecto.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
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

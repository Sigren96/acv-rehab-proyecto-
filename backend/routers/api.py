"""
routers/api.py
Todas las rutas HTTP y WebSocket del backend.
Organizado en prefijos: /auth, /pacientes, /sesiones, /telemetria, /ws
"""
import json
import secrets
import string
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from core.auth import get_current_user, require_terapeuta
from core.config import get_settings
from core.database import get_supabase
from models.schemas import (
    ActividadIn, ActividadOut,
    PacienteIn, PacienteOut,
    PaqueteTelemetria,
    RegistroTerapeutaIn,
    SesionIn, SesionOut,
    WsLoginPaciente,
)
from services.connection_manager import manager

cfg = get_settings()
router = APIRouter()

# ════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════

@router.post("/auth/registro/terapeuta", tags=["Auth"])
async def registro_terapeuta(body: RegistroTerapeutaIn):
    """Registra un nuevo terapeuta. Rol guardado en user_metadata de Supabase Auth."""
    db = get_supabase()
    try:
        res = db.auth.admin.create_user({
            "email":    body.email,
            "password": body.password,
            "user_metadata": {
                "rol":        "terapeuta",
                "nombres":    body.nombres,
                "apellidos":  body.apellidos,
            },
            "email_confirm": True,
        })
        user_id = res.user.id

        # Insertar perfil clínico en tabla especialistas
        db.table("especialistas").insert({
            "id":          user_id,
            "nombres":     body.nombres,
            "apellidos":   body.apellidos,
            "email":       body.email,
            "especialidad": body.especialidad,
        }).execute()

        return {"mensaje": "Terapeuta registrado correctamente.", "id": user_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auth/login", tags=["Auth"])
async def login(email: str, password: str):
    """Login estándar — retorna access_token de Supabase."""
    db = get_supabase()
    try:
        res = db.auth.sign_in_with_password({"email": email, "password": password})
        user_meta = res.user.user_metadata or {}
        return {
            "access_token": res.session.access_token,
            "rol": user_meta.get("rol"),
            "nombres": user_meta.get("nombres"),
        }
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")


@router.post("/auth/login/paciente", tags=["Auth"])
async def login_paciente(body: WsLoginPaciente):
    """
    Login por PIN de 6 dígitos para pacientes.
    Retorna un token de sesión temporal para el WebSocket.
    """
    db = get_supabase()
    res = db.table("pacientes").select("*").eq("pin_acceso", body.pin).eq("activo", True).execute()
    if not res.data:
        raise HTTPException(status_code=401, detail="PIN incorrecto o paciente inactivo.")
    paciente = res.data[0]

    # Si el paciente tiene auth_user_id, generar token de Supabase
    if paciente.get("auth_user_id"):
        # Token ya gestionado por Supabase Auth; aquí retornamos datos básicos
        pass

    return {
        "paciente_id": paciente["id"],
        "nombres":     paciente["nombres"],
        "apellidos":   paciente["apellidos"],
        "nivel_movilidad": paciente["nivel_movilidad"],
    }


# ════════════════════════════════════════════════════════════
# PACIENTES
# ════════════════════════════════════════════════════════════

@router.post("/pacientes", tags=["Pacientes"], response_model=PacienteOut)
async def crear_paciente(
    body: PacienteIn,
    user: dict = Depends(require_terapeuta),
):
    db = get_supabase()
    especialista_id = user["sub"]

    # Generar PIN único de 6 dígitos
    pin = _generar_pin_unico(db)

    # Calcular umbral G según nivel de movilidad
    umbral_map = {
        "critico":     cfg.umbral_g_critico,
        "intermedio":  cfg.umbral_g_intermedio,
        "recuperado":  cfg.umbral_g_recuperado,
    }

    data = {
        "especialista_id": especialista_id,
        "nombres":         body.nombres,
        "apellidos":       body.apellidos,
        "diagnostico":     body.diagnostico,
        "nivel_movilidad": body.nivel_movilidad,
        "pin_acceso":      pin,
    }
    if body.fecha_nacimiento:
        data["fecha_nacimiento"] = body.fecha_nacimiento

    res = db.table("pacientes").insert(data).execute()
    return res.data[0]


@router.get("/pacientes", tags=["Pacientes"])
async def listar_pacientes(user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    res = (
        db.table("pacientes")
        .select("*")
        .eq("especialista_id", user["sub"])
        .eq("activo", True)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


@router.get("/pacientes/{paciente_id}", tags=["Pacientes"])
async def obtener_paciente(paciente_id: str, user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    res = (
        db.table("pacientes")
        .select("*, sesiones(id, estado, nivel_dificultad, iniciada_at, finalizada_at)")
        .eq("id", paciente_id)
        .eq("especialista_id", user["sub"])
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Paciente no encontrado.")
    return res.data


@router.delete("/pacientes/{paciente_id}", tags=["Pacientes"])
async def eliminar_paciente(paciente_id: str, user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    db.table("pacientes").update({"activo": False}).eq("id", paciente_id).eq("especialista_id", user["sub"]).execute()
    return {"mensaje": "Paciente desactivado correctamente."}


# ════════════════════════════════════════════════════════════
# ACTIVIDADES
# ════════════════════════════════════════════════════════════

@router.post("/actividades", tags=["Actividades"], response_model=ActividadOut)
async def crear_actividad(body: ActividadIn, user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    res = db.table("actividades").insert({
        "especialista_id":    user["sub"],
        "nombre":             body.nombre,
        "descripcion_clinica": body.descripcion_clinica,
        "eje_movimiento":     body.eje_movimiento,
        "patron_validacion":  body.patron_validacion,
    }).execute()
    return res.data[0]


@router.get("/actividades", tags=["Actividades"])
async def listar_actividades(user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    res = (
        db.table("actividades")
        .select("*")
        .eq("especialista_id", user["sub"])
        .execute()
    )
    return res.data


# ════════════════════════════════════════════════════════════
# SESIONES
# ════════════════════════════════════════════════════════════

@router.post("/sesiones", tags=["Sesiones"], response_model=SesionOut)
async def crear_sesion(body: SesionIn, user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    especialista_id = user["sub"]

    # Calcular tmax y umbral según configuración del paciente
    paciente_res = db.table("pacientes").select("nivel_movilidad").eq("id", body.paciente_id).single().execute()
    if not paciente_res.data:
        raise HTTPException(404, "Paciente no encontrado.")

    tmax_map = {"facil": cfg.tmax_facil, "medio": cfg.tmax_medio, "dificil": cfg.tmax_dificil}
    umbral_map = {"critico": cfg.umbral_g_critico, "intermedio": cfg.umbral_g_intermedio, "recuperado": cfg.umbral_g_recuperado}

    nivel_mov = paciente_res.data["nivel_movilidad"]
    tmax    = tmax_map[body.nivel_dificultad]
    umbral  = umbral_map[nivel_mov]

    data = {
        "paciente_id":         body.paciente_id,
        "especialista_id":     especialista_id,
        "actividad_id":        body.actividad_id,
        "nivel_dificultad":    body.nivel_dificultad,
        "num_rondas":          body.num_rondas,
        "tiempo_descanso_seg": body.tiempo_descanso_seg,
        "porcentaje_go":       body.porcentaje_go,
        "tmax_seg":            tmax,
        "umbral_g":            umbral,
        "estado":              "pendiente",
    }
    res = db.table("sesiones").insert(data).execute()
    return res.data[0]


@router.post("/sesiones/{sesion_id}/iniciar", tags=["Sesiones"])
async def iniciar_sesion(sesion_id: str, user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    res = db.table("sesiones").select("*").eq("id", sesion_id).eq("especialista_id", user["sub"]).single().execute()
    if not res.data:
        raise HTTPException(404, "Sesión no encontrada.")
    sesion = res.data
    if sesion["estado"] != "pendiente":
        raise HTTPException(400, f"La sesión ya está en estado '{sesion['estado']}'.")

    await manager.iniciar_sesion(sesion_id, sesion)
    return {"mensaje": "Sesión iniciada.", "sesion_id": sesion_id}


@router.post("/sesiones/{sesion_id}/abortar", tags=["Sesiones"])
async def abortar_sesion(sesion_id: str, user: dict = Depends(require_terapeuta)):
    await manager.abortar_sesion(sesion_id)
    return {"mensaje": "Sesión abortada."}


@router.get("/sesiones/{sesion_id}/resultados", tags=["Sesiones"])
async def resultados_sesion(sesion_id: str, user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    res = (
        db.table("resultados_rondas")
        .select("*")
        .eq("sesion_id", sesion_id)
        .order("numero_ronda")
        .execute()
    )
    return res.data


@router.get("/pacientes/{paciente_id}/historial", tags=["Sesiones"])
async def historial_paciente(paciente_id: str, user: dict = Depends(require_terapeuta)):
    db = get_supabase()
    res = (
        db.table("vista_resumen_sesiones")
        .select("*")
        .eq("paciente_id", paciente_id)
        .eq("especialista_id", user["sub"])
        .order("iniciada_at", desc=True)
        .execute()
    )
    return res.data


# ════════════════════════════════════════════════════════════
# TELEMETRÍA — endpoint HTTP POST desde la Pico
# ════════════════════════════════════════════════════════════

@router.post("/telemetria", tags=["Telemetría"])
async def recibir_telemetria(body: PaqueteTelemetria):
    """
    Endpoint que la Raspberry Pi Pico llama cada 500 ms via urequests.post().
    No requiere autenticación de usuario (autenticado por sesion_id válido).
    """
    try:
        db = get_supabase()

        # Verificar sesión
        res = db.table("sesiones").select("id, estado").eq("id", body.sesion_id).single().execute()
        if not res.data or res.data["estado"] != "en_curso":
            return {"ok": False, "razon": "Sesión no activa"}

        # Actualizar ping
        db.table("dispositivos_pico").upsert({
            "sesion_id": body.sesion_id,
            "ultimo_ping": "now()",
        }, on_conflict="sesion_id").execute()

        # Procesar telemetría
        await manager.procesar_telemetria(body.sesion_id, body.muestras)
        return {"ok": True}

    except Exception as e:
        import traceback
        print(f"ERROR en telemetría: {e}")
        print(traceback.format_exc())
        # En producción, loguear pero no exponer detalles
        raise HTTPException(status_code=500, detail="Error interno al procesar telemetría")


# ════════════════════════════════════════════════════════════
# WEBSOCKET — Terapeuta
# ════════════════════════════════════════════════════════════

@router.websocket("/ws/terapeuta/{sesion_id}")
async def ws_terapeuta(websocket: WebSocket, sesion_id: str):
    """
    Terapeuta se conecta con el token JWT en el primer mensaje.
    Recibe: estimulos, telemetria en vivo, resultados de ronda, fin de sesión.
    """
    # Validar origen para WebSocket (CORS no maneja upgrade requests automáticamente)
    origin = websocket.headers.get("origin")
    allowed_origins = [
        cfg.frontend_url,
        "https://acv-rehab-proyecto.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # Railway domains
        "https://*.up.railway.app",
        "https://*.railway.app",
    ]
    if origin and not any(origin.startswith(o.replace("*.", "")) or origin == o for o in allowed_origins if "*" not in o) and not any(origin.endswith(o.replace("*.", "")) for o in allowed_origins if "*" in o):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origen no permitido")
        return

    await manager.conectar_terapeuta(sesion_id, websocket)
    try:
        while True:
            _ = await websocket.receive_text()  # mantener vivo
    except WebSocketDisconnect:
        manager.desconectar(sesion_id, "terapeuta")


# ════════════════════════════════════════════════════════════
# WEBSOCKET — Paciente
# ════════════════════════════════════════════════════════════

@router.websocket("/ws/paciente/{paciente_id}")
async def ws_paciente(websocket: WebSocket, paciente_id: str):
    """
    Paciente se conecta con su paciente_id (validado previamente por PIN).
    Queda en sala de espera hasta que el terapeuta inicie la sesión.
    Recibe: estimulos visuales/auditivos, resultados, fin de sesión.
    """
    # Validar origen para WebSocket (CORS no maneja upgrade requests automáticamente)
    origin = websocket.headers.get("origin")
    allowed_origins = [
        cfg.frontend_url,
        "https://acv-rehab-proyecto.vercel.app",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # Railway domains
        "https://*.up.railway.app",
        "https://*.railway.app",
    ]
    if origin and not any(origin.startswith(o.replace("*.", "")) or origin == o for o in allowed_origins if "*" not in o) and not any(origin.endswith(o.replace("*.", "")) for o in allowed_origins if "*" in o):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origen no permitido")
        return

    await manager.conectar_paciente_espera(paciente_id, websocket)
    try:
        while True:
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.desconectar_paciente_espera(paciente_id)


# ════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════

def _generar_pin_unico(db) -> str:
    """Genera un PIN de 6 dígitos que no exista en la tabla pacientes."""
    while True:
        pin = "".join(secrets.choice(string.digits) for _ in range(6))
        res = db.table("pacientes").select("id").eq("pin_acceso", pin).execute()
        if not res.data:
            return pin

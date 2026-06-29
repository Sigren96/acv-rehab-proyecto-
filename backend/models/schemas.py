"""
models/schemas.py
Modelos Pydantic para validación de datos de entrada y salida.
"""
from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List
from datetime import datetime
import uuid
import json


# ─────────────────────────────────────────
# TELEMETRÍA — Pico → Backend
# ─────────────────────────────────────────

class MuestraIMU(BaseModel):
    """Una sola lectura del MPU6050 (acelerómetro + giroscopio, ya en G y °/s)."""
    x:  float = Field(..., description="Aceleración eje X en G")
    y:  float = Field(..., description="Aceleración eje Y en G")
    z:  float = Field(..., description="Aceleración eje Z en G")
    gx: float = Field(..., description="Velocidad angular eje X en °/s")
    gy: float = Field(..., description="Velocidad angular eje Y en °/s")
    gz: float = Field(..., description="Velocidad angular eje Z en °/s")


class PaqueteTelemetria(BaseModel):
    """Paquete que envía la Pico cada 500 ms (10 muestras × 50 ms)."""
    sesion_id: str = Field(..., description="UUID de la sesión activa")
    muestras:  List[MuestraIMU] = Field(..., min_length=1, max_length=100, description="Lista de muestras IMU (típicamente 10)")


# ─────────────────────────────────────────
# AUTENTICACIÓN
# ─────────────────────────────────────────

class RegistroTerapeutaIn(BaseModel):
    email:       str
    password:    str = Field(..., min_length=6)
    nombres:     str
    apellidos:   str
    especialidad: Optional[str] = None


class LoginIn(BaseModel):
    email:    str
    password: str


# ─────────────────────────────────────────
# PACIENTES
# ─────────────────────────────────────────

class PacienteIn(BaseModel):
    nombres:          str
    apellidos:        str
    fecha_nacimiento: Optional[str] = None   # ISO date string YYYY-MM-DD
    diagnostico:      Optional[str] = None
    nivel_movilidad:  Literal["critico", "intermedio", "recuperado"] = "critico"


class PacienteOut(BaseModel):
    id:               str
    nombres:          str
    apellidos:        str
    nivel_movilidad:  str
    pin_acceso:       str
    diagnostico:      Optional[str]
    activo:           bool
    created_at:       datetime


# ─────────────────────────────────────────
# ACTIVIDADES
# ─────────────────────────────────────────

class ActividadIn(BaseModel):
    nombre:              str
    descripcion_clinica: Optional[str] = None
    eje_movimiento:      Literal["X", "Y", "Z"]
    patron_validacion:   Literal["lineal", "rotacion"]


class ActividadOut(BaseModel):
    id:                  str
    nombre:              str
    descripcion_clinica: Optional[str]
    eje_movimiento:      str
    patron_validacion:   str
    es_predefinida:      bool


# ─────────────────────────────────────────
# SESIONES
# ─────────────────────────────────────────

class SesionIn(BaseModel):
    paciente_id:        str
    actividad_id:       Optional[str] = None
    nivel_dificultad:   Literal["facil", "medio", "dificil"] = "facil"
    num_rondas:         int = Field(10, ge=1, le=50)
    tiempo_descanso_seg: int = Field(3, ge=1, le=30)
    porcentaje_go:      int = Field(70, ge=10, le=90)
    eje_movimiento:     Optional[Literal["X", "Y", "Z"]] = None
    patron_validacion:  Optional[Literal["lineal", "rotacion"]] = None


class SesionOut(BaseModel):
    id:                 str
    paciente_id:        str
    estado:             str
    nivel_dificultad:   str
    num_rondas:         int
    porcentaje_go:      int
    tmax_seg:           float
    umbral_g:           float
    iniciada_at:        Optional[datetime]
    finalizada_at:      Optional[datetime]
    created_at:         datetime


# ─────────────────────────────────────────
# RESULTADOS DE RONDA
# ─────────────────────────────────────────

class ResultadoRondaOut(BaseModel):
    id:                 str
    sesion_id:          str
    numero_ronda:       int
    tipo_estimulo:      str
    direccion_objetivo: Optional[str]
    resultado:          str
    latencia_ms:        Optional[int]
    angulo_final_deg:   Optional[float]
    tasa_temblor:       Optional[float]
    ejecutada_at:       datetime


# ─────────────────────────────────────────
# WEBSOCKET — Mensajes internos del servidor
# ─────────────────────────────────────────

class WsLoginPaciente(BaseModel):
    """Mensaje de login del paciente vía WebSocket (PIN de acceso)."""
    pin: str = Field(..., min_length=4, max_length=8, description="PIN de acceso del paciente")


class WsEstimulo(BaseModel):
    """Mensaje que el backend envía al frontend vía WebSocket."""
    tipo: Literal["estimulo", "resultado_ronda", "telemetria", "sesion_fin", "sesion_inicio", "ping"]
    payload: dict




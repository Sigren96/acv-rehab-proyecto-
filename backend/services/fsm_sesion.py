"""
services/fsm_sesion.py
Motor de la Máquina de Estados Finitos (FSM) de cada sesión terapéutica.
Corre completamente en el backend. La Pico solo envía datos crudos.

Estados:
  S0 → PENDIENTE      (sesión creada, esperando inicio del terapeuta)
  S1 → INICIADA       (terapeuta activó la sesión)
  S2 → ESPERA         (descanso entre rondas)
  S3 → ESTIMULO_ACTIVO (GO o NO-GO enviado al frontend, midiendo respuesta)
  S4 → PROCESANDO     (ronda terminada, calculando métricas)
  S5 → FINALIZADA     (todas las rondas completadas)
  S6 → ABORTADA       (terapeuta canceló)
"""
import asyncio
import math
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, List

from core.config import get_settings
from core.database import get_supabase
from models.schemas import MuestraIMU

cfg = get_settings()

# Mapeo de dirección → eje e sentido esperado
DIRECCION_MAP = {
    "derecha":   ("x",  1),
    "izquierda": ("x", -1),
    "arriba":    ("y",  1),
    "abajo":     ("y", -1),
}

# Keyword mapping para actividades personalizadas (D11)
KEYWORDS_EJE = {
    "izquierda": ("x", -1), "siniestro": ("x", -1),
    "derecha":   ("x",  1), "diestro":   ("x",  1),
    "arriba":    ("y",  1), "superior":  ("y",  1),
    "abajo":     ("y", -1), "inferior":  ("y", -1),
    "circulo":   ("z",  0), "círculo":   ("z",  0),
    "girar":     ("z",  0), "rotacion":  ("z",  0), "rotación": ("z",  0),
}


def resolver_keywords(descripcion: str) -> tuple[str, int]:
    """
    Extrae eje y sentido de una descripción textual libre.
    Retorna (eje, sentido) o ("x", 1) como default.
    """
    texto = descripcion.lower()
    for kw, resultado in KEYWORDS_EJE.items():
        if kw in texto:
            return resultado
    return ("x", 1)


class ProcesadorIMU:
    """
    Recibe paquetes de 10 muestras IMU y aplica los tres algoritmos de métricas.
    Cada instancia pertenece a una ronda activa.
    """

    def __init__(
        self,
        tipo_estimulo: str,       # "GO" | "NO-GO"
        direccion: Optional[str], # "arriba"|"abajo"|"izquierda"|"derecha"|"circulo"
        umbral_g: float,
        tmax_seg: float,
        patron: str,              # "lineal" | "rotacion"
    ):
        self.tipo_estimulo = tipo_estimulo
        self.direccion     = direccion
        self.umbral_g      = umbral_g
        self.tmax_seg      = tmax_seg
        self.patron        = patron

        self.t0: float       = time.monotonic()
        self.angulo_acum: float = 0.0          # integración giroscopio
        self.muestras_nogo: List[float] = []   # magnitudes sin gravedad para varianza
        self.latencia_ms: Optional[int] = None
        self.movimiento_detectado: bool = False
        self.paquetes_giro_z: int = 0          # contador para detección de círculos

    # ── Utilidades ──────────────────────────────────────────────────────

    @staticmethod
    def _get_valor(m, campo: str) -> float:
        """Obtiene un valor numérico de una muestra, ya sea dict o objeto Pydantic."""
        if isinstance(m, dict):
            return float(m.get(campo, 0.0))
        return float(getattr(m, campo, 0.0))

    @staticmethod
    def magnitud_sin_gravedad(m) -> float:
        """√(x² + y² + (z-1)²) — elimina la constante de gravedad en Z."""
        x = ProcesadorIMU._get_valor(m, 'x')
        y = ProcesadorIMU._get_valor(m, 'y')
        z = ProcesadorIMU._get_valor(m, 'z')
        return math.sqrt(x**2 + y**2 + (z - 1.0)**2)

    @staticmethod
    def varianza(valores: List[float]) -> float:
        if len(valores) < 2:
            return 0.0
        media = sum(valores) / len(valores)
        return sum((v - media) ** 2 for v in valores) / len(valores)

    # ── Procesamiento principal ──────────────────────────────────────────

    def procesar_paquete(self, muestras: List[Any]) -> Optional[dict]:
        """
        Procesa un paquete de 10 muestras.
        Retorna un dict con el resultado de la ronda si ya terminó, o None si sigue.
        """
        try:
            elapsed_ms = int((time.monotonic() - self.t0) * 1000)

            # Timeout check
            if elapsed_ms > int(self.tmax_seg * 1000):
                return self._cerrar_ronda("timeout")

            for muestra in muestras:
                # Validar que la muestra tenga los campos necesarios (dict o objeto)
                campos_requeridos = ['x', 'y', 'z', 'gx', 'gy', 'gz']
                if isinstance(muestra, dict):
                    if not all(c in muestra for c in campos_requeridos):
                        print(f"ERROR: Muestra IMU incompleta (dict): {muestra}")
                        continue
                elif not all(hasattr(muestra, c) for c in campos_requeridos):
                    print(f"ERROR: Muestra IMU incompleta (obj): {muestra}")
                    continue

                # Integración del giroscopio
                eje_giro = self._eje_giroscopio()
                vel_angular = self._get_valor(muestra, eje_giro)
                self.angulo_acum += vel_angular * cfg.dt_muestreo

                # Acumular magnitudes para Tasa de Temblor
                try:
                    mag = self.magnitud_sin_gravedad(muestra)
                    self.muestras_nogo.append(mag)
                except Exception as e:
                    print(f"ERROR al calcular magnitud: {e}")
                    continue

                # ── GO: detectar movimiento en la dirección objetivo ──
                if self.tipo_estimulo == "GO" and not self.movimiento_detectado:
                    if self.patron == "rotacion":
                        # Círculos: velocidad angular sostenida en Z
                        gz = self._get_valor(muestra, 'gz')
                        if abs(gz) >= cfg.umbral_giro_z:
                            self.paquetes_giro_z += 1
                        else:
                            self.paquetes_giro_z = 0
                        if self.paquetes_giro_z >= cfg.ventana_giro_paquetes:
                            self.movimiento_detectado = True
                            self.latencia_ms = elapsed_ms
                            return self._cerrar_ronda("acierto")
                    else:
                        # Movimiento lineal: umbral de fuerza G en eje objetivo
                        # Usar aceleración compensada de gravedad proyectada en el eje de movimiento
                        eje, sentido = DIRECCION_MAP.get(self.direccion, ("x", 1))
                        # Calcular vector de aceleración sin gravedad: (x, y, z-1)
                        ax = self._get_valor(muestra, 'x')
                        ay = self._get_valor(muestra, 'y')
                        az = self._get_valor(muestra, 'z') - 1.0  # restar gravedad en Z
                        # Proyectar en el eje correspondiente al movimiento
                        if eje == 'x':
                            valor = ax  # izquierda/derecha → eje X
                        elif eje == 'y':
                            valor = ay  # arriba/abajo → eje Y
                        else:
                            valor = 0.0
                        if sentido == 1 and valor > self.umbral_g:
                            self.movimiento_detectado = True
                            self.latencia_ms = elapsed_ms
                            return self._cerrar_ronda("acierto")
                        elif sentido == -1 and valor < -self.umbral_g:
                            self.movimiento_detectado = True
                            self.latencia_ms = elapsed_ms
                            return self._cerrar_ronda("acierto")

                # ── NO-GO: detectar movimiento indebido ──
                elif self.tipo_estimulo == "NO-GO":
                    mag = self.magnitud_sin_gravedad(muestra)
                    if mag > self.umbral_g:
                        # Se movió cuando no debía
                        return self._cerrar_ronda("error")

            return None  # Ronda sigue abierta

        except Exception as e:
            print(f"ERROR en procesar_paquete: {e}")
            import traceback
            print(traceback.format_exc())
            return self._cerrar_ronda("error")  # Cerrar ronda con error en lugar de crash

    def _eje_giroscopio(self) -> str:
        """Retorna el atributo gx/gy/gz según la dirección del ejercicio."""
        if self.direccion in ("arriba", "abajo"):
            return "gx"
        if self.direccion == "circulo":
            return "gz"
        return "gy"

    def _cerrar_ronda(self, resultado: str) -> dict:
        return {
            "resultado":        resultado,
            "latencia_ms":      self.latencia_ms,
            "angulo_final_deg": round(self.angulo_acum, 3),
            "tasa_temblor":     round(self.varianza(self.muestras_nogo), 6),
        }


class SesionFSM:
    """
    Controla el ciclo completo de una sesión terapéutica.
    Una instancia vive en memoria mientras la sesión está en curso.
    Se crea en el ConnectionManager al iniciar la sesión.
    """

    def __init__(self, sesion_db: dict):
        self.sesion_id       = sesion_db["id"]
        self.paciente_id     = sesion_db["paciente_id"]
        self.num_rondas      = sesion_db["num_rondas"]
        self.tmax_seg        = float(sesion_db["tmax_seg"])
        self.umbral_g        = float(sesion_db["umbral_g"])
        self.tiempo_descanso = sesion_db["tiempo_descanso_seg"]
        self.porcentaje_go   = sesion_db["porcentaje_go"]
        self.patron          = "lineal"  # default; se sobreescribe si hay actividad

        self.ronda_actual    = 0
        self.estado          = "iniciada"   # iniciada | espera | estimulo | procesando | finalizada
        self.procesador: Optional[ProcesadorIMU] = None
        self.cola_estimulos: List[dict] = []

        self._generar_cola_estimulos()

    def _generar_cola_estimulos(self):
        """Genera la cola aleatoria de GO/NO-GO según el porcentaje configurado."""
        n_go    = round(self.num_rondas * self.porcentaje_go / 100)
        n_nogo  = self.num_rondas - n_go
        direcciones = list(DIRECCION_MAP.keys())

        estimulos = []
        for _ in range(n_go):
            estimulos.append({
                "tipo":      "GO",
                "direccion": random.choice(direcciones),
            })
        for _ in range(n_nogo):
            estimulos.append({
                "tipo":      "NO-GO",
                "direccion": None,
            })
        random.shuffle(estimulos)
        self.cola_estimulos = estimulos

    def siguiente_estimulo(self) -> Optional[dict]:
        """Retorna el próximo estímulo o None si ya terminaron las rondas."""
        if self.ronda_actual >= len(self.cola_estimulos):
            return None
        est = self.cola_estimulos[self.ronda_actual]
        self.ronda_actual += 1
        return est

    def iniciar_ronda(self, estimulo: dict) -> ProcesadorIMU:
        """Crea un ProcesadorIMU fresco para la ronda activa."""
        self.procesador = ProcesadorIMU(
            tipo_estimulo=estimulo["tipo"],
            direccion=estimulo.get("direccion"),
            umbral_g=self.umbral_g,
            tmax_seg=self.tmax_seg,
            patron=self.patron,
        )
        self.estado = "estimulo"
        return self.procesador

    def procesar_paquete(self, muestras: List[Any]) -> Optional[dict]:
        """Delega al procesador activo; si no hay ronda activa retorna None."""
        if self.procesador is None or self.estado != "estimulo":
            return None
        resultado = self.procesador.procesar_paquete(muestras)
        if resultado is not None:
            self.estado = "procesando"
            self.procesador = None
        return resultado

    @property
    def finalizada(self) -> bool:
        return self.ronda_actual >= self.num_rondas and self.estado in ("procesando", "espera")

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
import math
import random
import time
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
    Procesador IMU ultra-simplificado para transmisión en tiempo real.
    
    REGLAS ESTRICTAS:
    1. Formato WebSocket Puro: Retorna dict con llaves originales x, y, z 
       mapeando valores directos del acelerómetro de la muestra actual.
    2. Umbral Ultra Suave (0.2G): Para estímulos GO, si la magnitud de 
       aceleración supera 0.2G → registra ACIERTO inmediato en historial.
    
    Sin fusión de sensores, sin matrices 3D, sin estimación de gravedad.
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
        self.movimiento_detectado: bool = False
        self.latencia_ms: Optional[int] = None
        self.aciertos: List[dict] = []  # Historial de aciertos para GO

    @staticmethod
    def _get_valor(m, campo: str) -> float:
        """Obtiene un valor numérico de una muestra, ya sea dict o objeto Pydantic."""
        if isinstance(m, dict):
            return float(m.get(campo, 0.0))
        return float(getattr(m, campo, 0.0))

    @staticmethod
    def _magnitud(ax: float, ay: float, az: float) -> float:
        """Magnitud del vector aceleración."""
        return math.sqrt(ax*ax + ay*ay + az*az)

    def procesar_paquete(self, muestras: List[Any]) -> Optional[dict]:
        """
        Procesa un paquete de muestras IMU.
        
        REGLA 1 - Formato WebSocket Puro:
        Retorna dict con llaves x, y, z mapeando valores directos del acelerómetro
        de la ÚLTIMA muestra del paquete para que el frontend pinte gráficas en tiempo real.
        
        REGLA 2 - Umbral Ultra Suave (0.2G):
        Para estímulos GO: calcula magnitud de aceleración. Si > 0.2G → ACIERTO inmediato.
        """
        try:
            elapsed_ms = int((time.monotonic() - self.t0) * 1000)

            # Timeout check
            if elapsed_ms > int(self.tmax_seg * 1000):
                return self._cerrar_ronda("timeout")

            # Tomar la última muestra del paquete para WebSocket en tiempo real
            ultima_muestra = muestras[-1] if muestras else None
            if ultima_muestra is None:
                return None

            # Extraer valores directos del acelerómetro (sin procesar)
            ax = self._get_valor(ultima_muestra, 'x')
            ay = self._get_valor(ultima_muestra, 'y')
            az = self._get_valor(ultima_muestra, 'z')

            # REGLA 1: Formato WebSocket Puro - llaves x, y, z intactas
            ws_data = {
                "x": ax,
                "y": ay,
                "z": az,
                "timestamp_ms": elapsed_ms,
            }

            # REGLA 2: Umbral Ultra Suave 0.2G para estímulos GO
            if self.tipo_estimulo == "GO" and not self.movimiento_detectado:
                mag = self._magnitud(ax, ay, az)
                # Umbral muy accesible: 0.2G para máxima sensibilidad
                if mag > 0.2:
                    self.movimiento_detectado = True
                    self.latencia_ms = elapsed_ms
                    # Registrar acierto inmediato en historial
                    self.aciertos.append({
                        "tipo": "acierto",
                        "latencia_ms": elapsed_ms,
                        "magnitud_g": round(mag, 3),
                        "direccion": self.direccion,
                    })
                    return self._cerrar_ronda("acierto", ws_data)

            # Para NO-GO: solo transmitir datos, no cerrar por movimiento
            # (la lógica de error NO-GO se maneja en el frontend o en nivel superior)

            # Retornar datos WebSocket para gráficas en tiempo real
            return ws_data

        except Exception as e:
            print(f"ERROR en procesar_paquete: {e}")
            import traceback
            print(traceback.format_exc())
            return self._cerrar_ronda("error")

    def _cerrar_ronda(self, resultado: str, ws_data: dict = None) -> dict:
        """Cierra la ronda y retorna resultado final + datos WebSocket."""
        base = {
            "resultado":        resultado,
            "latencia_ms":      self.latencia_ms,
            "aciertos":         self.aciertos,
        }
        if ws_data:
            base.update(ws_data)
        return base


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
        if resultado is not None and isinstance(resultado, dict) and "resultado" in resultado:
            self.estado = "procesando"
            self.procesador = None
        return resultado

    @property
    def finalizada(self) -> bool:
        return self.ronda_actual >= self.num_rondas and self.estado in ("procesando", "espera")

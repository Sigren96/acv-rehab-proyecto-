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


class EstimadorGravedad:
    """
    Estimador de vector de gravedad 3D usando fusión de sensores (acelerómetro + giroscopio).
    
    Algoritmo: Integración del giroscopio para rotar el vector de gravedad estimado.
    g_new = normalizar(g_old + (w × g_old) * dt)
    
    Donde:
    - w = vector velocidad angular [gx, gy, gz] en rad/s
    - g_old = vector gravedad estimado anterior (normalizado a 1G)
    - dt = intervalo de muestreo
    - × = producto cruz
    """
    
    def __init__(self, dt_muestreo: float = 0.01):
        self.dt = dt_muestreo
        # Vector gravedad inicial: asumimos dispositivo en reposo, Z hacia arriba
        self.g_est = [0.0, 0.0, 1.0]
        self.inicializado = False
    
    def actualizar(self, ax: float, ay: float, az: float, gx: float, gy: float, gz: float) -> List[float]:
        """
        Actualiza la estimación del vector gravedad usando fusión sensor.
        Retorna el vector gravedad estimado [gx, gy, gz] normalizado a 1G.
        """
        # Si es la primera muestra, inicializar con el vector acelerómetro normalizado
        if not self.inicializado:
            mag = math.sqrt(ax*ax + ay*ay + az*az)
            if mag > 0.1:  # Evitar división por cero
                self.g_est = [ax/mag, ay/mag, az/mag]
                self.inicializado = True
            return self.g_est
        
        # Producto cruz: w × g_est
        wx, wy, wz = gx, gy, gz
        gx_est, gy_est, gz_est = self.g_est
        
        cross_x = wy * gz_est - wz * gy_est
        cross_y = wz * gx_est - wx * gz_est
        cross_z = wx * gy_est - wy * gx_est
        
        # Integrar: g_new = g_old + (w × g_old) * dt
        gx_new = gx_est + cross_x * self.dt
        gy_new = gy_est + cross_y * self.dt
        gz_new = gz_est + cross_z * self.dt
        
        # Normalizar a 1G
        mag = math.sqrt(gx_new*gx_new + gy_new*gy_new + gz_new*gz_new)
        if mag > 0.01:
            self.g_est = [gx_new/mag, gy_new/mag, gz_new/mag]
        
        return self.g_est
    
    def obtener_gravedad(self) -> List[float]:
        """Retorna el vector gravedad estimado actual."""
        return self.g_est.copy()
    
    def aceleracion_lineal(self, ax: float, ay: float, az: float) -> List[float]:
        """
        Calcula la aceleración lineal restando la gravedad estimada.
        Retorna [ax_lin, ay_lin, az_lin] en unidades de G.
        """
        gx, gy, gz = self.g_est
        return [ax - gx, ay - gy, az - gz]


class ProcesadorIMU:
    """
    Procesa ráfagas de 10 muestras IMU (100 Hz → 100 ms por paquete).
    Mantiene estado interno por ronda y emite resultado cuando termina.
    """


class EstimadorGravedad:
    """
    Estimador de vector de gravedad 3D usando fusión de sensores (acelerómetro + giroscopio).
    
    Algoritmo: Integración del giroscopio para rotar el vector de gravedad estimado.
    g_new = normalizar(g_old + (w × g_old) * dt)
    
    Donde:
    - w = vector velocidad angular [gx, gy, gz] en rad/s
    - g_old = vector gravedad estimado anterior (normalizado a 1G)
    - dt = intervalo de muestreo
    - × = producto cruz
    """
    
    def __init__(self, dt_muestreo: float = 0.01):
        self.dt = dt_muestreo
        # Vector gravedad inicial: asumimos dispositivo en reposo, Z hacia arriba
        self.g_est = [0.0, 0.0, 1.0]  # [gx, gy, gz] normalizado a 1G
        self.inicializado = False
        self.muestras_iniciales = 0
        self.MUESTRAS_CALIBRACION = 50  # ~0.5s a 100Hz para converger
    
    def actualizar(self, ax: float, ay: float, az: float, gx: float, gy: float, gz: float) -> List[float]:
        """
        Actualiza la estimación del vector gravedad con nueva muestra IMU.
        Retorna el vector gravedad estimado actual [gx, gy, gz] normalizado a 1G.
        """
        # Vector aceleración medida
        a_measured = [ax, ay, az]
        mag_a = math.sqrt(ax*ax + ay*ay + az*az)
        
        # Vector velocidad angular
        w = [gx, gy, gz]
        
        if not self.inicializado:
            # Fase de calibración: promediar aceleración medida para obtener gravedad inicial
            if mag_a > 0.1:  # Evitar división por cero
                self.g_est[0] += ax / mag_a
                self.g_est[1] += ay / mag_a
                self.g_est[2] += az / mag_a
                self.muestras_iniciales += 1
                
                if self.muestras_iniciales >= self.MUESTRAS_CALIBRACION:
                    # Normalizar vector promedio
                    norm = math.sqrt(self.g_est[0]**2 + self.g_est[1]**2 + self.g_est[2]**2)
                    if norm > 0:
                        self.g_est = [v / norm for v in self.g_est]
                    self.inicializado = True
            return self.g_est
        
        # Fusión de sensores: rotar vector gravedad por integración del giroscopio
        # g_new = g_old + (w × g_old) * dt
        # Producto cruz: w × g
        wxg = [
            w[1] * self.g_est[2] - w[2] * self.g_est[1],
            w[2] * self.g_est[0] - w[0] * self.g_est[2],
            w[0] * self.g_est[1] - w[1] * self.g_est[0]
        ]
        
        # Integrar
        self.g_est[0] += wxg[0] * self.dt
        self.g_est[1] += wxg[1] * self.dt
        self.g_est[2] += wxg[2] * self.dt
        
        # Corrección por acelerómetro (filtro complementario simple)
        # Si la magnitud de aceleración medida está cerca de 1G, confiar en acelerómetro
        if 0.8 < mag_a < 1.2:
            alpha = 0.02  # Peso del acelerómetro (bajo para evitar ruido de movimiento)
            a_norm = [ax / mag_a, ay / mag_a, az / mag_a]
            self.g_est[0] = (1 - alpha) * self.g_est[0] + alpha * a_norm[0]
            self.g_est[1] = (1 - alpha) * self.g_est[1] + alpha * a_norm[1]
            self.g_est[2] = (1 - alpha) * self.g_est[2] + alpha * a_norm[2]
        
        # Renormalizar a 1G
        norm = math.sqrt(self.g_est[0]**2 + self.g_est[1]**2 + self.g_est[2]**2)
        if norm > 0:
            self.g_est = [v / norm for v in self.g_est]
        
        return self.g_est
    
    def obtener_gravedad(self) -> List[float]:
        """Retorna el vector gravedad estimado actual [gx, gy, gz] normalizado a 1G."""
        return self.g_est.copy()
    
    def calcular_aceleracion_lineal(self, ax: float, ay: float, az: float) -> List[float]:
        """
        Calcula la aceleración lineal restando el vector gravedad estimado.
        lineal = sensor - gravedad_estimada
        """
        g = self.obtener_gravedad()
        return [ax - g[0], ay - g[1], az - g[2]]
    
    def magnitud_aceleracion_lineal(self, ax: float, ay: float, az: float) -> float:
        """Magnitud de la aceleración lineal (libre de gravedad)."""
        lin = self.calcular_aceleracion_lineal(ax, ay, az)
        return math.sqrt(lin[0]**2 + lin[1]**2 + lin[2]**2)

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

        # Estimador de gravedad por fusión de sensores (acelerómetro + giroscopio)
        self.estimador_gravedad = EstimadorGravedad(dt_muestreo=cfg.dt_muestreo)
        
        self.t0: float       = time.monotonic()
        self.angulo_acum: float = 0.0          # integración giroscopio
        self.muestras_reposo: List[float] = []   # magnitudes sin gravedad SOLO en reposo (NO-GO)
        self.latencia_ms: Optional[int] = None
        self.movimiento_detectado: bool = False
        self.paquetes_giro_z: int = 0          # contador para detección de círculos
        self.umbral_g_lineal: float = 0.3      # umbral 0.3G para aceleración lineal

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
        
        Pipeline de 5 puntos:
        1. Estimador de gravedad por fusión de sensores (acelerómetro + giroscopio)
        2. Aceleración lineal = sensor - gravedad_estimada (por muestra)
        3. Umbral 0.2G en magnitud_sin_gravedad para GO/NO-GO
        4. Acumular muestras_reposo SOLO durante NO-GO
        5. Latencia por muestra dentro del procesamiento del paquete
        """
        try:
            elapsed_ms = int((time.monotonic() - self.t0) * 1000)

            # Timeout check
            if elapsed_ms > int(self.tmax_seg * 1000):
                return self._cerrar_ronda("timeout")

            for i, muestra in enumerate(muestras):
                # Validar que la muestra tenga los campos necesarios (dict o objeto)
                campos_requeridos = ['x', 'y', 'z', 'gx', 'gy', 'gz']
                if isinstance(muestra, dict):
                    if not all(c in muestra for c in campos_requeridos):
                        print(f"ERROR: Muestra IMU incompleta (dict): {muestra}")
                        continue
                elif not all(hasattr(muestra, c) for c in campos_requeridos):
                    print(f"ERROR: Muestra IMU incompleta (obj): {muestra}")
                    continue

                # Extraer valores de la muestra
                ax = self._get_valor(muestra, 'x')
                ay = self._get_valor(muestra, 'y')
                az = self._get_valor(muestra, 'z')
                gx = self._get_valor(muestra, 'gx')
                gy = self._get_valor(muestra, 'gy')
                gz = self._get_valor(muestra, 'gz')

                # 1. Actualizar estimador de gravedad con fusión de sensores
                self.estimador_gravedad.actualizar(ax, ay, az, gx, gy, gz)

                # 2. Calcular aceleración lineal (libre de gravedad) por muestra
                lin = self.estimador_gravedad.calcular_aceleracion_lineal(ax, ay, az)
                lin_x, lin_y, lin_z = lin[0], lin[1], lin[2]

                # 3. Magnitud sin gravedad para decisión GO/NO-GO (umbral 0.2G)
                mag_sin_grav = math.sqrt(lin_x**2 + lin_y**2 + lin_z**2)

                # 4. Integración del giroscopio para ángulo acumulado
                eje_giro = self._eje_giroscopio()
                vel_angular = self._get_valor(muestra, eje_giro)
                self.angulo_acum += vel_angular * cfg.dt_muestreo

                # 5. Latencia por muestra (desde inicio de ronda hasta esta muestra)
                latencia_muestra_ms = elapsed_ms + int(i * cfg.dt_muestreo * 1000)

                # ── GO: detectar movimiento en la dirección objetivo ──
                if self.tipo_estimulo == "GO" and not self.movimiento_detectado:
                    if self.patron == "rotacion":
                        # Círculos: velocidad angular sostenida en Z
                        if abs(gz) >= cfg.umbral_giro_z:
                            self.paquetes_giro_z += 1
                        else:
                            self.paquetes_giro_z = 0
                        if self.paquetes_giro_z >= cfg.ventana_giro_paquetes:
                            self.movimiento_detectado = True
                            self.latencia_ms = latencia_muestra_ms
                            return self._cerrar_ronda("acierto")
                    else:
                        # Movimiento lineal: usar aceleración lineal proyectada en eje objetivo
                        eje, sentido = DIRECCION_MAP.get(self.direccion, ("x", 1))
                        if eje == 'x':
                            valor = lin_x
                        elif eje == 'y':
                            valor = lin_y
                        else:
                            valor = 0.0
                        if sentido == 1 and valor > self.umbral_g_lineal:
                            self.movimiento_detectado = True
                            self.latencia_ms = latencia_muestra_ms
                            return self._cerrar_ronda("acierto")
                        elif sentido == -1 and valor < -self.umbral_g_lineal:
                            self.movimiento_detectado = True
                            self.latencia_ms = latencia_muestra_ms
                            return self._cerrar_ronda("acierto")

                # ── NO-GO: detectar movimiento indebido ──
                elif self.tipo_estimulo == "NO-GO":
                    # Acumular SOLO magnitudes en reposo (NO-GO) para tasa de temblor
                    self.muestras_reposo.append(mag_sin_grav)
                    # Si supera umbral 0.2G → error (se movió cuando no debía)
                    if mag_sin_grav > 0.2:
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
            "tasa_temblor":     round(self.varianza(self.muestras_reposo), 6),
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

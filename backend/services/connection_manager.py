"""
services/connection_manager.py
Gestión centralizada de conexiones WebSocket activas.
Coordina los canales terapeuta ↔ paciente y la FSM de cada sesión.
"""
import asyncio
import json
import time
from typing import Dict, Optional
from fastapi import WebSocket

from services.fsm_sesion import SesionFSM
from core.database import get_supabase
from core.config import get_settings

cfg = get_settings()


class ConnectionManager:
    """
    Registro global de WebSockets activos.

    Estructura:
      sesiones_activas[sesion_id] = {
          "fsm":        SesionFSM,
          "terapeuta":  WebSocket | None,
          "paciente":   WebSocket | None,
          "estimulo_actual": dict | None,
      }

      pacientes_en_espera[paciente_id] = WebSocket
        → paciente conectado pero sin sesión iniciada aún
    """

    def __init__(self):
        self.sesiones_activas: Dict[str, dict] = {}
        self.pacientes_en_espera: Dict[str, WebSocket] = {}

    # ── Conexiones básicas ───────────────────────────────────────────────

    async def conectar_terapeuta(self, sesion_id: str, ws: WebSocket):
        await ws.accept()
        if sesion_id not in self.sesiones_activas:
            self.sesiones_activas[sesion_id] = {
                "fsm": None,
                "terapeuta": None,
                "paciente": None,
                "estimulo_actual": None,
                "buffer_pendiente": [],
            }
        self.sesiones_activas[sesion_id]["terapeuta"] = ws

    async def conectar_paciente_espera(self, paciente_id: str, ws: WebSocket):
        """Paciente se conecta antes de que el terapeuta inicie sesión."""
        await ws.accept()
        self.pacientes_en_espera[paciente_id] = ws
        await self._enviar(ws, {
            "tipo": "ping",
            "payload": {"mensaje": "Conectado. Esperando que el terapeuta inicie tu sesión."},
        })

    async def conectar_paciente_sesion(self, sesion_id: str, paciente_id: str):
        """
        Mueve al paciente de la sala de espera al slot de la sesión activa.
        Se llama cuando el terapeuta inicia la sesión.
        """
        ws = self.pacientes_en_espera.pop(paciente_id, None)
        if ws and sesion_id in self.sesiones_activas:
            self.sesiones_activas[sesion_id]["paciente"] = ws

    def desconectar(self, sesion_id: str, rol: str):
        if sesion_id in self.sesiones_activas:
            self.sesiones_activas[sesion_id][rol] = None

    def desconectar_paciente_espera(self, paciente_id: str):
        self.pacientes_en_espera.pop(paciente_id, None)

    # ── Inicio de sesión (terapeuta dispara la FSM) ──────────────────────

    async def iniciar_sesion(self, sesion_id: str, sesion_db: dict):
        """
        El terapeuta presiona "Iniciar sesión".
        1. Crea la FSM.
        2. Actualiza el estado en Supabase.
        3. Notifica al paciente.
        4. Arranca el loop de rondas en background.
        """
        fsm = SesionFSM(sesion_db)

        # Si hay actividad con patrón de rotación, actualizar FSM
        if sesion_db.get("patron_validacion") == "rotacion":
            fsm.patron = "rotacion"

        if sesion_id not in self.sesiones_activas:
            self.sesiones_activas[sesion_id] = {
                "fsm": None, "terapeuta": None,
                "paciente": None, "estimulo_actual": None,
            }
        self.sesiones_activas[sesion_id]["fsm"] = fsm

        # Procesar paquetes bufferizados durante la race condition
        buffer_pendiente = self.sesiones_activas[sesion_id].pop("buffer_pendiente", [])
        for muestras_pendientes in buffer_pendiente:
            fsm.procesar_paquete(muestras_pendientes)
        print(f"[TELEMETRIA] {len(buffer_pendiente)} paquetes recuperados del buffer al iniciar sesión {sesion_id}")

        # Actualizar BD
        db = get_supabase()
        db.table("sesiones").update({
            "estado": "en_curso",
            "iniciada_at": "now()",
        }).eq("id", sesion_id).execute()

        # Conectar paciente desde sala de espera
        paciente_id = sesion_db["paciente_id"]
        await self.conectar_paciente_sesion(sesion_id, paciente_id)

        # Notificar ambos clientes
        await self.broadcast(sesion_id, {
            "tipo": "sesion_inicio",
            "payload": {
                "sesion_id": sesion_id,
                "num_rondas": sesion_db["num_rondas"],
                "nivel_dificultad": sesion_db["nivel_dificultad"],
            },
        })

        # Arrancar loop de rondas en background
        asyncio.create_task(self._loop_rondas(sesion_id))

    # ── Loop principal de rondas ─────────────────────────────────────────

    async def _loop_rondas(self, sesion_id: str):
        slot = self.sesiones_activas.get(sesion_id)
        if not slot:
            return
        fsm: SesionFSM = slot["fsm"]

        while True:
            # Obtener siguiente estímulo
            estimulo = fsm.siguiente_estimulo()
            if estimulo is None:
                await self._finalizar_sesion(sesion_id)
                break

            # Descanso entre rondas
            await asyncio.sleep(fsm.tiempo_descanso)

            # Lanzar estímulo
            fsm.iniciar_ronda(estimulo)
            slot["estimulo_actual"] = estimulo
            t0_unix = time.time()

            estimulo_msg = {
                "tipo": "estimulo",
                "payload": {
                    "ronda":     fsm.ronda_actual,
                    "total":     fsm.num_rondas,
                    "estimulo":  estimulo["tipo"],
                    "direccion": estimulo.get("direccion"),
                    "tmax_seg":  fsm.tmax_seg,
                    "t0":        t0_unix,
                },
            }
            await self.broadcast(sesion_id, estimulo_msg)

            # Esperar resultado (la Pico enviará paquetes que procesará telemetria_handler)
            resultado = await self._esperar_resultado_ronda(sesion_id, fsm)

            # Guardar métricas en Supabase
            await self._guardar_resultado(sesion_id, fsm, estimulo, resultado, fsm.ronda_actual)

            # Notificar resultado al frontend
            await self.broadcast(sesion_id, {
                "tipo": "resultado_ronda",
                "payload": {
                    "ronda":       fsm.ronda_actual,
                    "resultado":   resultado["resultado"],
                    "latencia_ms": resultado.get("latencia_ms"),
                    "angulo_deg":  resultado.get("angulo_final_deg"),
                    "temblor":     resultado.get("tasa_temblor"),
                    "estimulo":    estimulo["tipo"],
                    "direccion":   estimulo.get("direccion"),
                },
            })

            slot["estimulo_actual"] = None

            if fsm.finalizada:
                await self._finalizar_sesion(sesion_id)
                break

    async def _esperar_resultado_ronda(self, sesion_id: str, fsm: SesionFSM) -> dict:
        """
        Polling asíncrono: espera hasta que la FSM devuelva un resultado
        (por telemetría entrante) o se cumpla el tmax + margen.
        """
        margen_extra = 0.5  # segundos extra tras tmax para recibir el último paquete
        deadline = time.monotonic() + fsm.tmax_seg + margen_extra

        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            slot = self.sesiones_activas.get(sesion_id)
            if slot and slot.get("_ultimo_resultado"):
                resultado = slot.pop("_ultimo_resultado")
                return resultado

        # Timeout forzado
        return {
            "resultado":        "timeout",
            "latencia_ms":      None,
            "angulo_final_deg": 0.0,
            "tasa_temblor":     0.0,
        }

    # ── Procesamiento de telemetría desde la Pico ────────────────────────

    async def procesar_telemetria(self, sesion_id: str, muestras):
        """
        Llamado por el router de telemetría cada vez que llega un paquete HTTP POST.
        Delega a la FSM y retransmite datos crudos al frontend via WebSocket.
        """
        print(f"[DIAG] procesar_telemetria INICIO sesion_id={sesion_id} num_muestras={len(muestras) if isinstance(muestras, list) else 'N/A'}")
        try:
            slot = self.sesiones_activas.get(sesion_id)
            if not slot:
                print(f"[DIAG] DROP - slot no existe sesion_id={sesion_id}")
                return

            if not slot.get("fsm"):
                slot.setdefault("buffer_pendiente", []).append(muestras)
                print(f"[DIAG] BUFFERED - FSM no lista sesion_id={sesion_id} buffer_size={len(slot['buffer_pendiente'])}")
                return

            fsm: SesionFSM = slot["fsm"]
            print(f"[DIAG] FSM encontrada, procesando {len(muestras)} muestras")

            # Validar que muestras sea lista
            if not isinstance(muestras, list):
                print(f"[DIAG] ERROR: muestras no es lista, es {type(muestras)}")
                return

            # Retransmitir datos crudos al frontend (con manejo seguro)
            try:
                muestras_dict = []
                for m in muestras:
                    # Convertimos el objeto de Pydantic a un diccionario plano de Python
                    d = m.model_dump() if hasattr(m, 'model_dump') else (m.__dict__ if hasattr(m, '__dict__') else dict(m))
                    
                    # Mapeamos explícitamente las llaves que el frontend exige para pintar la gráfica
                    muestra_transformada = {
                        "ax": d.get("x", 0.0),
                        "ay": d.get("y", 0.0),
                        "az": d.get("z", 0.0),
                        "timestamp_ms": d.get("timestamp_ms", 0.0)
                    }
                    muestras_dict.append(muestra_transformada)

                print(f"[DIAG] BROADCAST telemetría cruda - {len(muestras_dict)} muestras, primera: ax={muestras_dict[0]['ax']:.3f} ay={muestras_dict[0]['ay']:.3f} az={muestras_dict[0]['az']:.3f}")

                await self.broadcast(sesion_id, {
                    "tipo": "telemetria",
                    "payload": {
                        "muestras": muestras_dict,
                        "ts": time.time(),
                    },
                })
                print(f"[DIAG] BROADCAST completado")
            except Exception as e:
                print(f"[DIAG] ERROR al retransmitir telemetría: {e}")

            # Procesar con FSM
            try:
                print(f"[DIAG] Llamando fsm.procesar_paquete()...")
                resultado = fsm.procesar_paquete(muestras)
                print(f"[DIAG] FSM retornó: {resultado is not None}")
                if resultado is not None:
                    # Transformar las llaves del ws_data de la FSM (x,y,z) -> (ax,ay,az)
                    # para alinear con lo que espera el frontend (Chart.js)
                    ws_data = resultado.get("ws_data")
                    if ws_data and isinstance(ws_data, dict):
                        ws_data_transformado = {
                            "ax": ws_data.get("x"),
                            "ay": ws_data.get("y"),
                            "az": ws_data.get("z"),
                            "timestamp_ms": ws_data.get("timestamp_ms"),
                            "gx": ws_data.get("gx"),
                            "gy": ws_data.get("gy"),
                            "gz": ws_data.get("gz"),
                            "win": ws_data.get("win"),
                            "latencia_ms": ws_data.get("latencia_ms"),
                            "angulo_final_deg": ws_data.get("angulo_final_deg"),
                            "temblor": ws_data.get("temblor"),
                        }
                        resultado["ws_data"] = ws_data_transformado
                        print(f"[DIAG] ws_data transformado: win={ws_data_transformado.get('win')} latencia={ws_data_transformado.get('latencia_ms')} angulo={ws_data_transformado.get('angulo_final_deg')}")
                    slot["_ultimo_resultado"] = resultado
            except Exception as e:
                print(f"[DIAG] ERROR en FSM al procesar paquete: {e}")

        except Exception as e:
            print(f"[DIAG] ERROR general en procesar_telemetria: {e}")
            import traceback
            print(traceback.format_exc())
        print(f"[DIAG] procesar_telemetria FIN sesion_id={sesion_id}")

    # ── Finalizar sesión ─────────────────────────────────────────────────

    async def _finalizar_sesion(self, sesion_id: str):
        db = get_supabase()
        db.table("sesiones").update({
            "estado": "completada",
            "finalizada_at": "now()",
        }).eq("id", sesion_id).execute()

        # Calcular resumen final
        res = (
            db.table("resultados_rondas")
            .select("latencia_ms, angulo_final_deg, tasa_temblor, resultado")
            .eq("sesion_id", sesion_id)
            .execute()
        )
        rondas = res.data or []
        aciertos = sum(1 for r in rondas if r["resultado"] == "acierto")
        latencias = [r["latencia_ms"] for r in rondas if r["latencia_ms"]]
        lat_prom  = round(sum(latencias) / len(latencias)) if latencias else None

        await self.broadcast(sesion_id, {
            "tipo": "sesion_fin",
            "payload": {
                "sesion_id":       sesion_id,
                "total_rondas":    len(rondas),
                "aciertos":        aciertos,
                "errores":         len(rondas) - aciertos,
                "latencia_prom_ms": lat_prom,
            },
        })

        # Limpiar slot en memoria
        self.sesiones_activas.pop(sesion_id, None)

    async def abortar_sesion(self, sesion_id: str):
        db = get_supabase()
        db.table("sesiones").update({
            "estado": "abortada",
            "finalizada_at": "now()",
        }).eq("id", sesion_id).execute()
        await self.broadcast(sesion_id, {
            "tipo": "sesion_fin",
            "payload": {"sesion_id": sesion_id, "abortada": True},
        })
        self.sesiones_activas.pop(sesion_id, None)

    # ── Guardar resultado en Supabase ────────────────────────────────────

    async def _guardar_resultado(
        self, sesion_id: str, fsm: SesionFSM,
        estimulo: dict, resultado: dict, numero_ronda: int
    ):
        db = get_supabase()
        db.table("resultados_rondas").insert({
            "sesion_id":          sesion_id,
            "numero_ronda":       numero_ronda,
            "tipo_estimulo":      estimulo["tipo"],
            "direccion_objetivo": estimulo.get("direccion"),
            "resultado":          resultado["resultado"],
            "latencia_ms":        resultado.get("latencia_ms"),
            "angulo_final_deg":   resultado.get("angulo_final_deg"),
            "tasa_temblor":       resultado.get("tasa_temblor"),
        }).execute()

    # ── Broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, sesion_id: str, mensaje: dict):
        """Envía el mensaje a terapeuta y paciente de la sesión."""
        slot = self.sesiones_activas.get(sesion_id)
        if not slot:
            return
        texto = json.dumps(mensaje, ensure_ascii=False, default=str)
        for rol in ("terapeuta", "paciente"):
            ws: Optional[WebSocket] = slot.get(rol)
            if ws:
                try:
                    await ws.send_text(texto)
                except Exception:
                    slot[rol] = None

    @staticmethod
    async def _enviar(ws: WebSocket, mensaje: dict):
        try:
            await ws.send_text(json.dumps(mensaje, ensure_ascii=False))
        except Exception:
            pass


# Singleton global
manager = ConnectionManager()

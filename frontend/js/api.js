/**
 * js/api.js
 * Cliente HTTP para el backend FastAPI y gestor de WebSocket.
 * Centraliza todas las llamadas de red del frontend.
 */

// ── Configuración ─────────────────────────────────────────────────────────────
// En producción, cambia por tu URL de Railway/Fly.io
const API_BASE = window.ENV_API_BASE || "http://localhost:8000/api/v1";
const WS_BASE  = API_BASE.replace(/^http/, "ws").replace("/api/v1", "");

// ── Estado global de sesión ───────────────────────────────────────────────────
const Auth = {
  token:      localStorage.getItem("acv_token"),
  rol:        localStorage.getItem("acv_rol"),
  nombres:    localStorage.getItem("acv_nombres"),
  pacienteId: localStorage.getItem("acv_paciente_id"),

  guardar(token, rol, nombres, pacienteId = null) {
    this.token      = token;
    this.rol        = rol;
    this.nombres    = nombres;
    this.pacienteId = pacienteId;
    localStorage.setItem("acv_token",      token      || "");
    localStorage.setItem("acv_rol",        rol        || "");
    localStorage.setItem("acv_nombres",    nombres    || "");
    localStorage.setItem("acv_paciente_id", pacienteId || "");
  },

  limpiar() {
    this.token = this.rol = this.nombres = this.pacienteId = null;
    ["acv_token","acv_rol","acv_nombres","acv_paciente_id"].forEach(k => localStorage.removeItem(k));
  },

  estaAutenticado: () => !!localStorage.getItem("acv_token"),
};

// ── Fetch helper ─────────────────────────────────────────────────────────────
async function apiFetch(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && Auth.token) headers["Authorization"] = `Bearer ${Auth.token}`;

  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 401) {
    Auth.limpiar();
    window.location.href = "/";
    return;
  }

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`);
  return data;
}

// ── Auth ─────────────────────────────────────────────────────────────────────
const ApiAuth = {
  async loginTerapeuta(email, password) {
    const params = new URLSearchParams({ email, password });
    const resp = await fetch(`${API_BASE}/auth/login?${params}`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Login fallido");
    return data;
  },

  async loginPaciente(pin) {
    return apiFetch("/auth/login/paciente", { method: "POST", body: { pin }, auth: false });
  },

  async registroTerapeuta(datos) {
    return apiFetch("/auth/registro/terapeuta", { method: "POST", body: datos, auth: false });
  },
};

// ── Pacientes ─────────────────────────────────────────────────────────────────
const ApiPacientes = {
  listar:   ()       => apiFetch("/pacientes"),
  obtener:  (id)     => apiFetch(`/pacientes/${id}`),
  crear:    (datos)  => apiFetch("/pacientes",    { method: "POST", body: datos }),
  eliminar: (id)     => apiFetch(`/pacientes/${id}`, { method: "DELETE" }),
  historial:(id)     => apiFetch(`/pacientes/${id}/historial`),
};

// ── Actividades ───────────────────────────────────────────────────────────────
const ApiActividades = {
  listar: ()      => apiFetch("/actividades"),
  crear:  (datos) => apiFetch("/actividades", { method: "POST", body: datos }),
};

// ── Sesiones ─────────────────────────────────────────────────────────────────
const ApiSesiones = {
  crear:       (datos)     => apiFetch("/sesiones",               { method: "POST", body: datos }),
  iniciar:     (sesionId)  => apiFetch(`/sesiones/${sesionId}/iniciar`, { method: "POST" }),
  abortar:     (sesionId)  => apiFetch(`/sesiones/${sesionId}/abortar`, { method: "POST" }),
  resultados:  (sesionId)  => apiFetch(`/sesiones/${sesionId}/resultados`),
};

// ── WebSocket Manager ─────────────────────────────────────────────────────────
class WsManager {
  constructor() {
    this.ws       = null;
    this.handlers = {};
    this._reconectarTimer = null;
    this._intentos = 0;
  }

  /**
   * Conecta el WebSocket como terapeuta de una sesión.
   * @param {string} sesionId
   */
  conectarTerapeuta(sesionId) {
    const url = `${WS_BASE}/ws/terapeuta/${sesionId}`;
    this._conectar(url);
  }

  /**
   * Conecta el WebSocket como paciente (sala de espera).
   * @param {string} pacienteId
   */
  conectarPaciente(pacienteId) {
    const url = `${WS_BASE}/ws/paciente/${pacienteId}`;
    this._conectar(url);
  }

  _conectar(url) {
    if (this.ws) this.ws.close();
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log("[WS] Conectado:", url);
      this._intentos = 0;
      this._emit("open", {});
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this._emit(msg.tipo, msg.payload);
        this._emit("*", msg); // wildcard
      } catch (e) {
        console.error("[WS] Parse error:", e);
      }
    };

    this.ws.onerror = (err) => {
      console.error("[WS] Error:", err);
      this._emit("error", err);
    };

    this.ws.onclose = () => {
      console.warn("[WS] Desconectado. Intentando reconectar...");
      this._emit("close", {});
      this._intentos++;
      const delay = Math.min(1000 * this._intentos, 8000);
      this._reconectarTimer = setTimeout(() => this._conectar(url), delay);
    };
  }

  on(tipo, handler) {
    if (!this.handlers[tipo]) this.handlers[tipo] = [];
    this.handlers[tipo].push(handler);
    return this; // chainable
  }

  off(tipo, handler) {
    if (!this.handlers[tipo]) return;
    this.handlers[tipo] = this.handlers[tipo].filter(h => h !== handler);
  }

  _emit(tipo, payload) {
    (this.handlers[tipo] || []).forEach(h => h(payload));
  }

  desconectar() {
    clearTimeout(this._reconectarTimer);
    if (this.ws) { this.ws.onclose = null; this.ws.close(); this.ws = null; }
  }
}

const wsManager = new WsManager();

// ── Toast helper ─────────────────────────────────────────────────────────────
function showToast(mensaje, tipo = "info", duracion = 3500) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast ${tipo}`;

  const iconos = { success: "✅", error: "❌", info: "ℹ️", warning: "⚠️" };
  toast.innerHTML = `<span>${iconos[tipo] || ""}</span><span>${mensaje}</span>`;
  container.appendChild(toast);

  setTimeout(() => { toast.remove(); }, duracion);
}

// ── Modal helper ─────────────────────────────────────────────────────────────
function openModal(id)  { document.getElementById(id)?.classList.add("open"); }
function closeModal(id) { document.getElementById(id)?.classList.remove("open"); }

// ── Formato de números ────────────────────────────────────────────────────────
function fmtMs(ms)    { return ms != null ? `${ms} ms`    : "—"; }
function fmtDeg(deg)  { return deg != null ? `${Number(deg).toFixed(1)}°` : "—"; }
function fmtTemblor(v) { return v != null ? Number(v).toFixed(5) : "—"; }

function resultadoBadge(r) {
  const map = {
    acierto: "badge-success",
    error:   "badge-error",
    timeout: "badge-warning",
  };
  const labels = { acierto: "Acierto", error: "Error", timeout: "Timeout" };
  return `<span class="badge ${map[r] || "badge-pending"}">${labels[r] || r}</span>`;
}

function nivelBadge(n) {
  const map = { facil: "badge-success", medio: "badge-warning", dificil: "badge-error" };
  return `<span class="badge ${map[n] || "badge-pending"}">${n}</span>`;
}

// Exportar para uso en otros scripts
window.ACV = { Auth, ApiAuth, ApiPacientes, ApiActividades, ApiSesiones, wsManager,
               showToast, openModal, closeModal, fmtMs, fmtDeg, fmtTemblor,
               resultadoBadge, nivelBadge };

/**
 * js/paciente.js
 * Controlador de la vista del PACIENTE.
 * Gestiona sala de espera, recepción de estímulos GO/NO-GO y feedback audiovisual.
 */

document.addEventListener("DOMContentLoaded", () => {
  const { Auth, 
    Manager, showToast } = window.ACV;
  const AudioEngine = window.AudioEngine;

  // ── Referencias DOM ────────────────────────────────────────────────────
  const pantallaEspera   = document.getElementById("pantalla-espera");
  const pantallaEstimulo = document.getElementById("pantalla-estimulo");
  const pantallaFin      = document.getElementById("pantalla-fin");
  const nombreBienvenida = document.getElementById("bienvenida-nombre");

  const estimuloContent  = document.getElementById("estimulo-content");
  const contadorRonda    = document.getElementById("contador-ronda");
  const resultadoOverlay = document.getElementById("resultado-overlay");

  // ── Cargar nombre del paciente ─────────────────────────────────────────
  const nombres = Auth.nombres || localStorage.getItem("acv_nombres") || "Paciente";
  const pacienteId = Auth.pacienteId || localStorage.getItem("acv_paciente_id");

  if (nombreBienvenida) nombreBienvenida.textContent = nombres;

  if (!pacienteId) {
    window.location.href = "/index.html";
    return;
  }

  // Desbloquear Web Audio al primer toque
  document.body.addEventListener("click", () => AudioEngine.desbloquear(), { once: true });
  document.body.addEventListener("touchstart", () => AudioEngine.desbloquear(), { once: true });

  // ── Conectar WebSocket ─────────────────────────────────────────────────
  wsManager.conectarPaciente(pacienteId);

  // ── Handlers WebSocket ─────────────────────────────────────────────────
  wsManager

    .on("open", () => {
      console.log("[Paciente] WS conectado, en sala de espera.");
      mostrarPantalla("espera");
      AudioEngine.bienvenida();
    })

    .on("ping", (payload) => {
      console.log("[Paciente] Ping:", payload.mensaje);
    })

    .on("sesion_inicio", (payload) => {
      mostrarPantalla("espera");
      document.getElementById("espera-msg-secundario").textContent =
        `Sesión iniciada. Prepárate — ${payload.num_rondas} rondas.`;
      AudioEngine.bienvenida();
    })

    .on("estimulo", (payload) => {
      mostrarEstimulo(payload);
    })

    .on("resultado_ronda", (payload) => {
      mostrarResultadoRonda(payload);
    })

    .on("sesion_fin", (payload) => {
      mostrarFin(payload);
      // Auto-redirect to index.html after 5 seconds showing final results
      setTimeout(() => {
        Auth.limpiar();
        window.location.href = "/index.html";
      }, 5000);
    })

    .on("close", () => {
      document.getElementById("conexion-status").textContent = "⚡ Reconectando...";
    })

    .on("error", () => {
      document.getElementById("conexion-status").textContent = "❌ Error de conexión";
    });

  // ── Mostrar pantallas ──────────────────────────────────────────────────
  function mostrarPantalla(cual) {
    pantallaEspera?.classList.add("hidden");
    pantallaEstimulo?.classList.add("hidden");
    pantallaFin?.classList.add("hidden");
    if (cual === "espera")   pantallaEspera?.classList.remove("hidden");
    if (cual === "estimulo") pantallaEstimulo?.classList.remove("hidden");
    if (cual === "fin")      pantallaFin?.classList.remove("hidden");
  }

  // ── Renderizar estímulo ────────────────────────────────────────────────
  const FLECHAS = {
    arriba:    "⬆",
    abajo:     "⬇",
    izquierda: "⬅",
    derecha:   "➡",
    circulo:   "🔄",
  };

  function mostrarEstimulo(payload) {
    mostrarPantalla("estimulo");
    limpiarResultadoOverlay();

    if (payload.estimulo === "GO") {
      const flecha = FLECHAS[payload.direccion] || "▶";
      pantallaEstimulo.className = "estimulo-screen go";
      estimuloContent.innerHTML  = `
        <div class="go-arrow">${flecha}</div>
        <div class="estimulo-label go-label">¡MUEVE la mano!</div>
        <div class="estimulo-label go-label" style="font-size:1rem;opacity:.7">${(payload.direccion || "").toUpperCase()}</div>
      `;
      AudioEngine.go();
    } else {
      pantallaEstimulo.className = "estimulo-screen nogo";
      estimuloContent.innerHTML  = `
        <div class="nogo-cross">✖</div>
        <div class="estimulo-label nogo-label">¡NO TE MUEVAS!</div>
      `;
      AudioEngine.nogo();
    }

    if (contadorRonda) {
      contadorRonda.textContent = `Ronda ${payload.ronda} de ${payload.total}`;
    }

    // Timer visual (barra de progreso)
    iniciarTimerVisual(payload.tmax_seg * 1000);
  }

  // ── Timer barra de progreso ────────────────────────────────────────────
  let _timerInterval = null;

  function iniciarTimerVisual(duracionMs) {
    clearInterval(_timerInterval);
    const barra = document.getElementById("timer-barra");
    if (!barra) return;
    const inicio = Date.now();
    barra.style.width = "100%";
    barra.style.transition = "none";

    _timerInterval = setInterval(() => {
      const transcurrido = Date.now() - inicio;
      const pct = Math.max(0, 100 - (transcurrido / duracionMs) * 100);
      barra.style.transition = "width 0.1s linear";
      barra.style.width = pct + "%";
      if (pct <= 0) clearInterval(_timerInterval);
    }, 100);
  }

  // ── Feedback de resultado ronda ────────────────────────────────────────
  function mostrarResultadoRonda(payload) {
    clearInterval(_timerInterval);

    // Feedback audiovisual
    if (payload.resultado === "acierto") {
      AudioEngine.acierto();
      pantallaEstimulo.className = "estimulo-screen go";
      mostrarOverlayResultado("✔", "¡Correcto!", "resultado-acierto");
    } else if (payload.resultado === "error") {
      AudioEngine.error();
      pantallaEstimulo.className = "estimulo-screen nogo";
      mostrarOverlayResultado("✖", "Error", "resultado-error");
    } else {
      AudioEngine.timeout();
      pantallaEstimulo.className = "estimulo-screen descanso";
      mostrarOverlayResultado("⏱", "Tiempo agotado", "");
    }

    // Volver a pantalla de espera entre rondas tras 1.5s
    setTimeout(() => {
      mostrarPantalla("espera");
      pantallaEstimulo.className = "estimulo-screen espera";
      document.getElementById("espera-msg-secundario").textContent = "Preparándose para la siguiente ronda...";
    }, 1800);
  }

  function mostrarOverlayResultado(icono, texto, clase) {
    if (!resultadoOverlay) return;
    resultadoOverlay.innerHTML = `
      <div class="resultado-overlay ${clase}">
        <div class="resultado-icon">${icono}</div>
        <div class="resultado-text">${texto}</div>
      </div>
    `;
  }

  function limpiarResultadoOverlay() {
    if (resultadoOverlay) resultadoOverlay.innerHTML = "";
  }

  // ── Pantalla de fin de sesión ──────────────────────────────────────────
  function mostrarFin(payload) {
    mostrarPantalla("fin");
    AudioEngine.finSesion();

    const total    = payload.total_rondas   || 0;
    const aciertos = payload.aciertos        || 0;
    const errores  = payload.errores != null ? payload.errores : (total - aciertos);
    const pct      = total > 0 ? Math.round((aciertos / total) * 100) : 0;

    document.getElementById("fin-aciertos").textContent = aciertos;
    document.getElementById("fin-errores").textContent  = errores;
    document.getElementById("fin-pct").textContent      = pct + "%";
    document.getElementById("fin-latencia").textContent =
      payload.latencia_prom_ms ? payload.latencia_prom_ms + " ms" : "—";
  }

  // ── Botón "Volver al inicio" en pantalla fin ───────────────────────────
  document.getElementById("btn-volver-inicio")?.addEventListener("click", () => {
    Auth.limpiar();
    window.location.href = "/index.html";
  });
});

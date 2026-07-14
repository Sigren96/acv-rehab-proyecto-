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
  const resultadoStrip   = document.getElementById("resultado-strip");

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
      // Flujo manual: el paciente debe hacer clic en "Terminar y Volver al Inicio"
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
    console.log("Frontend mostró GO", Date.now());
    mostrarPantalla("estimulo");
    limpiarResultadoOverlay();

    if (payload.estimulo === "GO") {
      const flecha = FLECHAS[payload.direccion] || "▶";
      pantallaEstimulo.className = "estimulo-screen go";
      estimuloContent.innerHTML  = `
        <div id="avatar-indicador-container">
          <svg viewBox="0 0 200 200" width="180" height="180" role="img"
               aria-label="Personaje indicando direccion del movimiento"
               stroke-linejoin="round">

            <g id="avatar-piernas">
              <g transform="rotate(15, 95, 145)">
                <rect x="86" y="110" width="17" height="35" fill="#2C2C2A" stroke="#000" stroke-width="2"></rect>
                <rect x="86" y="145" width="17" height="25" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>
                <ellipse cx="94" cy="172" rx="12" ry="6" fill="#185FA5" stroke="#000" stroke-width="2"></ellipse>
              </g>
              <g transform="rotate(-15, 105, 145)">
                <rect x="97" y="110" width="17" height="35" fill="#2C2C2A" stroke="#000" stroke-width="2"></rect>
                <rect x="97" y="145" width="17" height="25" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>
                <ellipse cx="105" cy="172" rx="12" ry="6" fill="#185FA5" stroke="#000" stroke-width="2"></ellipse>
              </g>
            </g>

            <g id="avatar-brazo-izquierdo" style="transform-origin:80px 78px; transform:rotate(10deg);">
              <rect x="72" y="78" width="16" height="8" fill="#378ADD" stroke="#000" stroke-width="2"></rect>
              <rect x="72" y="86" width="16" height="6" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>
              <rect x="74" y="92" width="12" height="28" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>
              <rect x="74" y="120" width="12" height="14" rx="5" ry="5" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>
            </g>

            <path id="avatar-torso" d="M84,68 Q78,68 78,76 L83,120 L117,120 L122,76 Q122,68 116,68 Z" fill="#378ADD" stroke="#000" stroke-width="2"></path>

            <path id="avatar-short" d="M80,120 L120,120 L120,140 Q120,146 113,146 L104,146 L100,130 L96,146 L87,146 Q80,146 80,140 Z" fill="#2C2C2A" stroke="#000" stroke-width="2"></path>

            <rect id="avatar-cuello" x="92" y="60" width="16" height="10" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>

            <g id="avatar-cabeza">
              <ellipse cx="100" cy="40" rx="20" ry="25" fill="#F2CFA6" stroke="#000" stroke-width="2"></ellipse>
              <path d="M78,46 Q75,10 100,7 Q125,10 122,46 Q122,26 108,20 Q100,18 92,20 Q78,26 78,46 Z" fill="#6B4423" stroke="#000" stroke-width="2"></path>
              <circle cx="92" cy="38" r="2" fill="#000"></circle>
              <circle cx="108" cy="38" r="2" fill="#000"></circle>
              <path d="M99,42 Q102,46 99,48" fill="none" stroke="#000" stroke-width="1.3"></path>
              <path d="M92,52 Q100,56 108,52" fill="none" stroke="#000" stroke-width="1.5"></path>
            </g>

            <g id="avatar-brazo-derecho" style="transform-origin:120px 78px; transform:rotate(-90deg); transition: transform 0.4s ease;">
              <rect x="112" y="78" width="16" height="8" fill="#378ADD" stroke="#000" stroke-width="2"></rect>
              <rect x="112" y="86" width="16" height="6" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>
              <rect x="114" y="92" width="12" height="28" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>
              <rect x="114" y="114" width="12" height="6" rx="3" fill="#fff" stroke="#000" stroke-width="1.5"></rect>
              <rect x="114" y="120" width="12" height="14" rx="5" ry="5" fill="#F2CFA6" stroke="#000" stroke-width="2"></rect>
            </g>
          </svg>
        </div>
        <div class="go-arrow">${flecha}</div>
        <div class="estimulo-label go-label">¡MUEVE la mano!</div>
        <div class="estimulo-label go-label" style="font-size:1rem;opacity:.7">${(payload.direccion || "").toUpperCase()}</div>
      `;
      actualizarAvatarDireccion(payload.direccion, payload.patron_validacion);
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
      mostrarOverlayResultado("⏱", "Tiempo agotado", "resultado-timeout");
    }

    // Volver a pantalla de espera entre rondas tras 1.5s
    setTimeout(() => {
      // Solo volver a espera si la sesión NO ha terminado
      const finVisible = pantallaFin && !pantallaFin.classList.contains("hidden");
      if (!finVisible) {
        mostrarPantalla("espera");
        pantallaEstimulo.className = "estimulo-screen espera";
        document.getElementById("espera-msg-secundario").textContent = "Preparándose para la siguiente ronda...";
      }
    }, 1800);
  }

  function mostrarOverlayResultado(icono, texto, clase) {
    if (!resultadoStrip) return;
    resultadoStrip.innerHTML = `
      <div class="resultado-strip-banner ${clase}">
        <span class="resultado-strip-icon">${icono}</span>
        <span class="resultado-strip-text">${texto}</span>
      </div>
    `;
  }

  function limpiarResultadoOverlay() {
    if (resultadoStrip) resultadoStrip.innerHTML = "";
  }

  function actualizarAvatarDireccion(direccion, patronValidacion) {
    const brazo = document.getElementById("avatar-brazo-derecho");
    if (!brazo) return;

    brazo.style.animation = "none";

    if (patronValidacion === "rotacion") {
      brazo.style.setProperty("--avatar-rotation", "-90deg");
      brazo.style.animation = "avatar-girar 1.2s linear infinite";
      return;
    }

    const angulos = {
      arriba:    180,
      abajo:     0,
      izquierda: 90,
      derecha:   -90,
    };

    const angulo = angulos[direccion];
    if (angulo !== undefined) {
      brazo.style.setProperty("--avatar-rotation", `${angulo}deg`);
      brazo.style.animation = "avatar-vaiven 1.4s ease-in-out infinite";
    }
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

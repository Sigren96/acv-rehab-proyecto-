/**
 * js/app.js
 * Controlador principal del dashboard del TERAPEUTA.
 * Maneja navegación SPA, vistas, formularios y WebSocket de monitoreo.
 */

document.addEventListener("DOMContentLoaded", () => {
  const { Auth, ApiAuth, ApiPacientes, ApiActividades, ApiSesiones,
          wsManager, showToast, openModal, closeModal,
          fmtMs, fmtDeg, fmtTemblor, resultadoBadge, nivelBadge } = window.ACV;

  // ── Guard: redirigir si no está autenticado ────────────────────────────
  if (!Auth.estaAutenticado() || Auth.rol !== "terapeuta") {
    window.location.href = "/index.html";
    return;
  }

  // ── Referencias DOM ────────────────────────────────────────────────────
  const sidebarEl     = document.getElementById("sidebar");
  const overlayEl     = document.getElementById("sidebar-overlay");
  const navItems      = document.querySelectorAll(".nav-item[data-view]");
  const views         = document.querySelectorAll(".view");
  const topbarTitle   = document.getElementById("topbar-title");
  const userNameEl    = document.getElementById("user-name");
  const userInitialEl = document.getElementById("user-initial");

  // ── Estado local ───────────────────────────────────────────────────────
  let sesionActivaId  = null;
  let chartXYZ        = null;
  let chartHistorial  = null;
  let bufferXYZ       = { x: [], y: [], z: [], labels: [] };
  const MAX_PUNTOS    = 60; // últimos 60 paquetes en el gráfico vivo

  // ── Inicialización ─────────────────────────────────────────────────────
  userNameEl.textContent    = Auth.nombres || "Terapeuta";
  userInitialEl.textContent = (Auth.nombres || "T")[0].toUpperCase();
  mostrarVista("pacientes");
  cargarPacientes();

  // ── Navegación SPA ─────────────────────────────────────────────────────
  navItems.forEach(btn => {
    btn.addEventListener("click", () => {
      const vista = btn.dataset.view;
      mostrarVista(vista);
      cerrarSidebarMovil();
    });
  });

  function mostrarVista(nombre) {
    views.forEach(v => v.classList.add("hidden"));
    navItems.forEach(b => b.classList.remove("active"));

    const vistaEl = document.getElementById(`view-${nombre}`);
    const navBtn  = document.querySelector(`.nav-item[data-view="${nombre}"]`);
    if (vistaEl) vistaEl.classList.remove("hidden");
    if (navBtn)  navBtn.classList.add("active");

    const titulos = {
      pacientes:      "Pacientes",
      sesiones:       "Nueva Sesión",
      monitoreo:      "Monitoreo en Tiempo Real",
      historial:      "Historial de Paciente",
      configuraciones:"Configuraciones",
      perfil:         "Perfil",
    };
    topbarTitle.textContent = titulos[nombre] || nombre;

    if (nombre === "sesiones")       cargarFormSesion();
    if (nombre === "configuraciones") cargarConfiguraciones();
    if (nombre === "historial")      cargarSelectorHistorial();
  }

  // ── Sidebar móvil ──────────────────────────────────────────────────────
  document.getElementById("hamburger")?.addEventListener("click", () => {
    sidebarEl.classList.toggle("open");
    overlayEl.classList.toggle("open");
  });
  overlayEl?.addEventListener("click", cerrarSidebarMovil);

  function cerrarSidebarMovil() {
    sidebarEl.classList.remove("open");
    overlayEl.classList.remove("open");
  }

  // ── Logout ─────────────────────────────────────────────────────────────
  document.getElementById("btn-logout")?.addEventListener("click", () => {
    Auth.limpiar();
    window.location.href = "/index.html";
  });

  // ════════════════════════════════════════════════════════════
  // VISTA: PACIENTES
  // ════════════════════════════════════════════════════════════

  async function cargarPacientes() {
    const tbody = document.getElementById("tabla-pacientes");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="6" class="text-center muted">Cargando...</td></tr>`;
    try {
      const pacientes = await ApiPacientes.listar();
      if (!pacientes || pacientes.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center muted">Sin pacientes registrados. Agrega uno.</td></tr>`;
        return;
      }
      tbody.innerHTML = pacientes.map(p => `
        <tr>
          <td><strong>${p.nombres} ${p.apellidos}</strong></td>
          <td>${p.diagnostico || "—"}</td>
          <td>${nivelBadge(p.nivel_movilidad)}</td>
          <td><code class="mono bold">${p.pin_acceso}</code></td>
          <td>${p.activo ? '<span class="badge badge-success">Activo</span>' : '<span class="badge badge-pending">Inactivo</span>'}</td>
          <td>
            <button class="btn btn-sm btn-outline" onclick="verHistorial('${p.id}','${p.nombres} ${p.apellidos}')">Historial</button>
            <button class="btn btn-sm btn-ghost" onclick="iniciarNuevaSesion('${p.id}')">Nueva sesión</button>
          </td>
        </tr>
      `).join("");
    } catch (e) {
      showToast(e.message, "error");
    }
  }

  // Formulario nuevo paciente
  document.getElementById("form-paciente")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
      const datos = {
        nombres:         document.getElementById("pac-nombres").value.trim(),
        apellidos:       document.getElementById("pac-apellidos").value.trim(),
        diagnostico:     document.getElementById("pac-diagnostico").value.trim(),
        nivel_movilidad: document.getElementById("pac-nivel").value,
        fecha_nacimiento:document.getElementById("pac-fecha").value || null,
      };
      const nuevo = await ApiPacientes.crear(datos);
      showToast(`Paciente registrado. PIN: ${nuevo.pin_acceso}`, "success", 6000);
      closeModal("modal-paciente");
      e.target.reset();
      cargarPacientes();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById("btn-nuevo-paciente")?.addEventListener("click", () => openModal("modal-paciente"));
  document.querySelectorAll(".modal-close").forEach(btn => {
    btn.addEventListener("click", () => closeModal(btn.closest(".modal-overlay").id));
  });

  // Exponer para uso inline en tabla
  window.verHistorial = (id, nombre) => {
    document.getElementById("historial-nombre").textContent = nombre;
    cargarHistorialPaciente(id);
    mostrarVista("historial");
  };

  window.iniciarNuevaSesion = (pacienteId) => {
    document.getElementById("sesion-paciente-id").value = pacienteId;
    mostrarVista("sesiones");
  };

  // ════════════════════════════════════════════════════════════
  // VISTA: NUEVA SESIÓN
  // ════════════════════════════════════════════════════════════

  async function cargarFormSesion() {
    // Cargar lista de pacientes en el select
    const sel = document.getElementById("sesion-paciente-id");
    if (!sel) return;
    try {
      const pacs = await ApiPacientes.listar();
      sel.innerHTML = `<option value="">— Selecciona paciente —</option>` +
        pacs.map(p => `<option value="${p.id}">${p.nombres} ${p.apellidos}</option>`).join("");
    } catch {}

    // Cargar actividades
    const selAct = document.getElementById("sesion-actividad");
    if (!selAct) return;
    try {
      const acts = await ApiActividades.listar();
      selAct.innerHTML = `<option value="">— Sin actividad específica —</option>` +
        acts.map(a => `<option value="${a.id}">${a.nombre} (${a.eje_movimiento} / ${a.patron_validacion})</option>`).join("");
    } catch {}
  }

  document.getElementById("form-sesion")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
      const datos = {
        paciente_id:         document.getElementById("sesion-paciente-id").value,
        actividad_id:        document.getElementById("sesion-actividad").value || null,
        nivel_dificultad:    document.getElementById("sesion-dificultad").value,
        num_rondas:          parseInt(document.getElementById("sesion-rondas").value),
        tiempo_descanso_seg: parseInt(document.getElementById("sesion-descanso").value),
        porcentaje_go:       parseInt(document.getElementById("sesion-go-pct").value),
      };

      if (!datos.paciente_id) { showToast("Selecciona un paciente.", "error"); return; }

      const sesion = await ApiSesiones.crear(datos);
      showToast("Sesión creada. Iniciando monitoreo...", "success");
      sesionActivaId = sesion.id;
      document.getElementById("sesion-id-display").textContent = sesion.id.slice(0, 8) + "...";
      document.getElementById("sesion-id-pico").value = sesion.id;
      
      // Obtener nombre del paciente del select
      const pacienteSelect = document.getElementById("sesion-paciente-id");
      const pacienteNombre = pacienteSelect.options[pacienteSelect.selectedIndex].text;
      
      mostrarVista("monitoreo");
      iniciarMonitoreo(sesion, pacienteNombre);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  });

  // Actividad personalizada: mostrar/ocultar campos extra
  document.getElementById("btn-nueva-actividad")?.addEventListener("click", () => openModal("modal-actividad"));

  document.getElementById("form-actividad")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const datos = {
        nombre:             document.getElementById("act-nombre").value.trim(),
        descripcion_clinica: document.getElementById("act-descripcion").value.trim(),
        eje_movimiento:     document.getElementById("act-eje").value,
        patron_validacion:  document.getElementById("act-patron").value,
      };
      await ApiActividades.crear(datos);
      showToast("Actividad guardada.", "success");
      closeModal("modal-actividad");
      cargarFormSesion();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // ════════════════════════════════════════════════════════════
  // VISTA: MONITOREO EN TIEMPO REAL
  // ════════════════════════════════════════════════════════════

  function iniciarMonitoreo(sesion, pacienteNombre) {
    inicializarChartXYZ();
    actualizarEstadoDispositivo("esperando");

    // Mostrar nombre del paciente en el header del monitoreo
    const headerMonitoreo = document.querySelector("#view-monitoreo h2");
    if (headerMonitoreo && pacienteNombre) {
      headerMonitoreo.textContent = `Monitoreo en Tiempo Real — ${pacienteNombre}`;
    }

    // Conectar WebSocket del terapeuta
    wsManager.conectarTerapeuta(sesion.id);

    wsManager
      .on("open", () => {
        actualizarEstadoDispositivo("conectado");
        showToast("Conectado al servidor. Presione 'Iniciar/Forzar Sesión' para comenzar.", "info");
      })

      .on("sesion_inicio", (payload) => {
        document.getElementById("monitor-rondas-total").textContent = payload.num_rondas;
        document.getElementById("monitor-dificultad").textContent   = payload.nivel_dificultad;
        showToast("¡Sesión activa! La Pico puede comenzar a enviar datos.", "success");
      })

      .on("telemetria", (payload) => {
        actualizarEstadoDispositivo("recibiendo");
        actualizarChartXYZ(payload.muestras);
      })

      .on("estimulo", (payload) => {
        const tipo = payload.estimulo;
        const dir  = payload.direccion || "";
        document.getElementById("monitor-estimulo-actual").innerHTML =
          tipo === "GO"
            ? `<span class="badge badge-success">GO ▶ ${dir.toUpperCase()}</span>`
            : `<span class="badge badge-error">NO-GO ✖</span>`;
        document.getElementById("monitor-ronda-actual").textContent = payload.ronda;
      })

      .on("resultado_ronda", (payload) => {
        agregarFilaRonda(payload);
        actualizarContadores(payload);
        document.getElementById("monitor-estimulo-actual").innerHTML =
          `<span class="badge badge-pending">Descanso...</span>`;
      })

      .on("sesion_fin", (payload) => {
        actualizarEstadoDispositivo("finalizada");
        wsManager.desconectar();
        mostrarResumenFinal(payload);
        showToast("Sesión finalizada correctamente.", "success");
        window.AudioEngine?.finSesion();
        // NO limpiar automáticamente: el terapeuta decide cuándo limpiar con el botón "Limpiar Dashboard"
      })

      .on("error", () => actualizarEstadoDispositivo("error"))
      .on("close",  () => actualizarEstadoDispositivo("desconectado"));
  }

  document.getElementById("btn-abortar")?.addEventListener("click", async () => {
    if (!sesionActivaId) return;
    if (!confirm("¿Abortar la sesión en curso?")) return;
    try {
      await ApiSesiones.abortar(sesionActivaId);
      wsManager.desconectar();
      showToast("Sesión abortada.", "warning");
      sesionActivaId = null;
      // Limpiar pantalla de monitoreo
      limpiarPantallaMonitoreo();
    } catch (e) {
      showToast(e.message, "error");
    }
  });

  // Handler para "Limpiar Dashboard" - limpieza manual por el terapeuta
  document.getElementById("btn-limpiar-dashboard")?.addEventListener("click", () => {
    limpiarPantallaMonitoreo();
    showToast("Dashboard limpiado. Listo para el siguiente paciente.", "info");
  });

  // Handler para "Iniciar/Forzar Sesión"
  document.getElementById("btn-iniciar-forzar")?.addEventListener("click", async () => {
    if (!sesionActivaId) return;
    try {
      await ApiSesiones.iniciar(sesionActivaId);
      showToast("Sesión iniciada/forzada. Esperando la Pico...", "info");
    } catch (e) {
      showToast(e.message, "error");
    }
  });

  function actualizarEstadoDispositivo(estado) {
    const el  = document.getElementById("device-status");
    const dot = document.getElementById("device-dot");
    if (!el) return;
    const cfg = {
      esperando:    { dot: "amarillo", texto: "Esperando dispositivo" },
      conectado:    { dot: "verde",    texto: "Conectado" },
      recibiendo:   { dot: "verde",    texto: "Recibiendo datos" },
      desconectado: { dot: "rojo",     texto: "Desconectado" },
      error:        { dot: "rojo",     texto: "Error de conexión" },
      finalizada:   { dot: "amarillo", texto: "Sesión finalizada" },
    }[estado] || { dot: "amarillo", texto: estado };

    dot.className = `dot ${cfg.dot}`;
    el.querySelector(".device-text").textContent = cfg.texto;
  }

  // ── Chart.js — Gráfico XYZ en vivo ────────────────────────────────────
  function inicializarChartXYZ() {
    const canvas = document.getElementById("chart-xyz");
    if (!canvas) return;
    if (chartXYZ) { chartXYZ.destroy(); chartXYZ = null; }
    bufferXYZ = { x: [], y: [], z: [], labels: [] };

    chartXYZ = new Chart(canvas, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: "Eje X (G)", data: [], borderColor: "#1A56DB", backgroundColor: "rgba(26,86,219,.08)", borderWidth: 2, tension: 0.3, pointRadius: 0 },
          { label: "Eje Y (G)", data: [], borderColor: "#10B981", backgroundColor: "rgba(16,185,129,.08)", borderWidth: 2, tension: 0.3, pointRadius: 0 },
          { label: "Eje Z (G)", data: [], borderColor: "#F59E0B", backgroundColor: "rgba(245,158,11,.08)",  borderWidth: 2, tension: 0.3, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { position: "top", labels: { font: { size: 11 }, boxWidth: 12 } } },
        scales: {
          x: { display: false },
          y: {
            min: -2, max: 2,
            grid: { color: "rgba(0,0,0,.05)" },
            ticks: { font: { size: 10 }, callback: v => v.toFixed(1) + " G" },
          },
        },
      },
    });
  }

  function actualizarChartXYZ(muestras) {
    if (!chartXYZ || !muestras) return;
    muestras.forEach((m, i) => {
      bufferXYZ.x.push(m.ax);
      bufferXYZ.y.push(m.ay);
      bufferXYZ.z.push(m.az);
      bufferXYZ.labels.push("");
    });

    // Mantener solo los últimos MAX_PUNTOS
    ["x","y","z","labels"].forEach(k => {
      if (bufferXYZ[k].length > MAX_PUNTOS) bufferXYZ[k] = bufferXYZ[k].slice(-MAX_PUNTOS);
    });

    chartXYZ.data.labels            = bufferXYZ.labels;
    chartXYZ.data.datasets[0].data  = bufferXYZ.x;
    chartXYZ.data.datasets[1].data  = bufferXYZ.y;
    chartXYZ.data.datasets[2].data  = bufferXYZ.z;
    chartXYZ.update("none");
  }

  // ── Tabla de rondas ────────────────────────────────────────────────────
  let contAciertos = 0, contErrores = 0;

  function agregarFilaRonda(p) {
    const tbody = document.getElementById("tabla-rondas");
    if (!tbody) return;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="mono">${p.ronda}</td>
      <td><span class="badge ${p.estimulo === 'GO' ? 'badge-success' : 'badge-error'}">${p.estimulo}</span></td>
      <td>${p.direccion || "—"}</td>
      <td>${resultadoBadge(p.resultado)}</td>
      <td class="mono">${fmtMs(p.latencia_ms)}</td>
      <td class="mono">${fmtDeg(p.angulo_deg)}</td>
      <td class="mono">${fmtTemblor(p.temblor)}</td>
    `;
    tbody.prepend(tr);
  }

  function actualizarContadores(p) {
    if (p.resultado === "acierto") contAciertos++;
    else contErrores++;
    document.getElementById("monitor-aciertos").textContent = contAciertos;
    document.getElementById("monitor-errores").textContent  = contErrores;
    if (p.latencia_ms) document.getElementById("monitor-latencia").textContent = fmtMs(p.latencia_ms);
  }

  function mostrarResumenFinal(p) {
    const el = document.getElementById("resumen-final");
    if (!el) return;
    el.classList.remove("hidden");
    el.innerHTML = `
      <div class="card mt-4">
        <div class="card-header"><span class="card-title">🏁 Sesión Completada</span></div>
        <div class="stats-grid">
          <div class="stat-card verde"><div class="stat-label">Aciertos</div><div class="stat-value">${p.aciertos}</div></div>
          <div class="stat-card rojo"><div class="stat-label">Errores</div><div class="stat-value">${p.errores ?? (p.total_rondas - p.aciertos)}</div></div>
          <div class="stat-card azul"><div class="stat-label">Latencia prom.</div><div class="stat-value">${p.latencia_prom_ms ?? "—"}<span class="stat-unit"> ms</span></div></div>
        </div>
        <div class="flex gap-2 mt-4">
          <button class="btn btn-primary" onclick="window.ACV.showToast('Generando PDF...','info'); window.generarPDF()">⬇ Descargar PDF</button>
          <button class="btn btn-ghost" onclick="mostrarVista('pacientes')">Volver a Pacientes</button>
        </div>
      </div>
    `;
  }

  // ── Limpiar pantalla de monitoreo ──────────────────────────────────────
  function limpiarPantallaMonitoreo() {
    // Resetear contadores
    contAciertos = 0;
    contErrores = 0;
    document.getElementById("monitor-aciertos").textContent = "0";
    document.getElementById("monitor-errores").textContent = "0";
    document.getElementById("monitor-ronda-actual").textContent = "0/—";
    document.getElementById("monitor-rondas-total").textContent = "—";
    document.getElementById("monitor-dificultad").textContent = "—";
    document.getElementById("monitor-latencia").textContent = "— ms";

    // Resetear estímulo activo
    document.getElementById("monitor-estimulo-actual").innerHTML =
      `<span class="badge badge-pending">ESPERANDO INICIO...</span>`;

    // Limpiar tabla de historial de rondas
    const tbody = document.getElementById("tabla-rondas");
    if (tbody) tbody.innerHTML = "";

    // Limpiar nombre del paciente en el header
    const headerMonitoreo = document.querySelector("#view-monitoreo h2");
    if (headerMonitoreo) {
      headerMonitoreo.textContent = "Monitoreo en Tiempo Real";
    }

    // Ocultar resumen final
    const resumenFinal = document.getElementById("resumen-final");
    if (resumenFinal) resumenFinal.classList.add("hidden");

    // Resetear gráfico XYZ
    if (chartXYZ) {
      chartXYZ.destroy();
      chartXYZ = null;
    }
    inicializarChartXYZ();

    // Resetear estado del dispositivo
    actualizarEstadoDispositivo("esperando");
  }

  // ════════════════════════════════════════════════════════════
  // VISTA: HISTORIAL
  // ════════════════════════════════════════════════════════════

  async function cargarSelectorHistorial() {
    const sel = document.getElementById("historial-paciente-sel");
    if (!sel) return;
    const pacs = await ApiPacientes.listar().catch(() => []);
    sel.innerHTML = `<option value="">— Selecciona paciente —</option>` +
      pacs.map(p => `<option value="${p.id}">${p.nombres} ${p.apellidos}</option>`).join("");
  }

  async function cargarHistorialPaciente(pacienteId) {
    const tbody = document.getElementById("tabla-historial");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="7" class="text-center muted">Cargando...</td></tr>`;
    try {
      const sesiones = await ApiPacientes.historial(pacienteId);
      if (!sesiones.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center muted">Sin sesiones registradas.</td></tr>`;
        renderHistChart([]);
        return;
      }
      tbody.innerHTML = sesiones.map(s => `
        <tr>
          <td class="mono">${new Date(s.iniciada_at).toLocaleDateString("es-PE")}</td>
          <td>${nivelBadge(s.nivel_dificultad)}</td>
          <td>${s.rondas_ejecutadas} / ${s.num_rondas ?? "?"}</td>
          <td><span class="badge badge-success">${s.aciertos}</span></td>
          <td><span class="badge badge-error">${s.errores}</span></td>
          <td class="mono">${s.latencia_promedio_ms ?? "—"} ms</td>
          <td class="mono">${s.angulo_promedio_deg != null ? Number(s.angulo_promedio_deg).toFixed(1) + "°" : "—"}</td>
        </tr>
      `).join("");
      renderHistChart(sesiones);
    } catch (e) {
      showToast(e.message, "error");
    }
  }

  document.getElementById("historial-paciente-sel")?.addEventListener("change", (e) => {
    if (e.target.value) cargarHistorialPaciente(e.target.value);
  });

  function renderHistChart(sesiones) {
    const canvas = document.getElementById("chart-historial");
    if (!canvas) return;
    if (chartHistorial) { chartHistorial.destroy(); chartHistorial = null; }
    if (!sesiones.length) return;

    const labels = sesiones.map(s => new Date(s.iniciada_at).toLocaleDateString("es-PE")).reverse();
    const latencias = sesiones.map(s => s.latencia_promedio_ms).reverse();
    const aciertos  = sesiones.map(s => s.aciertos).reverse();

    chartHistorial = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Latencia promedio (ms)",
            data: latencias,
            borderColor: "#1A56DB",
            backgroundColor: "rgba(26,86,219,.1)",
            borderWidth: 2,
            tension: 0.3,
            yAxisID: "y",
          },
          {
            label: "Aciertos",
            data: aciertos,
            borderColor: "#10B981",
            backgroundColor: "rgba(16,185,129,.1)",
            borderWidth: 2,
            tension: 0.3,
            yAxisID: "y2",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "top", labels: { font: { size: 11 }, boxWidth: 12 } } },
        scales: {
          y:  { position: "left",  title: { display: true, text: "ms" } },
          y2: { position: "right", title: { display: true, text: "Aciertos" }, grid: { drawOnChartArea: false } },
        },
      },
    });
  }

  // ════════════════════════════════════════════════════════════
  // GENERACIÓN DE PDF (jsPDF via CDN)
  // ════════════════════════════════════════════════════════════

  window.generarPDF = function () {
    if (typeof window.jspdf === "undefined") {
      showToast("Librería PDF no cargada.", "error");
      return;
    }
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ unit: "mm", format: "a4" });

    // Encabezado
    doc.setFontSize(16);
    doc.setFont("helvetica", "bold");
    doc.text("Reporte de Sesión Terapéutica", 14, 20);
    doc.setFontSize(10);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(100);
    doc.text("Sistema Embebido de Rehabilitación ACV — UNFV", 14, 27);
    doc.text(`Fecha: ${new Date().toLocaleString("es-PE")}`, 14, 33);
    doc.setTextColor(0);

    // Línea separadora
    doc.setDrawColor(200);
    doc.line(14, 37, 196, 37);

    // Tabla de rondas
    const filas = [];
    document.querySelectorAll("#tabla-rondas tr").forEach(tr => {
      const celdas = [...tr.querySelectorAll("td")].map(td => td.textContent.trim());
      if (celdas.length) filas.push(celdas);
    });

    if (filas.length && typeof doc.autoTable === "function") {
      doc.autoTable({
        startY: 42,
        head:   [["Ronda","Estímulo","Dirección","Resultado","Latencia","Ángulo","Temblor"]],
        body:   filas.reverse(),
        styles: { fontSize: 8, cellPadding: 3 },
        headStyles: { fillColor: [26, 86, 219] },
        alternateRowStyles: { fillColor: [245, 247, 255] },
      });
    } else {
      doc.setFontSize(10);
      doc.text("No hay datos de rondas para exportar.", 14, 50);
    }

    doc.save(`reporte-sesion-${Date.now()}.pdf`);
  };

  // ════════════════════════════════════════════════════════════
  // CONFIGURACIONES
  // ════════════════════════════════════════════════════════════

  function cargarConfiguraciones() {
    // Mostrar URL del backend configurada
    const urlEl = document.getElementById("cfg-api-url");
    if (urlEl) urlEl.value = window.ENV_API_BASE || "http://localhost:8000/api/v1";
  }

  document.getElementById("form-config")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const url = document.getElementById("cfg-api-url").value.trim();
    window.ENV_API_BASE = url;
    showToast("Configuración guardada en esta sesión.", "success");
  });
});

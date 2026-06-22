/**
 * js/audio.js
 * Motor de sonidos via Web Audio API nativa.
 * Sin archivos externos — todos los tonos se sintetizan en el navegador.
 */

const AudioEngine = (() => {
  let ctx = null;

  function _getCtx() {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    // Reanudar si el navegador lo suspendió por política de autoplay
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  /**
   * Reproduce un tono simple.
   * @param {number} frecuencia - Hz
   * @param {number} duracion   - segundos
   * @param {string} tipo       - "sine"|"square"|"triangle"|"sawtooth"
   * @param {number} volumen    - 0.0 a 1.0
   */
  function tono(frecuencia, duracion = 0.2, tipo = "sine", volumen = 0.4) {
    const c = _getCtx();
    const osc  = c.createOscillator();
    const gain = c.createGain();

    osc.connect(gain);
    gain.connect(c.destination);

    osc.type      = tipo;
    osc.frequency.setValueAtTime(frecuencia, c.currentTime);

    // Envelope: ramp up → sustain → ramp down
    gain.gain.setValueAtTime(0, c.currentTime);
    gain.gain.linearRampToValueAtTime(volumen, c.currentTime + 0.01);
    gain.gain.setValueAtTime(volumen, c.currentTime + duracion - 0.05);
    gain.gain.linearRampToValueAtTime(0, c.currentTime + duracion);

    osc.start(c.currentTime);
    osc.stop(c.currentTime + duracion);
  }

  /**
   * Reproduce una secuencia de notas [{f, d}] con delay acumulado.
   */
  function secuencia(notas, tipoOsc = "sine", volumen = 0.35) {
    const c = _getCtx();
    let t = c.currentTime;
    notas.forEach(({ f, d }) => {
      const osc  = c.createOscillator();
      const gain = c.createGain();
      osc.connect(gain);
      gain.connect(c.destination);
      osc.type = tipoOsc;
      osc.frequency.setValueAtTime(f, t);
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(volumen, t + 0.01);
      gain.gain.linearRampToValueAtTime(0, t + d - 0.02);
      osc.start(t);
      osc.stop(t + d);
      t += d;
    });
  }

  return {
    // ── Estímulo GO: bip corto ascendente ──────────────────────────────
    go() {
      secuencia([
        { f: 660, d: 0.08 },
        { f: 880, d: 0.12 },
      ], "sine", 0.4);
    },

    // ── Estímulo NO-GO: bip grave y plano ──────────────────────────────
    nogo() {
      tono(220, 0.18, "square", 0.25);
    },

    // ── Acierto: acorde mayor alegre ───────────────────────────────────
    acierto() {
      secuencia([
        { f: 523, d: 0.1 },
        { f: 659, d: 0.1 },
        { f: 784, d: 0.18 },
      ], "sine", 0.35);
    },

    // ── Error: bajada disonante ────────────────────────────────────────
    error() {
      secuencia([
        { f: 440, d: 0.12 },
        { f: 330, d: 0.18 },
      ], "sawtooth", 0.2);
    },

    // ── Timeout: tono neutro plano ─────────────────────────────────────
    timeout() {
      tono(350, 0.25, "triangle", 0.2);
    },

    // ── Melodía de fin de sesión ───────────────────────────────────────
    finSesion() {
      secuencia([
        { f: 523, d: 0.12 },
        { f: 659, d: 0.12 },
        { f: 784, d: 0.12 },
        { f: 1047, d: 0.30 },
      ], "sine", 0.3);
    },

    // ── Bienvenida ─────────────────────────────────────────────────────
    bienvenida() {
      secuencia([
        { f: 440, d: 0.1 },
        { f: 550, d: 0.1 },
      ], "sine", 0.25);
    },

    // ── Desbloquear contexto (llamar al primer tap del usuario) ────────
    desbloquear() { _getCtx(); },
  };
})();

window.AudioEngine = AudioEngine;

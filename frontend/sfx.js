/* v1.5.1 — Sound effects (Web Audio, synthesized: no files, works offline).
 * Sfx.play(name): success | add | error | login | alert | step | ready | install | click
 * Toggle: localStorage "sm.sfx" = "0" disables; volume "sm.sfx.vol" (0..1). */
(function () {
  "use strict";
  let ctx = null;
  const enabled = () => localStorage.getItem("sm.sfx") !== "0";
  const vol = () => { const v = parseFloat(localStorage.getItem("sm.sfx.vol")); return Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0.5; };
  function ac() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return null;
    ctx = new AC(); return ctx;
  }
  // unlock on first user gesture (browser autoplay policy)
  ["pointerdown", "keydown"].forEach((ev) => window.addEventListener(ev, () => { const c = ac(); if (c && c.state === "suspended") c.resume().catch(() => {}); }, { passive: true }));

  function tone(c, { f = 440, t0 = 0, d = 0.15, type = "sine", g = 0.3, slide = null }) {
    const o = c.createOscillator(), a = c.createGain();
    o.type = type; o.frequency.setValueAtTime(f, c.currentTime + t0);
    if (slide) o.frequency.exponentialRampToValueAtTime(slide, c.currentTime + t0 + d);
    a.gain.setValueAtTime(0.0001, c.currentTime + t0);
    a.gain.exponentialRampToValueAtTime(g * vol(), c.currentTime + t0 + 0.012);
    a.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + t0 + d);
    o.connect(a).connect(c.destination); o.start(c.currentTime + t0); o.stop(c.currentTime + t0 + d + 0.02);
  }
  const P = {
    // cheerful major arpeggio — sale completed / activation
    success: (c) => { [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => tone(c, { f, t0: i * 0.09, d: 0.22, type: "triangle", g: 0.28 })); tone(c, { f: 1567.98, t0: 0.36, d: 0.35, type: "sine", g: 0.12 }); },
    // short pop — item added to cart / scan hit
    add: (c) => { tone(c, { f: 880, d: 0.07, type: "square", g: 0.08 }); tone(c, { f: 1320, t0: 0.05, d: 0.09, type: "sine", g: 0.15 }); },
    // soft double low buzz — error
    error: (c) => { tone(c, { f: 220, d: 0.16, type: "sawtooth", g: 0.12, slide: 180 }); tone(c, { f: 196, t0: 0.18, d: 0.22, type: "sawtooth", g: 0.12, slide: 150 }); },
    // rising sweep — login / welcome
    login: (c) => { tone(c, { f: 392, d: 0.5, type: "sine", g: 0.2, slide: 784 }); tone(c, { f: 587.33, t0: 0.25, d: 0.4, type: "triangle", g: 0.15, slide: 1174.66 }); },
    // gentle two-note chime — alert / notification
    alert: (c) => { tone(c, { f: 987.77, d: 0.18, type: "sine", g: 0.2 }); tone(c, { f: 1318.5, t0: 0.16, d: 0.3, type: "sine", g: 0.18 }); },
    // tiny tick — wizard step
    step: (c) => tone(c, { f: 1500, d: 0.05, type: "sine", g: 0.1 }),
    click: (c) => tone(c, { f: 1000, d: 0.03, type: "square", g: 0.05 }),
    // ready — loading finished (short login loading)
    ready: (c) => { tone(c, { f: 659.25, d: 0.12, type: "triangle", g: 0.2 }); tone(c, { f: 987.77, t0: 0.12, d: 0.25, type: "triangle", g: 0.2 }); },
    // install complete — longer fanfare
    install: (c) => { [392, 523.25, 659.25, 783.99, 1046.5].forEach((f, i) => tone(c, { f, t0: i * 0.12, d: 0.3, type: "triangle", g: 0.25 })); [523.25, 659.25, 783.99].forEach((f) => tone(c, { f, t0: 0.7, d: 0.9, type: "sine", g: 0.12 })); },
  };
  function play(name) {
    if (!enabled()) return false;
    const c = ac(); if (!c) return false;
    if (c.state === "suspended") c.resume().catch(() => {});
    try { (P[name] || P.click)(c); return true; } catch (_) { return false; }
  }
  window.Sfx = { play, enabled, setEnabled: (v) => localStorage.setItem("sm.sfx", v ? "1" : "0"), volume: vol, setVolume: (v) => localStorage.setItem("sm.sfx.vol", String(v)), names: Object.keys(P) };
})();

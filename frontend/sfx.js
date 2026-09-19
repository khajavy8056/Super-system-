/* v1.5.1/v1.6 — Sound effects (Web Audio, synthesized: no files, works offline).
 * Sfx.play(name):
 *   welcome  — short instrumental jingle on app start (after login)
 *   success  — sale completed / activation        add     — item added to cart
 *   error    — soft low double-tone               login   — rising sweep
 *   alert    — gentle two-note chime              note    — notification / bottom alert
 *   void     — invoice voided (descending)        hold    — invoice parked
 *   resume   — invoice restored                   step / click / ready / install / exit
 * All levels are deliberately low (a shop till must not be loud); master volume
 * "sm.sfx.vol" (0..1, default 0.35); "sm.sfx"="0" disables. */
(function () {
  "use strict";
  let ctx = null, master = null;
  const enabled = () => localStorage.getItem("sm.sfx") !== "0";
  const vol = () => { const v = parseFloat(localStorage.getItem("sm.sfx.vol")); return Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0.35; };
  function ac() {
    if (ctx) return ctx;
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return null;
    ctx = new AC();
    master = ctx.createGain(); master.gain.value = vol();
    // soft low-pass so nothing sounds harsh
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 3800; lp.Q.value = 0.4;
    master.connect(lp).connect(ctx.destination);
    return ctx;
  }
  // unlock on first user gesture (browser autoplay policy)
  ["pointerdown", "keydown"].forEach((ev) => window.addEventListener(ev, () => { const c = ac(); if (c && c.state === "suspended") c.resume().catch(() => {}); }, { passive: true }));

  function tone(c, { f = 440, t0 = 0, d = 0.15, type = "sine", g = 0.3, slide = null, a = 0.012 }) {
    const o = c.createOscillator(), env = c.createGain();
    o.type = type; o.frequency.setValueAtTime(f, c.currentTime + t0);
    if (slide) o.frequency.exponentialRampToValueAtTime(slide, c.currentTime + t0 + d);
    env.gain.setValueAtTime(0.0001, c.currentTime + t0);
    env.gain.exponentialRampToValueAtTime(g, c.currentTime + t0 + a);
    env.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + t0 + d);
    o.connect(env).connect(master); o.start(c.currentTime + t0); o.stop(c.currentTime + t0 + d + 0.02);
  }
  // simple pluck used by the welcome jingle (triangle + quiet octave)
  const pluck = (c, f, t0, d = 0.5, g = 0.16) => { tone(c, { f, t0, d, type: "triangle", g, a: 0.006 }); tone(c, { f: f * 2, t0, d: d * 0.6, type: "sine", g: g * 0.35, a: 0.004 }); };
  const N = { C4: 261.63, D4: 293.66, E4: 329.63, F4: 349.23, G4: 392, A4: 440, B4: 493.88, C5: 523.25, D5: 587.33, E5: 659.25, F5: 698.46, G5: 783.99, A5: 880, B5: 987.77, C6: 1046.5 };
  const P = {
    // ~3.5 s instrumental jingle (I–V–vi–IV feel), quiet
    welcome: (c) => {
      const seq = [[N.C5, 0], [N.E5, .18], [N.G5, .36], [N.C6, .54], [N.B5, .9], [N.G5, 1.08], [N.A5, 1.35], [N.C6, 1.53], [N.E5, 1.8], [N.F5, 1.98], [N.A5, 2.16], [N.G5, 2.55]];
      seq.forEach(([f, t]) => pluck(c, f, t, 0.55, 0.14));
      [[N.C4, 0], [N.G4, .9], [N.A4, 1.35], [N.F4, 1.98], [N.C4, 2.55]].forEach(([f, t]) => tone(c, { f, t0: t, d: 0.9, type: "sine", g: 0.09, a: 0.03 }));
      pluck(c, N.C6, 2.95, 1.2, 0.12); tone(c, { f: N.E5, t0: 2.95, d: 1.2, type: "sine", g: 0.06, a: 0.05 });
    },
    // cheerful major arpeggio — sale completed / activation
    success: (c) => { [N.C5, N.E5, N.G5, N.C6].forEach((f, i) => tone(c, { f, t0: i * 0.09, d: 0.22, type: "triangle", g: 0.16 })); tone(c, { f: N.G5 * 2, t0: 0.36, d: 0.35, type: "sine", g: 0.07 }); },
    // short pop — item added to cart / scan hit
    add: (c) => { tone(c, { f: 880, d: 0.06, type: "square", g: 0.035 }); tone(c, { f: 1320, t0: 0.045, d: 0.09, type: "sine", g: 0.09 }); },
    // soft double low tone — error (not a buzzer)
    error: (c) => { tone(c, { f: 260, d: 0.14, type: "triangle", g: 0.11, slide: 220 }); tone(c, { f: 230, t0: 0.17, d: 0.2, type: "triangle", g: 0.11, slide: 180 }); },
    // rising sweep — login
    login: (c) => { tone(c, { f: N.G4, d: 0.45, type: "sine", g: 0.12, slide: N.G5 }); tone(c, { f: N.D5, t0: 0.22, d: 0.4, type: "triangle", g: 0.08, slide: N.D5 * 2 }); },
    // gentle two-note chime — critical alert
    alert: (c) => { tone(c, { f: N.B5, d: 0.18, type: "sine", g: 0.12 }); tone(c, { f: N.E5 * 2, t0: 0.16, d: 0.3, type: "sine", g: 0.1 }); },
    // single soft note — ordinary notification / bottom toast
    note: (c) => { tone(c, { f: N.A5, d: 0.16, type: "sine", g: 0.09 }); tone(c, { f: N.A5 * 1.5, t0: 0.05, d: 0.2, type: "sine", g: 0.04 }); },
    // descending minor — invoice voided
    void: (c) => { [N.E5, N.C5, N.A4].forEach((f, i) => tone(c, { f, t0: i * 0.12, d: 0.28, type: "triangle", g: 0.11 })); },
    // hold: two quick descending ticks; resume: reversed
    hold: (c) => { tone(c, { f: N.G5, d: 0.07, type: "sine", g: 0.09 }); tone(c, { f: N.D5, t0: 0.08, d: 0.12, type: "sine", g: 0.09 }); },
    resume: (c) => { tone(c, { f: N.D5, d: 0.07, type: "sine", g: 0.09 }); tone(c, { f: N.G5, t0: 0.08, d: 0.14, type: "sine", g: 0.09 }); },
    // tiny tick — wizard step
    step: (c) => tone(c, { f: 1500, d: 0.05, type: "sine", g: 0.06 }),
    click: (c) => tone(c, { f: 1000, d: 0.03, type: "square", g: 0.025 }),
    // ready — loading finished (short login loading)
    ready: (c) => { tone(c, { f: N.E5, d: 0.12, type: "triangle", g: 0.12 }); tone(c, { f: N.B5, t0: 0.12, d: 0.25, type: "triangle", g: 0.12 }); },
    // install complete — longer, still soft
    install: (c) => { [N.G4, N.C5, N.E5, N.G5, N.C6].forEach((f, i) => tone(c, { f, t0: i * 0.12, d: 0.3, type: "triangle", g: 0.14 })); [N.C5, N.E5, N.G5].forEach((f) => tone(c, { f, t0: 0.7, d: 0.9, type: "sine", g: 0.06 })); },
    // exit — calm descending farewell
    exit: (c) => { [N.C6, N.G5, N.E5, N.C5].forEach((f, i) => pluck(c, f, i * 0.16, 0.5, 0.11)); tone(c, { f: N.C4, t0: 0.5, d: 1.1, type: "sine", g: 0.07, a: 0.04 }); },
  };
  function play(name) {
    if (!enabled()) return false;
    const c = ac(); if (!c) return false;
    if (c.state === "suspended") c.resume().catch(() => {});
    master.gain.value = vol();
    try { (P[name] || P.click)(c); return true; } catch (_) { return false; }
  }
  window.Sfx = { play, enabled, setEnabled: (v) => localStorage.setItem("sm.sfx", v ? "1" : "0"), volume: vol, setVolume: (v) => { localStorage.setItem("sm.sfx.vol", String(v)); if (master) master.gain.value = vol(); }, names: Object.keys(P) };
})();

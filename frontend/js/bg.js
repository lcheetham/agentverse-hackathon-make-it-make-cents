// "Pearl Horizon" atmosphere: pale gradient, five soft orbs, S-curve ribbon in three bands, cursor swoop.
// Time-driven (seconds), integer cycles per 60 s, seeded phases. Pauses when hidden; static at t=0 for reduced motion.
const ORBS = [ // cx, cy (fractions of w,h), radius (x max(w,h)), colour, alpha, cycles/60s (integer), drift amplitude
  [0.80, 0.12, 0.50, '140,196,242', 0.42, 1, 0.020],
  [0.08, 0.31, 0.42, '216,212,242', 0.55, 2, 0.018],
  [0.26, 1.04, 0.44, '251,237,227', 0.75, 1, 0.022],
  [0.98, 0.96, 0.40, '147,166,194', 0.30, 2, 0.016],
  [0.56, 0.42, 0.22, '226,231,238', 0.70, 3, 0.014],
];
function mulberry32(a) { return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

export function startBackground(canvas) {
  const ctx = canvas.getContext('2d');
  const rnd = mulberry32(20260711);
  const phases = ORBS.map(() => [rnd() * Math.PI * 2, rnd() * Math.PI * 2]);
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
  const touch = window.matchMedia('(hover: none)');
  let w = 0, h = 0, dpr = 1, t = 0, last = 0, raf = 0;
  const ptr = { x: 0.5, y: 0.5, ox: 0, oy: 0, active: false };

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    w = window.innerWidth; h = window.innerHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }
  const TAU = Math.PI * 2;
  function draw() {
    const m = Math.max(w, h);
    const g = ctx.createLinearGradient(0, 0, w * 0.4, h);
    g.addColorStop(0, '#F7F8FB'); g.addColorStop(1, '#E2E7EE');
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    ORBS.forEach(([cx, cy, r, col, a, cyc, amp], i) => {
      const x = cx * w + Math.sin(TAU * cyc * t / 60 + phases[i][0]) * amp * m;
      const y = cy * h + Math.cos(TAU * cyc * t / 60 + phases[i][1]) * amp * m;
      const breathe = 1 + 0.03 * Math.sin(TAU * t / 30 + phases[i][0]);
      const rg = ctx.createRadialGradient(x, y, 0, x, y, r * m * breathe);
      rg.addColorStop(0, `rgba(${col},${a})`); rg.addColorStop(0.55, `rgba(${col},${a * 0.35})`); rg.addColorStop(1, `rgba(${col},0)`);
      ctx.fillStyle = rg; ctx.fillRect(0, 0, w, h);
    });
    // ribbon: broad S-curve, three fading bands
    const wob = Math.sin(TAU * t / 60) * 0.03 * h;
    const path = () => { ctx.beginPath(); ctx.moveTo(-0.05 * w, 0.72 * h + wob); ctx.bezierCurveTo(0.3 * w, 0.2 * h - wob, 0.55 * w, 1.05 * h + wob, 1.05 * w, 0.32 * h - wob); };
    ctx.lineCap = 'round';
    [[0.30, 0.10, '185,214,242'], [0.16, 0.14, '255,255,255'], [0.05, 0.20, '255,255,255']].forEach(([lw, a, col]) => {
      ctx.lineWidth = lw * h; ctx.strokeStyle = `rgba(${col},${a})`; path(); ctx.stroke();
    });
    // travelling sweep along the ribbon
    const sp = ((t / 60) % 1) * 1.6 - 0.3;
    const sg = ctx.createLinearGradient(w * (sp - 0.2), 0, w * (sp + 0.2), 0);
    sg.addColorStop(0, 'rgba(255,255,255,0)'); sg.addColorStop(0.5, 'rgba(255,255,255,0.28)'); sg.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.lineWidth = 0.08 * h; ctx.strokeStyle = sg; path(); ctx.stroke();
    // cursor swoop + echo (2.5-5.5% opacity, offsets bounded)
    if (ptr.active && !mq.matches && !touch.matches) {
      const ox = ptr.ox, oy = ptr.oy;
      const band = (dx, dy, a) => { ctx.lineWidth = 0.16 * h; ctx.strokeStyle = `rgba(140,196,242,${a})`; ctx.beginPath(); ctx.moveTo(0.1 * w + dx, 0.85 * h + dy); ctx.quadraticCurveTo(0.5 * w + dx, 0.05 * h + dy, 0.9 * w + dx, 0.7 * h + dy); ctx.stroke(); };
      band(ox, oy, 0.045); band(ox * 1.6, oy * 1.6 + 0.04 * h, 0.022);
    }
  }
  function frame(now) {
    raf = 0;
    if (document.hidden || mq.matches) return;
    let dt = (now - last) / 1000; last = now;
    if (dt * 1000 > 100) dt = 0; // discard frame gaps > 100 ms
    t += dt;
    const a = 1 - Math.exp(-dt / 0.22);
    const mx = Math.min(14, 0.012 * w), my = Math.min(8, 0.008 * h);
    ptr.ox += ((ptr.x - 0.5) * 2 * mx - ptr.ox) * a; ptr.oy += ((ptr.y - 0.5) * 2 * my - ptr.oy) * a;
    draw();
    schedule();
  }
  function schedule() { if (!raf && !document.hidden && !mq.matches) raf = requestAnimationFrame((n) => { if (n - last < 30) { raf = 0; schedule(); return; } frame(n); }); }
  function restart() { cancelAnimationFrame(raf); raf = 0; last = performance.now(); if (mq.matches) { t = 0; draw(); } else schedule(); }

  window.addEventListener('resize', resize);
  window.addEventListener('pointermove', (e) => { if (e.pointerType === 'touch') return; ptr.x = e.clientX / w; ptr.y = e.clientY / h; ptr.active = true; });
  document.addEventListener('visibilitychange', restart);
  mq.addEventListener?.('change', restart);
  resize(); restart();
}

/* Firetier motion: the fire splash with real boot steps, and click feedback (ripples, sparks, bursts).
   Loaded before app.js. Pure decoration: every effect is skipped under reduced motion. */
(function () {
  "use strict";
  const FT = (window.FT = window.FT || {});
  // The splash starts before /api/state answers, so it uses the motion setting cached by the last session.
  let boot = "full";
  try { boot = localStorage.getItem("ft-motion") || "full"; } catch (e) { /* storage off */ }
  FT.bootMotion = boot;
  if (boot !== "system") document.documentElement.dataset.motion = boot;
  const reduced = () => {
    if (FT.reducedMotion) return FT.reducedMotion();
    return boot === "reduced" || (boot !== "full" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- glow sprites, tinted once ----------
  function sprite(r, g, b) {
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const x = c.getContext("2d"), gr = x.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, `rgba(${r},${g},${b},1)`);
    gr.addColorStop(.35, `rgba(${r},${g},${b},.55)`);
    gr.addColorStop(1, `rgba(${r},${g},${b},0)`);
    x.fillStyle = gr;
    x.fillRect(0, 0, 64, 64);
    return c;
  }
  let SPR = null;
  const sprites = () => (SPR = SPR || [sprite(255, 244, 200), sprite(255, 190, 80), sprite(255, 120, 45), sprite(220, 60, 25), sprite(110, 30, 18)]);
  // age 0..1 -> sprite index: white-hot core, amber, orange, red, smoke-red
  const tint = (a) => (a < .12 ? 0 : a < .3 ? 1 : a < .55 ? 2 : a < .8 ? 3 : 4);

  // ---------- particle field shared by splash fire and click sparks ----------
  function Field(canvas, scale) {
    const ctx = canvas.getContext("2d");
    let W = 0, H = 0, dpr = 1;
    const parts = [];
    function size() {
      dpr = Math.min(window.devicePixelRatio || 1, 1.5) * scale;
      W = canvas.clientWidth; H = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(W * dpr)); canvas.height = Math.max(1, Math.round(H * dpr));
    }
    size();
    window.addEventListener("resize", size);
    function step(dt) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      const S = sprites();
      for (let i = parts.length - 1; i >= 0; i--) {
        const p = parts[i];
        p.t += dt;
        const a = p.t / p.life;
        if (a >= 1) { parts.splice(i, 1); continue; }
        p.vx += (Math.sin(p.t * p.wf + p.ph) * p.wob - p.vx * p.drag) * dt;
        p.vy += (p.g - p.vy * p.drag) * dt;
        p.x += p.vx * dt; p.y += p.vy * dt;
        const r = p.r * (p.grow ? 1 + a * .6 : 1 - a * .75);
        const flick = p.spark ? .6 + Math.random() * .4 : 1;
        ctx.globalAlpha = Math.min(1, (1 - a) * 1.6) * p.alpha * flick;
        ctx.drawImage(S[p.spark ? Math.min(2, tint(a)) : tint(a)], p.x - r, p.y - r, r * 2, r * 2);
      }
      ctx.globalAlpha = 1;
    }
    return { parts, step, size, get W() { return W; }, get H() { return H; } };
  }

  // ---------- splash ----------
  const splash = (() => {
    const el = document.getElementById("splash");
    if (!el) return null;
    const t0 = performance.now();
    const canvas = el.querySelector("canvas"), list = el.querySelector("#splash-steps"), bar = el.querySelector("#splash-bar");
    const hello = el.querySelector("#splash-hello");
    const rows = new Map();
    let total = 5, done = 0, running = true, field = null, last = 0, skipped = false, onSkip;
    // Boot races its slow steps (account, health checks) against this, so a skip doesn't wait for them.
    const whenSkipped = new Promise((r) => { onSkip = r; });
    const skip = () => { skipped = true; onSkip("skipped"); if (api.ready) api.finish(); };
    el.addEventListener("click", skip);
    const onKey = (e) => { if (!api.closed && (e.key === "Escape" || e.key === "Enter" || e.key === " ")) skip(); };
    document.addEventListener("keydown", onKey);

    function spawn(f, n) {
      const cx = f.W / 2, base = f.H + 10;
      for (let i = 0; i < n; i++) {
        const centre = Math.random() < .62;
        const x = centre ? cx + (Math.random() + Math.random() + Math.random() - 1.5) * Math.min(f.W * .32, 260) : Math.random() * f.W;
        const big = centre ? 1 : .7;
        f.parts.push({ x, y: base + Math.random() * 20, vx: (Math.random() - .5) * 20, vy: -(70 + Math.random() * 120) * big,
          g: -38, drag: .35, wob: 55 + Math.random() * 60, wf: 2 + Math.random() * 3, ph: Math.random() * 6.3,
          r: (26 + Math.random() * 38) * big, life: 1.6 + Math.random() * 1.6, t: 0, alpha: .42, grow: false });
      }
      if (Math.random() < .35) // ember
        f.parts.push({ x: cx + (Math.random() - .5) * f.W * .6, y: base, vx: (Math.random() - .5) * 40, vy: -(140 + Math.random() * 160),
          g: -20, drag: .2, wob: 120, wf: 4 + Math.random() * 4, ph: Math.random() * 6.3, r: 2.5 + Math.random() * 3,
          life: 2.4 + Math.random() * 2, t: 0, alpha: 1, spark: true });
    }
    function loop(now) {
      if (!running) return;
      const dt = Math.min(.05, (now - (last || now)) / 1000);
      last = now;
      if (!document.hidden) {
        spawn(field, Math.round(dt * 150) || 1);
        field.step(dt);
      }
      requestAnimationFrame(loop);
    }
    if (!reduced()) {
      field = Field(canvas, .5); // half resolution: soft flames, a quarter of the fill cost
      for (let i = 0; i < 90; i++) { spawn(field, 1); field.parts[field.parts.length - 1].t = Math.random() * 1.4; }
      requestAnimationFrame(loop);
    }

    function progress() { bar.style.width = Math.max(4, Math.round((done / total) * 100)) + "%"; }
    const api = {
      ready: false,
      skipped: whenSkipped,
      total(n) { total = n; progress(); },
      step(key, label) {
        const li = document.createElement("li");
        li.innerHTML = `<span class="st"></span><span>${esc(label)}</span><small></small>`;
        list.appendChild(li);
        rows.set(key, li);
      },
      done(key, detail, lvl) {
        const li = rows.get(key);
        if (!li || li.dataset.done) return;
        li.dataset.done = "1";
        li.className = lvl || "ok";
        li.querySelector("small").textContent = detail || "";
        done++;
        progress();
      },
      hello(acc) {
        if (!acc) return;
        hello.classList.remove("swap"); void hello.offsetWidth; hello.classList.add("swap");
        hello.innerHTML = (acc.avatar_data ? `<img src="${esc(acc.avatar_data)}" alt="">` : "") +
          `<span>Welcome back, <b>${esc(acc.display_name || acc.name)}</b></span>`;
      },
      async finish() {
        api.ready = true;
        const min = reduced() ? 250 : 1900;
        const wait = skipped ? 0 : Math.max(0, min - (performance.now() - t0));
        if (wait) await new Promise((r) => setTimeout(r, wait));
        if (api.closed) return;
        api.closed = true;
        done = total; progress();
        if (field && !reduced()) { // flare: a fast upward gust as the curtain lifts
          for (let i = 0; i < 70; i++) spawn(field, 1);
          field.parts.forEach((p) => { p.vy *= 2.2; });
        }
        el.classList.add("out");
        if (skipped) el.classList.add("quick");
        const app = document.querySelector(".app");
        if (app && !reduced()) {
          document.querySelectorAll(".sidebar .brand, .sidebar .nav-item, .sidebar .nav-label").forEach((n, i) => n.style.setProperty("--n", i));
          app.classList.add("enter");
          setTimeout(() => app.classList.remove("enter"), 1400);
        }
        await new Promise((r) => setTimeout(r, reduced() ? 0 : skipped ? 240 : 560));
        running = false;
        document.removeEventListener("keydown", onKey);
        el.remove();
      },
    };
    progress();
    return api;
  })();
  FT.splash = splash || { ready: true, total() {}, step() {}, done() {}, hello() {}, finish: async () => {} };

  // ---------- click feedback ----------
  let fxField = null, fxRunning = false, fxLast = 0;
  function fxLoop(now) {
    const dt = Math.min(.05, (now - (fxLast || now)) / 1000);
    fxLast = now;
    fxField.step(dt);
    if (fxField.parts.length) requestAnimationFrame(fxLoop);
    else { fxRunning = false; fxLast = 0; }
  }
  function field() {
    if (!fxField) {
      const c = document.createElement("canvas");
      c.className = "fx-canvas";
      c.setAttribute("aria-hidden", "true");
      document.body.appendChild(c);
      fxField = Field(c, 1);
    }
    return fxField;
  }
  function kick() { if (!fxRunning) { fxRunning = true; requestAnimationFrame(fxLoop); } }

  // Sparks fly out of (x, y). n ≈ 8 for a click, 60+ for a celebration.
  function sparks(x, y, n, power) {
    if (reduced()) return;
    const f = field(), pw = power || 1;
    for (let i = 0; i < n; i++) {
      const ang = -Math.PI / 2 + (Math.random() - .5) * Math.PI * 1.7, sp = (120 + Math.random() * 260) * pw;
      f.parts.push({ x, y, vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, g: 520, drag: 1.6, wob: 0, wf: 0, ph: 0,
        r: 2 + Math.random() * 2.6 * pw, life: .45 + Math.random() * .5 * pw, t: 0, alpha: 1, spark: true });
    }
    for (let i = 0; i < Math.round(n / 3); i++) // a soft glow puff under the sparks
      f.parts.push({ x: x + (Math.random() - .5) * 10, y: y + (Math.random() - .5) * 6, vx: (Math.random() - .5) * 40, vy: -40 - Math.random() * 60,
        g: -30, drag: 1, wob: 30, wf: 3, ph: Math.random() * 6, r: 12 + Math.random() * 14 * pw, life: .5 + Math.random() * .4, t: 0, alpha: .35, grow: true });
    kick();
  }
  function ring(x, y, scale) {
    if (reduced()) return;
    const r = document.createElement("div");
    r.className = "fx-ring";
    r.style.left = x + "px"; r.style.top = y + "px";
    r.style.setProperty("--s", scale || 9);
    document.body.appendChild(r);
    setTimeout(() => r.remove(), 760);
  }
  const lastPointer = { x: innerWidth / 2, y: innerHeight / 2 };
  function at(target) {
    if (target && target.getBoundingClientRect) {
      const b = target.getBoundingClientRect();
      if (b.width) return { x: b.left + b.width / 2, y: b.top + b.height / 2 };
    }
    return lastPointer;
  }
  // The big one: apply succeeded, account connected, import landed.
  function celebrate(target) {
    const p = at(target);
    ring(p.x, p.y, 11);
    setTimeout(() => ring(p.x, p.y, 6), 110);
    sparks(p.x, p.y, 70, 1.6);
  }
  FT.fx = { sparks, ring, celebrate, lastPointer };

  const RIPPLE = ".btn:not(:disabled):not(.loading), .nav-item, .target-mini, .acct-chip, .card.interactive, .seg button, .chip, .qa button:not(:disabled)";
  document.addEventListener("pointerdown", (e) => {
    lastPointer.x = e.clientX; lastPointer.y = e.clientY;
    if (e.button !== 0 || reduced()) return;
    const el = e.target.closest(RIPPLE);
    if (!el) return;
    const b = el.getBoundingClientRect();
    let host = el.querySelector(":scope > .rip-host");
    if (!host) {
      if (getComputedStyle(el).position === "static") el.style.position = "relative";
      host = document.createElement("span");
      host.className = "rip-host";
      el.appendChild(host);
    }
    const d = Math.hypot(Math.max(e.clientX - b.left, b.right - e.clientX), Math.max(e.clientY - b.top, b.bottom - e.clientY)) * 2;
    const r = document.createElement("span");
    r.className = "rip";
    r.style.cssText = `left:${e.clientX - b.left}px;top:${e.clientY - b.top}px;width:${d}px;height:${d}px`;
    host.appendChild(r);
    setTimeout(() => r.remove(), 680);
    if (el.matches(".btn.primary")) sparks(e.clientX, e.clientY, 10, .8);
  }, true);
  // A little flick of embers when a switch turns on.
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t && t.matches && t.matches(".switch input[type=checkbox]") && t.checked) {
      const tr = t.parentElement.querySelector(".track");
      if (tr) { const b = tr.getBoundingClientRect(); sparks(b.right - 10, b.top + b.height / 2, 7, .6); }
    }
  }, true);
})();

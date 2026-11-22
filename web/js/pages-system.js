/* Asset Studio (local preview only), Diagnostics, Settings. */
(function () {
  "use strict";
  const FT = window.FT, PAGES = window.FTPages, { esc, icon, $, $$, plural, api } = FT;

  // Fit a canvas's backing store to its CSS box (capped), return true if it changed.
  function fitCanvas(c, fast) {
    const dpr = window.devicePixelRatio || 1, q = fast ? 0.5 : 1;
    let w = Math.round(c.clientWidth * dpr * q), h = Math.round(c.clientHeight * dpr * q);
    const cap = 1.6e6;
    if (w * h > cap) { const k = Math.sqrt(cap / (w * h)); w = Math.round(w * k); h = Math.round(h * k); }
    if (w < 2 || h < 2) return false;
    if (c.width === w && c.height === h) return false;
    c.width = w; c.height = h;
    return true;
  }
  const fmtDur = (s) => (isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "0:00");

  // =====================================================================
  // Asset Studio: files stay in this window as blob URLs. Nothing is uploaded or written.
  // =====================================================================
  const files = [];
  let selId = null, level = 3, seq = 0;
  const LEVELS = [[3, "Level 3 · full"], [2, "2"], [1, "1"], [0, "0 · lowest"]];
  const FACTOR = { 3: 1, 2: 2, 1: 4, 0: 8 };

  function loadFile(f) {
    return new Promise((resolve) => {
      const kind = f.type.startsWith("image/") ? "image" : f.type.startsWith("audio/") ? "audio" : null;
      if (!kind) { FT.toast("warn", "Not an image or audio file", f.name); return resolve(null); }
      if (f.size > 64 * 1048576) { FT.toast("warn", "File too large to preview", `${f.name} · ${FT.fmtBytes(f.size)}`); return resolve(null); }
      const rec = { id: "a" + ++seq, name: f.name, type: f.type || kind, size: f.size, kind, url: URL.createObjectURL(f), file: f };
      if (kind === "image") {
        const img = new Image();
        img.onload = () => { rec.img = img; rec.w = img.naturalWidth; rec.h = img.naturalHeight; resolve(rec); };
        img.onerror = () => { URL.revokeObjectURL(rec.url); FT.toast("err", "Couldn't decode image", f.name); resolve(null); };
        img.src = rec.url;
      } else {
        f.arrayBuffer().then((buf) => {
          const AC = window.AudioContext || window.webkitAudioContext;
          const ctx = new AC();
          return ctx.decodeAudioData(buf).then((ab) => {
            rec.dur = ab.duration; rec.rate = ab.sampleRate; rec.channels = ab.numberOfChannels;
            const ch = ab.getChannelData(0), N = 1200, step = Math.max(1, Math.floor(ch.length / N)), peaks = new Float32Array(N);
            for (let i = 0; i < N; i++) {
              let m = 0;
              for (let j = i * step, e = Math.min(ch.length, j + step); j < e; j++) { const v = Math.abs(ch[j]); if (v > m) m = v; }
              peaks[i] = m;
            }
            rec.peaks = peaks;
            ctx.close();
            resolve(rec);
          });
        }).catch(() => { URL.revokeObjectURL(rec.url); FT.toast("err", "Couldn't decode audio", f.name); resolve(null); });
      }
    });
  }

  PAGES.assets = {
    full: true,
    render(page) {
      const S = FT.S, imports = FT.allProfiles().filter((p) => p.unsupported);
      FT.setTop("Asset Studio", "Preview local images and sounds · nothing leaves this window");
      page.innerHTML = `<div class="studio">
        <aside class="dock left" aria-label="Files">
          <div class="dock-hd"><span class="eyebrow">Local files</span><span class="end">
            <button class="btn ghost icon sm" id="as-pick2" aria-label="Open files" data-tip="Open files">${icon("plus", "sm")}</button></span></div>
          <div class="drop" id="as-drop">${icon("import")}<div style="margin:6px 0 8px">Drop images or audio here</div>
            <button class="btn sm" id="as-pick">${icon("folder", "sm")}Browse…</button>
            <input type="file" id="as-file" accept="image/*,audio/*" multiple class="sr-only" tabindex="-1" aria-hidden="true"></div>
          <div class="tree" id="as-list" role="listbox" aria-label="Local files"></div>
        </aside>
        <section class="studio-stage" id="as-stage" aria-label="Preview"></section>
        <aside class="dock right" id="as-info" aria-label="File details"></aside>
      </div>`;

      let audio = null, raf = 0, ro = null, timer = 0;
      const cur = () => files.find((f) => f.id === selId);

      const paintList = () => {
        $("#as-list").innerHTML = (files.length ? `<div class="eyebrow">This session</div>` + files.map((f) => `<button class="tree-item" role="option" data-id="${f.id}" aria-selected="${f.id === selId}">
            ${f.kind === "image" ? `<img class="asset-thumb" src="${f.url}" alt="">` : `<span class="asset-thumb">${icon("music", "sm")}</span>`}
            <span>${esc(f.name)}</span><small>${FT.fmtBytes(f.size)}</small></button>`).join("") : "")
          + `<div class="eyebrow">Stored imports</div>` + (imports.length
            ? imports.map((p) => `<a class="tree-item locked" href="#/editor?id=${encodeURIComponent(p.id)}" data-tip="Asset replacement list · reference only">${icon("lock", "sm")}<span>${esc(p.name)}</span><small>${p.rules || ""}</small></a>`).join("")
            : `<p class="hint" style="padding:4px 8px 8px">Fleasion-style asset lists you import show up here. They are stored for reference and never applied.</p>`);
      };
      const paintInfo = () => {
        const f = cur();
        $("#as-info").innerHTML = `<div class="insp-grp"><div class="eyebrow">${icon("info", "sm")}Details</div>${f ? `<dl class="kv-list">
            <dt>Name</dt><dd>${esc(f.name)}</dd><dt>Type</dt><dd class="mono">${esc(f.type)}</dd><dt>Size</dt><dd>${FT.fmtBytes(f.size)}</dd>
            ${f.kind === "image" ? `<dt>Dimensions</dt><dd>${f.w} × ${f.h}</dd><dt>At level ${level}</dt><dd>${Math.max(1, Math.round(f.w / FACTOR[level]))} × ${Math.max(1, Math.round(f.h / FACTOR[level]))}</dd>`
              : `<dt>Duration</dt><dd>${fmtDur(f.dur)}</dd><dt>Sample rate</dt><dd>${(f.rate / 1000).toFixed(1)} kHz</dd><dt>Channels</dt><dd>${f.channels}</dd>`}
          </dl><button class="btn ghost sm" id="as-rm" style="align-self:flex-start;margin-left:-8px">${icon("x", "sm")}Remove from list</button>` : `<p class="hint">Pick a file to see its details.</p>`}</div>
          ${f && f.kind === "image" ? `<div class="insp-grp"><div class="eyebrow">${icon("export", "sm")}Export</div>
            <button class="btn sm" id="as-png" style="align-self:flex-start">${icon("download", "sm")}Save level ${level} as PNG</button>
            <p class="help">Downloads a PNG at ${Math.max(1, Math.round(f.w / FACTOR[level]))} × ${Math.max(1, Math.round(f.h / FACTOR[level]))}, the size this level keeps. A local approximation for comparing, not a Roblox render. Nothing is uploaded.</p></div>` : ""}
          <div class="insp-grp"><div class="callout">${icon("shield")}<div><b>Preview only</b><p>Firetier never uploads, swaps or replaces Roblox assets. Files stay in this window and are gone when you close it.</p></div></div>
            ${f && f.kind === "image" ? `<p class="help">The texture level slider mimics what <span class="mono">DFIntTextureQualityOverride</span> does: Roblox drops mip levels, so each step halves the resolution. It's a local approximation, not a Roblox render.</p>` : ""}</div>`;
        const rm = $("#as-rm");
        if (rm) rm.onclick = () => {
          const i = files.findIndex((x) => x.id === selId);
          if (i < 0) return;
          URL.revokeObjectURL(files[i].url);
          files.splice(i, 1);
          selId = files[0] ? files[0].id : null;
          paintAll();
        };
        const png = $("#as-png");
        if (png) png.onclick = () => {
          const k = FACTOR[level], out = document.createElement("canvas");
          out.width = Math.max(1, Math.round(f.w / k)); out.height = Math.max(1, Math.round(f.h / k));
          // Halve step by step, like dropping mip levels, so the result isn't aliased.
          let src = f.img, sw = f.w, sh = f.h;
          while (sw / 2 >= out.width && sh / 2 >= out.height && sw > out.width) {
            const c = document.createElement("canvas");
            c.width = Math.max(1, Math.round(sw / 2)); c.height = Math.max(1, Math.round(sh / 2));
            const g = c.getContext("2d"); g.imageSmoothingQuality = "high"; g.drawImage(src, 0, 0, c.width, c.height);
            src = c; sw = c.width; sh = c.height;
          }
          const g = out.getContext("2d"); g.imageSmoothingQuality = "high"; g.drawImage(src, 0, 0, out.width, out.height);
          const base = f.name.replace(/\.[^.]+$/, "") || "texture";
          out.toBlob((b) => {
            if (!b) { FT.toast("err", "Couldn't encode the PNG"); return; }
            const name = `${base}-level${level}-approx.png`;
            FT.download(name, b, "image/png");
            FT.toast("ok", "PNG saved", `${name} · ${out.width} × ${out.height}`);
          }, "image/png");
        };
      };

      const drawImage = () => {
        const f = cur();
        if (!f || f.kind !== "image") return;
        const b = $("#as-stage canvas.before"), a = $("#as-stage canvas.after");
        if (!b) return;
        const fast = S.prefs.preview_quality === "fast";
        fitCanvas(b, fast); fitCanvas(a, fast);
        window.FTPreview.downscaleImage(b, f.img, 1);
        window.FTPreview.downscaleImage(a, f.img, FACTOR[level]);
      };
      const drawWave = (t) => {
        const f = cur(), c = $("#as-wave");
        if (!f || !c || !f.peaks) return;
        fitCanvas(c, false);
        const g = c.getContext("2d"), w = c.width, h = c.height, n = f.peaks.length, mid = h / 2;
        const css = getComputedStyle(document.documentElement);
        const played = css.getPropertyValue("--ac").trim() || "#ff6a3d", rest = css.getPropertyValue("--s4").trim() || "#3a3f47";
        const pos = f.dur ? (t || 0) / f.dur : 0, bw = Math.max(1, w / n);
        g.clearRect(0, 0, w, h);
        for (let i = 0; i < n; i++) {
          const x = (i / n) * w, ph = Math.max(1, f.peaks[i] * (h * 0.9));
          g.fillStyle = i / n < pos ? played : rest;
          g.fillRect(x, mid - ph / 2, Math.ceil(bw), ph);
        }
      };
      const stopAudio = () => { if (audio) { audio.pause(); audio = null; } cancelAnimationFrame(raf); };

      const paintStage = () => {
        stopAudio();
        if (ro) { ro.disconnect(); ro = null; }
        const st = $("#as-stage"), f = cur();
        if (!f) {
          st.innerHTML = `<div style="margin:auto;max-width:440px">${FT.stateBlock("empty-assets", "Nothing to preview yet",
            "Drop a texture or sound to see it locally. Use it to judge how low texture levels look before you pick a preset.",
            `<button class="btn primary" id="as-pick3">${icon("folder", "sm")}Choose files</button>`)}</div>`;
          $("#as-pick3").onclick = () => $("#as-file").click();
          return;
        }
        if (f.kind === "image") {
          st.innerHTML = `<div class="center-bar"><h2 style="font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:36ch">${esc(f.name)}</h2>
              <span class="badge outline">${f.w} × ${f.h}</span><span class="grow"></span>
              <span class="label" id="lv-l">Texture level</span>${FT.seg("lvl", LEVELS, level, "Texture level")}</div>
            <div class="compare checker" id="as-cmp" style="--split:50%">
              <canvas class="before" role="img" aria-label="Original image"></canvas>
              <canvas class="after" role="img" aria-label="Image at texture level ${level}"></canvas>
              <div class="handle"><button type="button" id="as-h" role="slider" aria-label="Comparison divider" aria-valuemin="0" aria-valuemax="100" aria-valuenow="50">${icon("compare", "sm")}</button></div>
              <span class="tag l">Original</span><span class="tag r" id="as-tr">Level ${level}</span>
              <span class="note">Local approximation · not a Roblox render</span>
            </div>`;
          FT.bindSeg(st, "lvl", (v) => { level = +v; $("#as-tr").textContent = "Level " + level; drawImage(); paintInfo(); });
          const cmp = $("#as-cmp"), h = $("#as-h");
          let split = 50, drag = false;
          const set = (v) => { split = Math.max(0, Math.min(100, v)); cmp.style.setProperty("--split", split + "%"); h.setAttribute("aria-valuenow", String(Math.round(split))); };
          const fromX = (x) => { const r = cmp.getBoundingClientRect(); set(((x - r.left) / r.width) * 100); };
          cmp.addEventListener("pointerdown", (e) => { drag = true; cmp.setPointerCapture(e.pointerId); fromX(e.clientX); h.focus({ preventScroll: true }); });
          cmp.addEventListener("pointermove", (e) => { if (drag) fromX(e.clientX); });
          cmp.addEventListener("pointerup", () => (drag = false));
          cmp.addEventListener("pointercancel", () => (drag = false));
          h.addEventListener("keydown", (e) => {
            const s = e.shiftKey ? 10 : 2, m = { ArrowLeft: -s, ArrowDown: -s, ArrowRight: s, ArrowUp: s }[e.key];
            if (m) { e.preventDefault(); set(split + m); } else if (e.key === "Home") { e.preventDefault(); set(0); } else if (e.key === "End") { e.preventDefault(); set(100); }
          });
          ro = new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(drawImage, 100); });
          ro.observe(cmp);
          drawImage();
        } else {
          st.innerHTML = `<div class="center-bar"><h2 style="font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:40ch">${esc(f.name)}</h2>
              <span class="badge outline">${fmtDur(f.dur)}</span><span class="grow"></span></div>
            <div class="audio-stage">
              <canvas class="wave" id="as-wave" role="slider" tabindex="0" aria-label="Playback position" aria-valuemin="0" aria-valuemax="${Math.round(f.dur)}" aria-valuenow="0"></canvas>
              <div class="player"><button class="btn primary icon" id="as-play" aria-label="Play">${icon("play")}</button>
                <span class="time" id="as-time">0:00 / ${fmtDur(f.dur)}</span><span class="grow" style="flex:1"></span>
                <span class="hint">Space to play or pause · arrows to seek</span></div>
            </div>`;
          const wave = $("#as-wave"), play = $("#as-play"), time = $("#as-time");
          const el = new Audio(f.url);
          audio = el;
          const tick = () => {
            time.textContent = `${fmtDur(el.currentTime)} / ${fmtDur(f.dur)}`;
            wave.setAttribute("aria-valuenow", String(Math.round(el.currentTime)));
            drawWave(el.currentTime);
            if (!el.paused) raf = requestAnimationFrame(tick);
          };
          const setIcon = () => { play.innerHTML = icon(el.paused ? "play" : "pause"); play.setAttribute("aria-label", el.paused ? "Play" : "Pause"); };
          play.onclick = () => { if (el.paused) el.play().catch((e) => FT.toast("err", "Can't play this file", e.message)); else el.pause(); };
          el.onplay = () => { setIcon(); raf = requestAnimationFrame(tick); };
          el.onpause = el.onended = () => { setIcon(); tick(); };
          const seek = (t) => { el.currentTime = Math.max(0, Math.min(f.dur, t)); tick(); };
          wave.onclick = (e) => { const r = wave.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * f.dur); };
          wave.onkeydown = (e) => {
            if (e.key === "ArrowRight") { e.preventDefault(); seek(el.currentTime + 5); }
            else if (e.key === "ArrowLeft") { e.preventDefault(); seek(el.currentTime - 5); }
            else if (e.key === " " || e.key === "Enter") { e.preventDefault(); play.click(); }
          };
          ro = new ResizeObserver(() => drawWave(el.currentTime));
          ro.observe(wave);
          drawWave(0);
        }
      };
      const paintAll = () => { paintList(); paintStage(); paintInfo(); };

      const add = async (list) => {
        const recs = (await Promise.all(Array.from(list).map(loadFile))).filter(Boolean);
        if (!recs.length) return;
        files.push(...recs);
        selId = recs[0].id;
        paintAll();
      };
      $("#as-list").addEventListener("click", (e) => {
        const b = e.target.closest("button.tree-item");
        if (!b || b.dataset.id === selId) return;
        selId = b.dataset.id;
        paintAll();
      });
      const picker = $("#as-file");
      $("#as-pick").onclick = $("#as-pick2").onclick = () => picker.click();
      picker.onchange = () => { add(picker.files); picker.value = ""; };
      const drop = $("#as-drop"), stage = $("#as-stage");
      const over = (e) => { e.preventDefault(); drop.classList.add("over"); };
      const out = () => drop.classList.remove("over");
      const dropIt = (e) => { e.preventDefault(); out(); if (e.dataTransfer && e.dataTransfer.files.length) add(e.dataTransfer.files); };
      [drop, stage].forEach((el) => { el.addEventListener("dragover", over); el.addEventListener("dragleave", out); el.addEventListener("drop", dropIt); });
      const onKey = (e) => {
        if (e.key === " " && audio && !/^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(e.target.tagName) && e.target.id !== "as-wave") { e.preventDefault(); $("#as-play").click(); }
      };
      document.addEventListener("keydown", onKey);

      if (!selId && files[0]) selId = files[0].id;
      paintAll();
      return () => { stopAudio(); if (ro) ro.disconnect(); clearTimeout(timer); document.removeEventListener("keydown", onKey); };
    },
  };

  // =====================================================================
  // Diagnostics
  // =====================================================================
  PAGES.diagnostics = {
    render(page, q) {
      const S = FT.S;
      FT.setTop("Diagnostics", "Read-only checks · nothing in Roblox's folders is touched",
        `<button class="btn ghost" id="d-copy">${icon("copy", "sm")}Copy report</button>
         <button class="btn ghost" id="d-save">${icon("download", "sm")}Save report</button>
         <button class="btn primary" id="d-run">${icon("refresh", "sm")}Run checks</button>`);
      page.innerHTML = `<div class="diag">
        <div class="dash-col">
          <section class="card" aria-labelledby="h-checks"><div class="card-hd"><h3 id="h-checks">Checks</h3><span class="end dim" id="d-ran"></span></div><div id="d-checks"></div></section>
          <section class="card" id="log" aria-labelledby="h-log"><div class="card-hd"><h3 id="h-log">Activity log</h3><span class="end">
              ${FT.seg("lf", [["all", "All"], ["prob", "Problems"]], "all", "Log filter")}
              <button class="btn ghost icon sm" id="d-logr" aria-label="Reload log" data-tip="Reload">${icon("refresh", "sm")}</button></span></div>
            <div class="logbox" id="d-log" tabindex="0" aria-label="Activity log"></div></section>
        </div>
        <div class="dash-col">
          <section class="card" id="backups" aria-labelledby="h-bk"><div class="card-hd"><h3 id="h-bk">Backups</h3><span class="end dim">${plural(S.backup_count != null ? S.backup_count : S.backups.length, "backup")}</span></div>
            <div id="d-bk"></div>
            <div class="btn-row" style="margin-top:12px"><button class="btn danger sm" id="d-clear" ${FT.target() ? "" : "disabled"}>${icon("trash", "sm")}Remove all flags from target</button></div></section>
          <section class="card" aria-labelledby="h-st"><div class="card-hd"><h3 id="h-st">Storage</h3></div><div id="d-st"><div class="skel line"></div><div class="skel line"></div></div></section>
          <section class="card" aria-labelledby="h-faq"><div class="card-hd"><h3 id="h-faq">Common questions</h3></div>${[
            ["My flags don't seem to do anything", "Roblox reads ClientAppSettings.json only at start-up, and only honors flags on its allowlist. Close Roblox completely, then start it again. Firetier can confirm the file was written, but it can't see inside the game."],
            ["Bloxstrap or Fishstrap reset my flags", "Bootstrappers can rewrite the file from their own settings when they launch Roblox. Point Firetier at that bootstrapper's Modifications folder in Settings, or set the same flags inside the bootstrapper."],
            ["Why is my imported Fleasion file locked?", "Fleasion lists swap Roblox assets. Firetier stores them so you don't lose them, but it never replaces assets or touches Roblox's cache."],
            ["How do I undo everything?", "Restore the oldest backup above, or use Remove all flags from target. Every apply makes a backup first."],
          ].map(([qq, a]) => `<details class="faq"><summary>${icon("chevron-right", "sm")}${esc(qq)}</summary><div>${esc(a)}</div></details>`).join("")}</section>
        </div></div>`;

      // checks
      const paintChecks = (d) => {
        const box = $("#d-checks");
        if (!d) { box.innerHTML = `<div class="skel line"></div><div class="skel line"></div><div class="skel line"></div>`; return; }
        const n = (s) => d.checks.filter((c) => c.status === s).length;
        $("#d-ran").textContent = `${n("ok")} ok · ${n("warn")} warning · ${n("fail")} failed · ran ${FT.fmtTime(d.ran)}`;
        const order = { fail: 0, warn: 1, info: 2, ok: 3 };
        box.innerHTML = d.checks.slice().sort((a, b) => (order[FT.lvlOf(a.status)] - order[FT.lvlOf(b.status)])).map((c) => {
          const l = FT.lvlOf(c.status);
          return `<div class="check-row"><span class="lvl ${l}">${icon(FT.lvlIcon[l])}</span>
            <div><b>${esc(c.name)}</b><p>${esc(c.detail)}</p>${c.fix && l !== "ok" ? `<p class="fix">${icon("wrench", "sm")} ${esc(c.fix)}</p>` : ""}</div>
            <span class="badge ${l === "fail" ? "err" : l === "ok" ? "ok" : l}">${{ ok: "OK", warn: "Warning", fail: "Failed", info: "Info" }[l]}</span></div>`;
        }).join("");
      };
      const run = async () => {
        const b = $("#d-run");
        b.disabled = true; b.innerHTML = `<span class="spinner" style="width:14px;height:14px"></span>Running…`;
        paintChecks(null);
        try { FT.lastDiag = await api("diagnostics"); FT.paintShell(); paintChecks(FT.lastDiag); loadLog(); }
        catch (e) { $("#d-checks").innerHTML = FT.stateBlock("error-target", "Checks couldn't run", esc(e.message), "", true); }
        finally { b.disabled = false; b.innerHTML = `${icon("refresh", "sm")}Run checks`; }
      };
      $("#d-run").onclick = run;
      if (q.get("run") === "1" || !FT.lastDiag) run(); else paintChecks(FT.lastDiag);

      // report
      $("#d-copy").onclick = async () => { try { const r = await api("report"); FT.copy(r.content); } catch (e) { FT.fail(e); } };
      $("#d-save").onclick = async () => { try { const r = await api("report"); FT.download(r.filename, r.content, "text/plain"); } catch (e) { FT.fail(e); } };

      // log
      let entries = [], filter = "all";
      const paintLog = () => {
        const list = filter === "prob" ? entries.filter((e) => ["warn", "fail"].includes(FT.lvlOf(e.level))) : entries;
        $("#d-log").innerHTML = list.length
          ? list.map((e) => { const l = FT.lvlOf(e.level); return `<div class="ln ${l}"><span>${esc(e.time)}</span><span>${esc(String(e.level).toUpperCase().slice(0, 4))}</span><span>${esc(e.msg)}</span></div>`; }).join("")
          : FT.stateBlock("empty-log", filter === "prob" ? "No problems logged" : "Log is empty", filter === "prob" ? "Warnings and failures show up here." : "Actions like apply, restore and import are recorded here.");
      };
      const loadLog = async () => { try { entries = (await api("log?n=300")).entries; paintLog(); } catch (e) { $("#d-log").innerHTML = `<p class="hint err">${esc(e.message)}</p>`; } };
      FT.bindSeg($("#log"), "lf", (v) => { filter = v; paintLog(); });
      $("#d-logr").onclick = loadLog;
      loadLog();

      // backups
      const paintBackups = () => {
        const bk = FT.S.backups;
        $("#d-bk").innerHTML = bk.length ? bk.slice(0, 8).map((b, i) => `<div class="row" style="padding-left:0;padding-right:0">
            <span class="lvl ${b.existed ? "info" : ""}">${icon("backup")}</span>
            <div class="grow"><div class="title">${esc(FT.fmtDateTime(b.created))}${i === 0 ? ` <span class="badge outline" style="margin-left:4px">Latest</span>` : ""}</div>
              <div class="sub" title="${esc(b.target_path)}">${esc(b.reason)} · ${esc(b.target_label)}${b.existed ? "" : " · file didn't exist"}</div></div>
            <button class="btn sm" data-restore="${esc(b.id)}">${icon("undo", "sm")}Restore</button></div>`).join("")
          + (bk.length > 8 ? `<p class="hint" style="margin-top:8px">${bk.length - 8} older backups in the backups folder.</p>` : "")
          : `<p class="hint">No backups yet. Firetier makes one every time it writes the flags file.</p>`;
      };
      $("#d-bk").addEventListener("click", async (e) => {
        const b = e.target.closest("[data-restore]");
        if (!b) return;
        const rec = FT.S.backups.find((x) => x.id === b.dataset.restore);
        const ok = await FT.confirm("Restore this backup?", `<p>${esc(rec.target_label)} goes back to how it was on <b>${esc(FT.fmtDateTime(rec.created))}</b>${rec.existed ? "" : " (the file didn't exist then, so it will be removed)"}. Your current file is backed up first.</p>`, "Restore", false, "undo");
        if (!ok) return;
        try { const r = await api("restore", { id: rec.id }); await FT.refresh(); paintBackups(); loadLog(); FT.toast("ok", "Restored", r.message); } catch (err) { FT.fail(err); }
      });
      $("#d-clear").onclick = async () => {
        const t = FT.target();
        const ok = await FT.confirm("Remove all flags from the target?", `<p>This empties <span class="mono">${esc(t.path)}</span>. A backup is made first, so you can restore it from this page.</p>`, "Remove all flags", true, "trash");
        if (!ok) return;
        try { const r = await api("clear", {}); await FT.refresh(); paintBackups(); loadLog(); FT.toast(r.verified ? "ok" : "warn", r.verified ? "Flags removed" : "Removed, not verified", r.message); } catch (e) { FT.fail(e); }
      };
      paintBackups();

      // storage
      api("storage").then((st) => {
        const rows = [["profiles", "Profiles", "presets"], ["backups", "Backups", "backup"], ["trash", "Trash", "trash"], ["log", "Log", "terminal"]];
        $("#d-st").innerHTML = rows.map(([k, label, ic]) => {
          const v = st[k] || { bytes: 0, files: 0 };
          return `<div class="row" style="padding-left:0;padding-right:0"><span class="lvl">${icon(ic)}</span><div class="grow"><div class="title">${label}</div>
            <div class="sub" title="${esc(v.path || "")}">${plural(v.files, "file")} · ${FT.fmtBytes(v.bytes)}</div></div>
            ${k === "log" ? "" : `<button class="btn ghost icon sm" data-open="${k}" aria-label="Open ${label} folder" data-tip="Open folder">${icon("folder", "sm")}</button>`}</div>`;
        }).join("");
      }).catch((e) => { $("#d-st").innerHTML = `<p class="hint err">${esc(e.message)}</p>`; });
      $("#d-st").addEventListener("click", async (e) => {
        const b = e.target.closest("[data-open]");
        if (!b) return;
        try { await api("open", { which: b.dataset.open }); } catch (err) { FT.fail(err); }
      });

      const sec = q.get("sec");
      if (sec) requestAnimationFrame(() => { const el = document.getElementById(sec); if (el) el.scrollIntoView({ block: "start" }); });
    },
  };

  // =====================================================================
  // Settings
  // =====================================================================
  PAGES.settings = {
    render(page, q) {
      const S = FT.S, app = S.app;
      FT.setTop("Settings", "Saved on this PC in Firetier's folder");
      const secs = [["appearance", "Appearance", "sun"], ["account", "Roblox account", "user"], ["target", "Target file", "file"], ["applying", "Applying", "bolt"], ["performance", "Performance", "gauge"],
        ["storage", "Storage", "database"], ["privacy", "Privacy", "shield"], ["about", "Updates & about", "info"], ["advanced", "Advanced", "wrench"]];
      const custom = S.targets.find((t) => t.id === "custom");
      const targetRow = (t) => {
        const on = t.id === S.target_id;
        const st = t.error ? `<span class="badge err">${icon("x")}Unreadable</span>` : !t.writable ? `<span class="badge warn">${icon("alert")}Not writable</span>`
          : t.exists ? `<span class="badge ok">${plural(t.count, "flag")}</span>` : `<span class="badge outline">No file yet</span>`;
        return `<button type="button" class="card interactive ${on ? "selected" : ""}" role="radio" aria-checked="${on}" data-target="${esc(t.id)}"
            style="display:grid;grid-template-columns:20px minmax(0,1fr) auto;gap:12px;align-items:start;padding:14px 16px;text-align:left;color:inherit;font:inherit;width:100%">
          <span style="width:16px;height:16px;margin-top:2px;border-radius:50%;box-shadow:inset 0 0 0 ${on ? "5px var(--ac)" : "1.5px var(--line-strong)"}"></span>
          <span style="min-width:0"><b style="display:block;font-weight:600">${esc(t.label)}${t.version ? ` <span class="dim" style="font-weight:400">· ${esc(t.version)}</span>` : ""}</b>
            <span class="mono dim" style="display:block;overflow-wrap:anywhere;margin-top:2px">${esc(t.path)}</span>
            ${(t.notes || []).length ? `<span class="hint" style="display:block;margin-top:4px">${esc(t.notes.join(" "))}</span>` : ""}
            ${t.error ? `<span class="hint err" style="display:block;margin-top:4px">${esc(t.error)}</span>` : ""}</span>${st}</button>`;
      };

      page.innerHTML = `<div class="settings">
        <nav class="settings-nav" aria-label="Settings sections">${secs.map(([id, l, ic]) => `<a href="#/settings?sec=${id}" data-sec="${id}">${icon(ic, "sm")}${l}</a>`).join("")}</nav>
        <div>
          <section class="set-sec" id="appearance"><h2>Appearance</h2>
            <div class="set-row"><div class="txt"><b>Motion</b><span>“System” follows Windows' animation setting. “Reduced” turns off movement and keeps quick fades.</span></div>
              <div class="ctl">${FT.seg("motion", [["system", "System"], ["reduced", "Reduced"], ["full", "Full"]], S.prefs.motion, "Motion")}</div></div>
            <div class="set-row"><div class="txt"><b>Density</b><span>Compact tightens rows and tables.</span></div>
              <div class="ctl">${FT.seg("density", [["comfortable", "Comfortable"], ["compact", "Compact"]], S.prefs.density, "Density")}</div></div>
          </section>
          <section class="set-sec" id="account"><h2>Roblox account</h2>
            <p class="hint" style="margin-bottom:12px">Optional. Shows your Roblox name and avatar in Firetier. It doesn't change what gets applied.</p>
            <div id="s-acct"><div class="skel line"></div></div>
            <div class="callout" style="margin-top:14px">${icon("shield")}<div><b>What connecting sends</b><p>Only the name or ID you type, to Roblox's public users and thumbnails services over verified HTTPS. No password, cookie or sign-in is used or stored. Disconnect removes the saved name and avatar.</p></div></div>
          </section>
          <section class="set-sec" id="target"><h2>Target file</h2>
            <p class="hint" style="margin-bottom:12px">Where profiles are written. Firetier found these ClientAppSettings.json locations on this PC.</p>
            <div role="radiogroup" aria-label="Target file" id="s-targets" style="display:flex;flex-direction:column;gap:8px">${S.targets.map(targetRow).join("") || `<div class="callout warn">${icon("alert")}<div><b>No Roblox install found</b><p>Pick a file below, or install Roblox, Bloxstrap or Fishstrap first.</p></div></div>`}</div>
            <div class="field" style="margin-top:16px"><label for="s-custom">Custom file</label>
              <div class="btn-row" style="flex-wrap:nowrap"><input class="input mono" id="s-custom" placeholder="C:\\…\\ClientSettings\\ClientAppSettings.json" value="${esc(custom ? custom.path : "")}" spellcheck="false" style="flex:1">
                <button class="btn" id="s-cset">Set</button>${custom ? `<button class="btn ghost" id="s-cclr">Clear</button>` : ""}</div>
              <p class="hint" style="margin-top:4px">A full path ending in .json. Firetier creates the file on first apply.</p></div>
          </section>
          <section class="set-sec" id="applying"><h2>Applying</h2>
            <div class="set-row"><div class="txt"><b>Write mode</b><span id="s-mode-txt"></span></div>
              <div class="ctl">${FT.seg("mode", [["merge", "Merge"], ["replace", "Replace"]], S.mode, "Write mode")}</div></div>
            <div class="set-row"><div class="txt"><b>Backups</b><span>Every apply, clear and restore backs up the target first. ${plural(S.backup_count != null ? S.backup_count : S.backups.length, "backup")} kept.</span></div>
              <div class="ctl"><a class="btn sm" href="#/diagnostics?sec=backups">${icon("backup", "sm")}Manage</a></div></div>
          </section>
          <section class="set-sec" id="performance"><h2>Performance</h2>
            <p class="hint" style="margin-bottom:4px">These settings affect Firetier itself, not Roblox. In-game FPS depends on the flags you apply.</p>
            <div class="set-row"><div class="txt"><b>Preview quality</b><span>Fast renders the offline preview and Asset Studio at half resolution. Use it on slower PCs.</span></div>
              <div class="ctl">${FT.seg("preview_quality", [["full", "Full"], ["fast", "Fast"]], S.prefs.preview_quality, "Preview quality")}</div></div>
            <div class="set-row"><div class="txt"><b>Run checks at start-up</b><span>Runs the read-only diagnostics when Firetier opens and shows problems on the sidebar.</span></div>
              <div class="ctl"><label class="switch"><input type="checkbox" id="s-diag" ${S.prefs.diag_on_start ? "checked" : ""} aria-label="Run checks at start-up"><span class="track"><span></span></span></label></div></div>
          </section>
          <section class="set-sec" id="storage"><h2>Storage</h2>
            <div class="set-row"><div class="txt"><b>Firetier folder</b><span class="mono" style="overflow-wrap:anywhere">${esc(app.home)}</span></div>
              <div class="ctl"><button class="btn sm" data-open="home">${icon("folder", "sm")}Open</button></div></div>
            ${[["profiles", "Profiles", "One JSON file per profile you made or imported."], ["backups", "Backups", "Copies of the target taken before each write."],
               ["trash", "Trash", "Deleted profiles. Remove them here for good."], ["log", "Log", "firetier.log, kept in the Firetier folder."]]
              .map(([k, l, d]) => `<div class="set-row"><div class="txt"><b>${l} <span class="dim num" style="font-weight:400" data-size="${k}">…</span></b><span>${d}</span></div>
                <div class="ctl">${k === "log" ? `<a class="btn sm" href="#/diagnostics?sec=log">${icon("terminal", "sm")}View</a>` : `<button class="btn sm" data-open="${k}">${icon("folder", "sm")}Open</button>`}</div></div>`).join("")}
          </section>
          <section class="set-sec" id="privacy"><h2>Privacy</h2>
            <div class="set-row"><div class="txt"><b>Network</b><span>Firetier's window talks only to a local server on 127.0.0.1 that checks a random token created at each launch. The outside requests are the optional Roblox account lookup (only when you click Connect) and update checks to the GitHub repo you set under Updates.</span></div>
              <div class="ctl">${FT.account ? `<span class="badge outline">${icon("user")}Account linked</span>` : `<span class="badge ok">${icon("check")}Offline</span>`}</div></div>
            <div class="set-row"><div class="txt"><b>Telemetry</b><span>None. Nothing about you, your PC or your profiles is collected or sent.</span></div>
              <div class="ctl"><span class="badge outline">Off · no setting</span></div></div>
            <div class="set-row"><div class="txt"><b>Activity log</b><span>Applies, imports and restores are written to a local log so you can see what changed. It stays on this PC.</span></div>
              <div class="ctl"><a class="btn sm" href="#/diagnostics?sec=log">${icon("terminal", "sm")}View log</a></div></div>
            <div class="set-row"><div class="txt"><b>Links</b><span>“View source” and similar buttons open your default browser. Apart from the optional account lookup and update checks, Firetier doesn't fetch anything.</span></div></div>
          </section>
          <section class="set-sec" id="about"><h2>Updates &amp; about</h2>
            <div class="card" style="display:flex;gap:20px;align-items:center"><img src="assets/logo-128.png" alt="" width="64" height="64" style="border-radius:14px">
              <div style="min-width:0"><b style="font:650 20px var(--font-display)">${esc(app.name)} ${esc(app.version)}</b>
                <p class="dim" style="margin-top:2px">FastFlag profile manager · Python ${esc(app.python)}</p></div></div>
            <div class="field" style="margin-top:16px"><label for="s-up-repo">Update from GitHub repo</label>
              <div class="btn-row" style="flex-wrap:nowrap"><input class="input mono" id="s-up-repo" placeholder="owner/name" value="${esc(S.update.repo || "")}" spellcheck="false" autocomplete="off" maxlength="140" style="flex:1">
                <button class="btn" id="s-up-set">Save</button></div>
              <p class="hint" style="margin-top:4px">The repo that publishes Firetier releases, as owner/name. Leave it empty to turn updates off.</p></div>
            <div class="set-row"><div class="txt"><b>Check automatically</b><span>Checks the repo's latest release when Firetier opens, at most every 6 hours. Installing always waits for your click.</span></div>
              <div class="ctl"><label class="switch"><input type="checkbox" id="s-up-auto" ${S.update.auto ? "checked" : ""} aria-label="Check for updates automatically"><span class="track"><span></span></span></label></div></div>
            <div id="s-upd"></div>
            <div class="set-row"><div class="txt"><b>Roblox flag allowlist</b><span>Posted ${esc(app.allowlist_posted)} · last checked by the developer ${esc(app.allowlist_checked)}. ${S.allowlist.length} flags. Roblox can change it at any time; Firetier won't know until a new build ships.</span></div>
              <div class="ctl"><button class="btn sm" id="s-src">${icon("external", "sm")}View source</button></div></div>
            <div class="set-row"><div class="txt"><b>Game scope</b><span>${esc(app.game_scope_note)}</span></div></div>
            <div class="callout">${icon("shield")}<div><b>Verified updates. No telemetry.</b><p>Updates come only from the repo above, over verified HTTPS, and must match the release's SHA-256 before Firetier.exe is replaced. The previous build is kept as Firetier.old.exe. Firetier only reads and writes ClientAppSettings.json and its own folder. It never injects into Roblox, swaps assets or touches anti-cheat.</p></div></div>
          </section>
          <section class="set-sec" id="advanced"><h2>Advanced</h2>
            <div class="set-row"><div class="txt"><b>Classic interface</b><span>The older Tk window is still included. Start it with <span class="mono">Firetier.bat classic</span>. Both use the same profiles and backups.</span></div></div>
            <div class="set-row"><div class="txt"><b>Diagnostics report</b><span>A plain-text summary of targets, checks and recent log lines, for bug reports.</span></div>
              <div class="ctl"><a class="btn sm" href="#/diagnostics">${icon("diagnostics", "sm")}Open diagnostics</a></div></div>
            <div class="set-row"><div class="txt"><b>Reset preferences</b><span>Restores appearance, mode and target choice. Profiles and backups are kept.</span></div>
              <div class="ctl"><button class="btn danger sm" id="s-reset">${icon("undo", "sm")}Reset</button></div></div>
          </section>
        </div></div>`;

      const save = async (body, msg) => {
        try { await api("prefs", body); await FT.refresh(); if (msg) FT.toast("ok", msg); return true; } catch (e) { FT.fail(e); return false; }
      };
      ["motion", "density", "preview_quality"].forEach((k) => FT.bindSeg(page, k, (v) => save({ [k]: v })));
      const modeTxt = () => {
        $("#s-mode-txt").textContent = FT.S.mode === "replace"
          ? "Replace: the target ends up holding only this profile's flags. Flags set by other tools are removed (they stay in the backup)."
          : "Merge: this profile's flags are added or updated. Other flags already in the file are kept.";
      };
      modeTxt();
      FT.bindSeg(page, "mode", async (v) => { if (await save({ mode: v })) modeTxt(); });
      $("#s-diag").onchange = (e) => save({ diag_on_start: e.target.checked });
      $("#s-targets").addEventListener("click", async (e) => {
        const b = e.target.closest("[data-target]");
        if (!b || b.dataset.target === FT.S.target_id) return;
        if (await save({ target_id: b.dataset.target }, "Target changed")) FT.rerender();
      });
      $("#s-targets").addEventListener("keydown", (e) => {
        if (!["ArrowDown", "ArrowUp"].includes(e.key)) return;
        const all = $$("[data-target]", page), i = all.indexOf(document.activeElement);
        if (i < 0) return;
        e.preventDefault();
        all[(i + (e.key === "ArrowDown" ? 1 : all.length - 1)) % all.length].focus();
      });
      $("#s-cset").onclick = async () => {
        const v = $("#s-custom").value.trim();
        if (!v) { FT.toast("warn", "Enter a file path"); return; }
        if (await save({ custom_target: v }, "Custom target set")) FT.rerender();
      };
      if ($("#s-cclr")) $("#s-cclr").onclick = async () => { if (await save({ custom_target: "" }, "Custom target cleared")) FT.rerender(); };
      $$("[data-open]", page).forEach((b) => (b.onclick = async () => { try { await api("open", { which: b.dataset.open }); } catch (e) { FT.fail(e); } }));
      $("#s-reset").onclick = async () => {
        if (!(await FT.confirm("Reset preferences?", "<p>Appearance, write mode and target choice go back to defaults. Profiles and backups aren't touched.</p>", "Reset", true, "undo"))) return;
        try { await api("prefs/reset", {}); await FT.refresh(); FT.toast("ok", "Preferences reset"); FT.rerender(); } catch (e) { FT.fail(e); }
      };
      // Roblox account
      const acctBox = $("#s-acct");
      const paintAcct = () => {
        const a = FT.account;
        if (a) {
          acctBox.innerHTML = `<div class="card acct-card"><span class="av" style="${a.avatar_data ? `background-image:url('${a.avatar_data}')` : ""}"></span>
            <div class="who" style="flex:1;min-width:0"><b>${esc(a.display_name || a.name)}${a.verified_badge ? ` <span class="badge outline" style="vertical-align:middle">${icon("check")}Verified</span>` : ""}</b>
              <span>@${esc(a.name)} · user ID <span class="mono">${esc(a.user_id)}</span>${a.connected_at ? ` · connected ${FT.fmtAgo(a.connected_at)}` : ""}</span></div>
            <div class="btn-row"><button class="btn sm" id="s-acct-re" data-tip="Fetch the name and avatar again">${icon("refresh", "sm")}Refresh</button>
              <button class="btn ghost sm" id="s-acct-off">Disconnect</button></div></div>`;
          $("#s-acct-re").onclick = (e) => connect(a.user_id, e.currentTarget, "Account refreshed");
          $("#s-acct-off").onclick = async () => {
            try { await FT.disconnectAccount(); FT.toast("ok", "Disconnected", "The saved name and avatar were removed."); paintAcct(); } catch (e) { FT.fail(e); }
          };
        } else {
          const det = FT.detectedUserId;
          acctBox.innerHTML = `<div class="field"><label for="s-acct-q">Username or user ID</label>
              <div class="btn-row" style="flex-wrap:nowrap"><input class="input" id="s-acct-q" placeholder="e.g. Builderman or 156" value="${esc(det || "")}" spellcheck="false" autocomplete="off" maxlength="40" style="flex:1">
                <button class="btn primary" id="s-acct-go">${icon("link", "sm")}Connect</button></div>
              <p class="hint" style="margin-top:4px">${det ? `User ID <span class="mono">${esc(det)}</span> was read from your local Roblox logs. Check it's you, or type your username.` : "Your public profile name, not your password."}</p></div>`;
          const q = $("#s-acct-q");
          $("#s-acct-go").onclick = (e) => connect(q.value, e.currentTarget, "Connected");
          q.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("#s-acct-go").click(); } };
        }
      };
      const connect = async (query, btn, title) => {
        if (!String(query || "").trim()) { FT.toast("warn", "Enter a username or user ID"); return; }
        btn.classList.add("loading"); btn.disabled = true;
        try {
          const a = await FT.connectAccount(query);
          if (FT.fx) FT.fx.celebrate(btn);
          FT.toast("ok", `${title}: ${a.display_name || a.name}`, a.avatar_data ? "Name and avatar saved on this PC." : "Name saved. Roblox didn't return an avatar.");
          paintAcct();
        } catch (e) {
          FT.toast("err", "Couldn't connect", e.message);
          btn.classList.remove("loading"); btn.disabled = false;
        }
      };
      paintAcct();
      const key = () => (FT.account ? FT.account.user_id + ":" + FT.account.connected_at : "none:" + FT.detectedUserId);
      const before = key();
      FT.loadAccount().then(() => { if (key() !== before && document.body.contains(acctBox)) paintAcct(); }).catch(() => {});
      // Updates
      const updBox = $("#s-upd");
      const paintUpd = () => {
        if (!document.body.contains(updBox)) return;
        const u = FT.S.update, r = u.result;
        const when = u.checked ? `Last checked ${FT.fmtAgo(u.checked)}.` : "Not checked yet.";
        let status, ctl;
        if (!u.repo) { status = "Set a repo above to get updates."; ctl = ""; }
        else if (u.busy && u.progress) {
          const [d, t] = u.progress, pct = t ? Math.floor((d / t) * 100) : 0;
          status = `Downloading ${esc(r ? r.latest : "")}… ${FT.fmtBytes(d)} of ${FT.fmtBytes(t)}<span class="upd-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct}%"></span></span>`;
          ctl = "";
        } else if (r && r.available) {
          status = `<b class="upd-new">Firetier ${esc(r.latest)} is available</b> · you have ${esc(r.current)}.${r.published ? ` Published ${esc(r.published.slice(0, 10))}.` : ""}`
            + (r.notes ? `<span class="upd-notes">${esc(r.notes)}</span>` : "");
          ctl = u.can_install ? `<button class="btn primary sm" id="s-up-go">${icon("download", "sm")}Update &amp; restart</button>`
            : `<button class="btn sm" id="s-up-page">${icon("external", "sm")}Release page</button>`;
        } else if (r) { status = `Firetier ${esc(r.current)} is the latest version. ${when}`; ctl = `<button class="btn sm" id="s-up-chk">${icon("refresh", "sm")}Check now</button>`; }
        else { status = when; ctl = `<button class="btn sm" id="s-up-chk">${icon("refresh", "sm")}Check now</button>`; }
        updBox.innerHTML = `<div class="set-row"><div class="txt"><b>Status</b><span>${status}</span></div><div class="ctl">${ctl}</div></div>`
          + (r && r.available && !u.can_install ? `<p class="hint">This copy runs from its source files, so it can't replace itself. Download Firetier.exe from the release page.</p>` : "");
        const chk = $("#s-up-chk");
        if (chk) chk.onclick = async () => {
          chk.classList.add("loading"); chk.disabled = true;
          try { const v = await FT.checkUpdate(false); FT.toast(v.result && v.result.available ? "info" : "ok", v.result && v.result.available ? `Firetier ${v.result.latest} is available` : "Firetier is up to date"); }
          catch (e) { FT.toast("err", "Update check failed", e.message); }
          paintUpd();
        };
        const go = $("#s-up-go");
        if (go) go.onclick = async () => {
          if (!(await FT.confirm(`Update to Firetier ${r.latest}?`, "<p>Firetier downloads the new Firetier.exe, checks its SHA-256, replaces this one and restarts. Profiles, backups and settings are kept. The current build is saved as Firetier.old.exe.</p>", "Update & restart", false, "download"))) return;
          FT.installUpdate(paintUpd);
        };
        const pg = $("#s-up-page");
        if (pg) pg.onclick = async () => { try { await api("open-url", { url: r.page }); } catch (e) { FT.fail(e); } };
      };
      FT.paintUpdate = paintUpd;
      paintUpd();
      $("#s-up-set").onclick = async () => {
        const v = $("#s-up-repo").value.trim();
        if (await save({ update_repo: v }, v ? "Update repo saved" : "Updates turned off")) { paintUpd(); if (v) $("#s-up-chk") && $("#s-up-chk").click(); }
      };
      $("#s-up-repo").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("#s-up-set").click(); } };
      $("#s-up-auto").onchange = (e) => save({ update_auto: e.target.checked });
      $("#s-src").onclick = async () => { try { await api("open-url", { url: app.allowlist_source }); } catch (e) { FT.fail(e); } };
      api("storage").then((st) => {
        $$("[data-size]", page).forEach((el) => {
          const v = st[el.dataset.size] || { bytes: 0, files: 0 };
          el.textContent = el.dataset.size === "log" ? `· ${FT.fmtBytes(v.bytes)}` : `· ${plural(v.files, "file")}, ${FT.fmtBytes(v.bytes)}`;
        });
      }).catch(() => $$("[data-size]", page).forEach((el) => { el.textContent = "· size unavailable"; }));

      // scroll-spy + ?sec=
      const scroller = $("#scroll"), links = $$(".settings-nav a", page);
      const mark = (id) => links.forEach((a) => a.classList.toggle("on", a.dataset.sec === id));
      // `want` is the section last asked for. The final sections are too short to scroll to the top,
      // so at the bottom of the page the asked-for one stays highlighted while it's on screen.
      let want = null;
      links.forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); want = a.dataset.sec; const el = document.getElementById(want); if (el) el.scrollIntoView({ block: "start", behavior: FT.reducedMotion() ? "auto" : "smooth" }); mark(want); }));
      const spy = () => {
        const box = scroller.getBoundingClientRect(), top = box.top + 40;
        let id = secs[0][0];
        for (const [s] of secs) { const el = document.getElementById(s); if (el && el.getBoundingClientRect().top <= top) id = s; }
        if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2) {
          const w = want && document.getElementById(want), wt = w && w.getBoundingClientRect().top;
          id = w && wt >= box.top && wt < box.bottom ? want : secs[secs.length - 1][0];
        }
        mark(id);
      };
      scroller.addEventListener("scroll", spy, { passive: true });
      const sec = q.get("sec");
      if (sec && document.getElementById(sec)) requestAnimationFrame(() => { want = sec; document.getElementById(sec).scrollIntoView({ block: "start" }); mark(sec); });
      else mark(secs[0][0]);
      return () => scroller.removeEventListener("scroll", spy);
    },
  };
})();

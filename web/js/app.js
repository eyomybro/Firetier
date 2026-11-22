/* Firetier UI core: API client, router, shell, toasts, modals and shared flows. Screens live in pages-*.js. */
(function () {
  "use strict";
  const FT = (window.FT = window.FT || {});
  const PAGES = (window.FTPages = window.FTPages || {});

  // ---------- token + initial route ----------
  // The server opens us at /#t=<token>[&r=<route>]. Keep the token in sessionStorage and move to a clean route hash.
  (function readHash() {
    const raw = location.hash.replace(/^#/, "");
    if (!raw.startsWith("t=")) return;
    const q = new URLSearchParams(raw);
    sessionStorage.setItem("ft-token", q.get("t") || "");
    FT.deepLink = q.has("r");
    FT.flags = { onboard: q.get("onboard") === "1", modal: q.get("modal") || "" };
    history.replaceState(null, "", location.pathname + location.search + "#/" + (q.get("r") || "dashboard"));
  })();
  FT.flags = FT.flags || {};
  const TOKEN = sessionStorage.getItem("ft-token") || "";

  // ---------- small helpers ----------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (n, cls = "") => `<svg class="ic ${cls}" aria-hidden="true"><use href="assets/icons.svg#i-${n}"/></svg>`;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
  const toDate = (t) => (typeof t === "number" ? new Date(t * 1000) : new Date(t));
  function fmtTime(t) {
    const d = toDate(t);
    return isNaN(d) ? String(t) : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  function fmtDateTime(t) {
    const d = toDate(t);
    return isNaN(d) ? String(t) : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  function fmtAgo(t) {
    const s = (Date.now() - toDate(t).getTime()) / 1000;
    if (!isFinite(s)) return "";
    if (s < 60) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  }
  const fmtBytes = (b) => (b < 1024 ? b + " B" : b < 1048576 ? (b / 1024).toFixed(1) + " KB" : (b / 1048576).toFixed(1) + " MB");
  const lvlOf = (l) => ({ ok: "ok", warn: "warn", warning: "warn", fail: "fail", error: "fail", err: "fail", info: "info" }[String(l).toLowerCase()] || "info");
  const lvlIcon = { ok: "check", warn: "alert", fail: "x", info: "info" };
  Object.assign(FT, { esc, icon, $, $$, plural, fmtTime, fmtDateTime, fmtAgo, fmtBytes, lvlOf, lvlIcon });

  // ---------- API ----------
  async function api(path, body) {
    const opt = { method: body === undefined ? "GET" : "POST", headers: { "X-Firetier-Token": TOKEN } };
    if (body !== undefined) {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    let r;
    try {
      r = await fetch("/api/" + path, opt);
    } catch (e) {
      throw new Error("Firetier's local server isn't responding. Close this window and start Firetier again.");
    }
    let data = null;
    try { data = await r.json(); } catch (e) { /* non-JSON */ }
    if (!r.ok) throw new Error((data && data.error) || `Request failed (${r.status})`);
    return data;
  }
  FT.api = api;

  // ---------- toasts ----------
  function toast(kind, title, msg, ms) {
    const box = $("#toasts");
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.innerHTML = `${icon({ ok: "check-circle", warn: "alert", err: "x-circle", info: "info" }[kind] || "info")}
      <div><b>${esc(title)}</b>${msg ? `<p>${esc(msg)}</p>` : ""}</div>
      <button class="btn ghost icon sm" aria-label="Dismiss">${icon("x", "sm")}</button>`;
    const close = () => { el.classList.add("out"); setTimeout(() => el.remove(), 260); };
    el.querySelector("button").onclick = close;
    box.appendChild(el);
    while (box.children.length > 4) box.firstElementChild.remove();
    setTimeout(close, ms || (kind === "err" ? 9000 : 5200));
  }
  FT.toast = toast;
  FT.fail = (e) => toast("err", "Something went wrong", e && e.message ? e.message : String(e));

  // ---------- modal ----------
  function modal({ title, sub, body, wide, actions = [], onOpen, iconName, cls }) {
    const prev = document.activeElement;
    const scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.innerHTML = `<div class="modal ${wide ? "wide" : ""} ${cls || ""}" role="dialog" aria-modal="true" aria-labelledby="m-ttl">
      <div class="modal-hd">${iconName ? `<span class="lvl ${iconName[1] || "info"}">${icon(iconName[0])}</span>` : ""}
        <div><h3 id="m-ttl">${esc(title)}</h3>${sub ? `<p class="dim" style="margin-top:2px">${esc(sub)}</p>` : ""}</div>
        <div class="end"><button class="btn ghost icon sm" data-x aria-label="Close">${icon("x", "sm")}</button></div></div>
      <div class="modal-bd">${body || ""}</div>
      ${actions.length ? `<div class="modal-ft">${actions.map((a, i) => `<button class="btn ${a.cls || ""}" data-a="${i}">${a.icon ? icon(a.icon, "sm") : ""}${esc(a.label)}</button>`).join("")}</div>` : ""}
    </div>`;
    let done = false;
    const close = () => {
      if (done) return;
      done = true;
      document.removeEventListener("keydown", onKey, true);
      scrim.classList.add("closing");
      setTimeout(() => scrim.remove(), 240);
      if (prev && prev.focus) prev.focus();
    };
    function onKey(e) {
      if (e.key === "Escape") { e.stopPropagation(); close(); }
      if (e.key === "Tab") { // keep focus inside
        const f = $$("button:not(:disabled), input, select, textarea, a[href], [tabindex='0']", scrim).filter((x) => x.offsetParent);
        if (!f.length) return;
        const i = f.indexOf(document.activeElement);
        if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
      }
    }
    document.addEventListener("keydown", onKey, true);
    scrim.addEventListener("mousedown", (e) => { if (e.target === scrim) close(); });
    scrim.querySelector("[data-x]").onclick = close;
    actions.forEach((a, i) => {
      scrim.querySelector(`[data-a="${i}"]`).onclick = async (ev) => {
        const btn = ev.currentTarget;
        if (!a.onClick) return close();
        btn.classList.add("loading");
        try {
          const keep = await a.onClick(scrim, close);
          if (keep !== true) close();
        } catch (e) { FT.fail(e); }
        btn.classList.remove("loading");
      };
    });
    document.body.appendChild(scrim);
    const first = scrim.querySelector("[autofocus]") || scrim.querySelector(".modal-ft .btn.primary, .modal-ft .btn.danger") || scrim.querySelector("[data-x]");
    if (first) first.focus();
    if (onOpen) onOpen(scrim, close);
    return close;
  }
  FT.modal = modal;
  FT.confirm = (title, body, okLabel, danger, iconName) =>
    new Promise((res) => {
      let answered = false;
      const close = modal({
        title, body, iconName: iconName || (danger ? ["alert", "warn"] : null),
        actions: [
          { label: "Cancel", cls: "ghost", onClick: () => { answered = true; res(false); } },
          { label: okLabel || "Continue", cls: danger ? "danger" : "primary", onClick: () => { answered = true; res(true); } },
        ],
      });
      const obs = new MutationObserver(() => { if (!document.contains(obs.target) && !answered) { res(false); obs.disconnect(); } });
      setTimeout(() => { const s = $$(".scrim").pop(); if (s) { obs.observe(document.body, { childList: true }); obs.target = s; } }, 0);
      void close;
    });

  // ---------- downloads / clipboard ----------
  FT.download = (filename, content, type) => {
    const url = URL.createObjectURL(new Blob([content], { type: type || "application/json" }));
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  };
  FT.copy = async (text) => {
    try { await navigator.clipboard.writeText(text); return true; }
    catch (e) {
      const t = document.createElement("textarea");
      t.value = text; document.body.appendChild(t); t.select();
      const ok = document.execCommand("copy"); t.remove(); return ok;
    }
  };

  // ---------- state ----------
  FT.S = null;
  FT.target = () => FT.S && FT.S.targets.find((t) => t.id === FT.S.target_id);
  FT.allProfiles = () => (FT.S ? FT.S.presets.concat(FT.S.profiles) : []);
  FT.findProfile = (id) => FT.allProfiles().find((p) => p.id === id);
  FT.allow = () => new Map(FT.S.allowlist.map((a) => [a.flag, a]));

  function applyPrefs() {
    const p = FT.S.prefs, root = document.documentElement;
    if (p.motion === "system") delete root.dataset.motion; else root.dataset.motion = p.motion;
    root.dataset.density = p.density;
    try { localStorage.setItem("ft-motion", p.motion); } catch (e) { /* storage off: splash uses the default */ }
  }
  FT.reducedMotion = () => {
    const m = FT.S ? FT.S.prefs.motion : FT.bootMotion;
    return m === "reduced" || (m !== "full" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  };

  function paintShell() {
    const S = FT.S, t = FT.target();
    $("#nav-presets").textContent = S.presets.length + S.profiles.length;
    const dot = $("#target-dot");
    if (!t) {
      dot.className = "dot err";
      $("#target-name").textContent = "No target";
      $("#target-sub").textContent = "Choose one in Settings";
    } else {
      dot.className = "dot " + (t.error ? "err" : !t.writable ? "warn" : t.exists ? "ok" : "info");
      $("#target-name").textContent = t.label;
      $("#target-sub").textContent = t.error ? "File unreadable" : t.exists ? `${plural(t.count, "flag")} in file` : "No flags file yet";
    }
    $("#target-mini").setAttribute("data-tip", t ? `Writing to ${t.label}. Click to change.` : "Choose where profiles are written");
    const diag = FT.lastDiag;
    const n = diag ? diag.checks.filter((c) => c.status === "fail" || c.status === "warn").length : 0;
    $("#nav-diag").textContent = n ? String(n) : "";
    const up = S.update && S.update.result && S.update.result.available;
    const nu = $("#nav-upd");
    nu.textContent = up ? "New" : "";
    nu.title = up ? `Firetier ${S.update.result.latest} is available` : "";
  }

  // ---------- updates ----------
  // The server does the checking, downloading and SHA-256 verification; the page only asks and shows progress.
  FT.checkUpdate = async (quiet) => {
    const u = await api("update/check", { quiet: !!quiet });
    FT.S.update = u;
    paintShell();
    if (FT.paintUpdate) FT.paintUpdate();
    return u;
  };
  FT.installUpdate = async (paint) => {
    let polling = true;
    const poll = async () => {
      while (polling) {
        try { const u = await api("update"); if (polling) { FT.S.update = u; paint && paint(); } } catch (e) { /* keep waiting */ }
        await new Promise((r) => setTimeout(r, 300));
      }
    };
    const job = api("update/install", {});
    poll();
    let res;
    try { res = await job; }
    catch (e) {
      polling = false;
      FT.toast("err", "Update failed", e.message);
      try { FT.S.update = await api("update"); } catch (e2) { /* server gone */ }
      paint && paint();
      return;
    }
    polling = false;
    restartOverlay(res.version);
  };
  function restartOverlay(version) {
    const el = document.createElement("div");
    el.className = "upd-restart";
    el.setAttribute("role", "alertdialog");
    el.setAttribute("aria-live", "assertive");
    el.innerHTML = `<div class="upd-card">${icon("check-circle")}<b>Firetier ${esc(version)} is installed</b>
      <p>The SHA-256 matched. Restarting into the new version…</p></div>`;
    document.body.appendChild(el);
    // The new build opens its own window; this one belongs to the old server, which exits.
    setTimeout(() => {
      window.close();
      el.querySelector("p").textContent = "The new version opened in its own window. You can close this one.";
    }, 2500);
  }
  async function autoCheckUpdate() {
    const u = FT.S.update;
    if (!u || !u.repo || !u.auto || (u.checked && Date.now() / 1000 - u.checked < 6 * 3600)) return;
    try {
      const v = await FT.checkUpdate(true);
      if (v.result && v.result.available)
        FT.toast("info", `Firetier ${v.result.latest} is available`, "Open Settings › Updates & about to install it.", 9000);
    } catch (e) { /* offline or rate-limited: try again next launch */ }
  }

  // ---------- Roblox account (optional) ----------
  FT.account = null;
  FT.detectedUserId = null;
  function paintAccount() {
    const a = FT.account, chip = $("#acct-chip"), av = $("#acct-av");
    if (!chip) return;
    chip.classList.toggle("on", !!a);
    if (a && a.avatar_data) { av.style.backgroundImage = `url("${a.avatar_data}")`; av.innerHTML = ""; }
    else { av.style.backgroundImage = ""; av.innerHTML = icon("user", "sm"); }
    $("#acct-name").textContent = a ? a.display_name || a.name : "Roblox account";
    $("#acct-sub").textContent = a ? "@" + a.name : "Connect (optional)";
    chip.dataset.tip = a ? `Connected as @${a.name}. Click to manage.` : "Show your Roblox name and avatar (optional)";
  }
  FT.paintAccount = paintAccount;
  FT.loadAccount = async () => {
    const r = await api("account");
    FT.account = r.account;
    FT.detectedUserId = r.detected_user_id;
    paintAccount();
    return r;
  };
  FT.connectAccount = async (query) => {
    const r = await api("account/connect", { query });
    FT.account = r.account;
    paintAccount();
    return r.account;
  };
  FT.disconnectAccount = async () => {
    await api("account/disconnect", {});
    FT.account = null;
    paintAccount();
  };

  FT.refresh = async () => {
    FT.S = await api("state");
    applyPrefs();
    paintShell();
    return FT.S;
  };

  // ---------- page frame ----------
  FT.setTop = (title, sub, actions) => {
    $("#page-title").textContent = title;
    $("#page-sub").textContent = sub || "";
    $("#page-actions").innerHTML = actions || "";
    document.title = title + " · Firetier";
  };

  // Honest state chain shown wherever a profile is described.
  FT.ladder = (p, t) => {
    const steps = [`<span class="step ok">${icon("eye")}Offline preview</span>`];
    if (p.unsupported) {
      steps.push(`<span class="step ok">${icon("import")}Configuration imported</span>`);
      steps.push(`<span class="step err">${icon("x")}Live application unsupported</span>`);
      return `<div class="ladder">${steps.join("")}</div>`;
    }
    if (!t) steps.push(`<span class="step na">${icon("file")}No target</span>`);
    else if (p.total && p.present === p.total) steps.push(`<span class="step ok">${icon("check")}Written to ${esc(t.label)}</span>`);
    else if (p.present) steps.push(`<span class="step warn">${icon("alert")}${p.present}/${p.total} flags in file</span>`);
    else steps.push(`<span class="step na">${icon("file")}Not written yet</span>`);
    steps.push(p.ignored || p.invalid
      ? `<span class="step warn">${icon("alert")}${p.ignored + p.invalid} not honored</span>`
      : `<span class="step ok">${icon("shield")}Allowlisted</span>`);
    steps.push(`<span class="step na" data-tip="Firetier can't see inside Roblox">${icon("info")}In-game effect: not verified</span>`);
    return `<div class="ladder">${steps.join("")}</div>`;
  };

  FT.thumbFor = (p) => {
    if (p.builtin) return `assets/thumbs/${p.id}.svg`;
    if (p.unsupported || p.source_kind === "fleasion" || p.source_kind === "import" || p.source_kind === "imported") return "assets/thumbs/imported.svg";
    return "assets/thumbs/user.svg";
  };
  FT.kindOf = (p) => (p.builtin ? "builtin" : p.source_kind && p.source_kind !== "user" ? "imported" : "mine");

  FT.countBadges = (p) => {
    if (p.unsupported) return `<span class="badge err">${icon("lock")}Asset replacement · not applied</span>`;
    const out = [`<span class="badge ok">${p.active} honored</span>`];
    if (p.ignored) out.push(`<span class="badge warn">${p.ignored} ignored</span>`);
    if (p.invalid) out.push(`<span class="badge err">${p.invalid} invalid</span>`);
    if (p.disabled) out.push(`<span class="badge outline">${p.disabled} off</span>`);
    return out.join("");
  };

  // ---------- shared flows ----------
  FT.apply = async (id) => {
    const p = FT.findProfile(id), t = FT.target(), S = FT.S;
    if (!p) return;
    if (p.unsupported) {
      toast("warn", "Not applied", "Asset replacement imports are stored for reference only. Firetier never swaps Roblox assets.");
      return;
    }
    if (!t) { toast("warn", "No target selected", "Pick a target in Settings first."); location.hash = "#/settings"; return; }
    const notes = [];
    if (S.mode === "replace") notes.push(`<b>Replace mode:</b> every other flag in ${esc(t.label)} will be removed. A backup is made first.`);
    if (S.running && S.running.length) notes.push("Roblox is running. Flags load when Roblox starts, so restart it after applying.");
    if (p.ignored || p.invalid) notes.push(`${p.ignored + p.invalid} of this profile's flags aren't honored and will be skipped.`);
    if (notes.length) {
      const ok = await FT.confirm(`Apply “${p.name}”?`, `<p>Writes to <span class="mono">${esc(t.path)}</span></p>
        <div class="callout warn" style="margin-top:12px">${icon("alert")}<div>${notes.map((n) => `<p>${n}</p>`).join("")}</div></div>`,
        "Back up and apply", S.mode === "replace");
      if (!ok) return;
    }
    try {
      const r = await api("apply", { id });
      if (r.ok && r.verified && FT.fx) FT.fx.celebrate();
      if (r.ok && r.verified) toast("ok", "Written and verified", `${plural(r.written.length || r.written, "flag")} in ${t.label}. Restart Roblox to load them. In-game effect: not verified.`);
      else if (r.ok) toast("warn", "Written, not verified", r.message);
      else toast("err", r.rolled_back ? "Apply failed, rolled back" : "Apply failed", r.message);
      await FT.refresh();
      FT.rerender();
    } catch (e) { FT.fail(e); }
  };

  FT.importFlow = () => {
    modal({
      title: "Import a profile", sub: "Flat ClientAppSettings.json, a Firetier profile, or a Fleasion export.", wide: true,
      body: `<div class="drop" id="imp-drop" style="margin:0 0 12px">${icon("import", "lg")}<p style="margin-top:6px">Drop a .json file here or <a href="#" id="imp-pick">choose a file</a></p>
          <input type="file" id="imp-file" accept=".json,application/json" class="hidden"></div>
        <div class="field"><label for="imp-text">Or paste JSON</label><textarea class="input mono" id="imp-text" rows="8" placeholder='{ "DFIntTextureQualityOverride": 0 }'></textarea></div>
        <p class="hint" style="margin-top:8px">Imports are stored locally. Asset replacement lists are kept for reference and never applied.</p>`,
      actions: [{ label: "Cancel", cls: "ghost" }, {
        label: "Import", cls: "primary", icon: "import", onClick: async (m) => {
          const text = m.querySelector("#imp-text").value.trim();
          if (!text) { toast("warn", "Nothing to import", "Paste JSON or choose a file."); return true; }
          const r = await api("import", { text, name: m.dataset.fname || "Imported" });
          if (!r.profile) { toast("err", "Couldn't import", r.messages.join(" ")); return true; }
          await FT.refresh();
          if (r.supported && FT.fx) FT.fx.celebrate();
          if (r.supported) toast("ok", `Imported “${r.profile.name}”`, r.messages.join(" "));
          else toast("warn", `Stored “${r.profile.name}”, not applicable`, r.messages.join(" "));
          location.hash = "#/editor?id=" + r.profile.id;
        },
      }],
      onOpen: (m) => {
        const file = m.querySelector("#imp-file"), drop = m.querySelector("#imp-drop");
        const read = (f) => { if (!f) return; m.dataset.fname = f.name; f.text().then((t) => (m.querySelector("#imp-text").value = t)); };
        m.querySelector("#imp-pick").onclick = (e) => { e.preventDefault(); file.click(); };
        file.onchange = () => read(file.files[0]);
        drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
        drop.ondragleave = () => drop.classList.remove("over");
        drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); read(e.dataTransfer.files[0]); };
      },
    });
  };

  FT.newProfile = (from) => {
    const src = from && FT.findProfile(from);
    modal({
      title: src ? "Duplicate profile" : "New profile",
      body: `<div class="field"><label for="np-name">Name</label><input class="input" id="np-name" autofocus value="${esc(src ? src.name + " (copy)" : "My Rivals profile")}"></div>
        ${src ? "" : `<div class="field" style="margin-top:12px"><label for="np-from">Start from</label><select class="select" id="np-from"><option value="">Empty profile</option>${FT.allProfiles().filter((p) => !p.unsupported).map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")}</select></div>`}`,
      actions: [{ label: "Cancel", cls: "ghost" }, {
        label: src ? "Duplicate" : "Create", cls: "primary", onClick: async (m) => {
          const name = m.querySelector("#np-name").value.trim();
          if (!name) { toast("warn", "Name required"); return true; }
          const f = src ? src.id : m.querySelector("#np-from").value;
          const p = await api("profile/new", { name, from: f || undefined, game: "rivals" });
          await FT.refresh();
          toast("ok", `Created “${p.name}”`);
          location.hash = "#/editor?id=" + p.id;
        },
      }],
      onOpen: (m) => { const i = m.querySelector("#np-name"); i.focus(); i.select(); },
    });
  };

  FT.exportProfile = async (id, kind) => {
    try {
      const e = await api(`export?id=${encodeURIComponent(id)}&kind=${kind || "flat"}`);
      FT.download(e.filename, e.content);
      toast("ok", "Exported", e.filename);
    } catch (e) { FT.fail(e); }
  };

  FT.deleteProfile = async (id) => {
    const p = FT.findProfile(id);
    if (!p || !(await FT.confirm(`Delete “${p.name}”?`, "<p>The profile moves to Firetier's trash folder. Nothing in Roblox changes.</p>", "Move to trash", true))) return false;
    try {
      await api("profile/delete", { id });
      await FT.refresh();
      toast("ok", "Moved to trash", p.name);
      return true;
    } catch (e) { FT.fail(e); return false; }
  };

  // Lightweight popover menu anchored to a button.
  FT.menu = (anchor, items) => {
    $$(".menu").forEach((m) => m.remove());
    const m = document.createElement("div");
    m.className = "menu";
    m.setAttribute("role", "menu");
    m.innerHTML = items.map((it, i) => (it === "-" ? `<div class="menu-sep"></div>` :
      `<button class="menu-item ${it.danger ? "danger" : ""}" role="menuitem" data-i="${i}" ${it.disabled ? "disabled" : ""}>${icon(it.icon || "chevron-right", "sm")}${esc(it.label)}</button>`)).join("");
    document.body.appendChild(m);
    const r = anchor.getBoundingClientRect();
    const left = Math.min(r.right - m.offsetWidth, innerWidth - m.offsetWidth - 8);
    const top = r.bottom + m.offsetHeight + 6 > innerHeight ? r.top - m.offsetHeight - 6 : r.bottom + 6;
    m.style.left = Math.max(8, left) + "px"; m.style.top = top + "px"; m.style.position = "fixed";
    const close = () => { m.remove(); document.removeEventListener("mousedown", out, true); document.removeEventListener("keydown", key, true); };
    const out = (e) => { if (!m.contains(e.target)) close(); };
    const key = (e) => {
      const b = $$(".menu-item:not(:disabled)", m), i = b.indexOf(document.activeElement);
      if (e.key === "Escape") { close(); anchor.focus(); }
      else if (e.key === "ArrowDown") { e.preventDefault(); b[(i + 1) % b.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); b[(i - 1 + b.length) % b.length].focus(); }
    };
    document.addEventListener("mousedown", out, true);
    document.addEventListener("keydown", key, true);
    $$(".menu-item", m).forEach((b) => (b.onclick = () => { close(); items[+b.dataset.i].onClick(); }));
    const f = m.querySelector(".menu-item:not(:disabled)");
    if (f) f.focus();
  };

  // Segmented control: opts = [[value, label], ...]
  FT.seg = (name, opts, val, label) =>
    `<div class="seg" role="group" aria-label="${esc(label || name)}" data-seg="${name}">${opts.map(([v, l]) =>
      `<button type="button" data-v="${esc(v)}" aria-pressed="${String(v) === String(val)}">${l}</button>`).join("")}</div>`;
  FT.bindSeg = (root, name, fn) => {
    const s = root.querySelector(`[data-seg="${name}"]`);
    if (!s) return;
    s.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-v]");
      if (!b || b.disabled || b.getAttribute("aria-pressed") === "true") return;
      $$("button", s).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      fn(b.dataset.v);
    });
  };

  // Client mirror of engine.flag_kind / normalize_value / Rule.status (the server re-checks on save).
  const KIND_RE = /^(DF|F)(Flag|Int|String|Log)[A-Za-z0-9_]+$/, INT_RE = /^[+-]?\d+$/;
  FT.flagKind = (n) => { const m = KIND_RE.exec(n || ""); return m ? m[2] : null; };
  FT.normalize = (name, value) => {
    let v = typeof value === "boolean" ? (value ? "True" : "False") : String(value == null ? "" : value).trim();
    const k = FT.flagKind(name);
    if (k === "Flag" && /^(true|false)$/i.test(v)) return v.toLowerCase() === "true" ? "True" : "False";
    if ((k === "Int" || k === "Log") && INT_RE.test(v) && v.replace(/^[+-]/, "").length <= 20) return String(BigInt(v));
    return v;
  };
  FT.ruleStatus = (r, allow) => {
    if (!r.enabled) return ["disabled", "disabled"];
    const k = FT.flagKind(r.flag);
    if (!k) return ["invalid", "not a FastFlag name (must start with FFlag, DFFlag, FInt, DFInt, FString, DFString, FLog or DFLog)"];
    const v = FT.normalize(r.flag, r.value);
    if (k === "Flag" && v !== "True" && v !== "False") return ["invalid", "value must be True or False"];
    if ((k === "Int" || k === "Log") && (!INT_RE.test(v) || v.replace(/^[+-]/, "").length > 20)) return ["invalid", "value must be a whole number"];
    const a = allow.get(r.flag);
    if (!a) return ["ignored", "not on Roblox's allowlist: Roblox ignores it"];
    if (a.range) {
      const n = Number(v);
      if (n < a.range[0] || n > a.range[1]) return ["active", `${v} is outside the usual range ${a.range[0]}-${a.range[1]}`];
    }
    return ["active", "honored by Roblox"];
  };
  FT.statusBadge = (st, msg) => {
    if (st === "active" && msg !== "honored by Roblox") return `<span class="badge warn" data-tip="${esc(msg)}">${icon("alert")}Unusual value</span>`;
    return {
      active: `<span class="badge ok">${icon("check")}Honored</span>`,
      ignored: `<span class="badge warn" data-tip="${esc(msg)}">Ignored</span>`,
      invalid: `<span class="badge err" data-tip="${esc(msg)}">${icon("x")}Invalid</span>`,
      disabled: `<span class="badge outline">Off</span>`,
    }[st];
  };

  FT.stateBlock = (img, title, text, buttons, err) =>
    `<div class="state ${err ? "err" : ""}"><img src="assets/illus/${img}.svg" alt=""><h3>${esc(title)}</h3><p>${text}</p>${buttons ? `<div class="btn-row">${buttons}</div>` : ""}</div>`;

  // ---------- router ----------
  let current = null;
  function parseRoute() {
    const m = location.hash.match(/^#\/([a-z]+)(?:\?(.*))?$/);
    return { name: m && PAGES[m[1]] ? m[1] : "dashboard", q: new URLSearchParams((m && m[2]) || "") };
  }
  FT.route = parseRoute;
  async function render() {
    const r = parseRoute();
    if (current && current.leave && current.name !== r.name) {
      const ok = await current.leave();
      if (ok === false) { history.replaceState(null, "", current.hash); return; }
    }
    if (current && current.cleanup) current.cleanup();
    $$(".nav-item").forEach((a) => (a.dataset.route === r.name ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    const page = $("#page");
    const P = PAGES[r.name];
    page.className = "page" + (P.full ? " full" : "");
    page.style.animation = "none"; void page.offsetWidth; page.style.animation = "";
    $("#scroll").scrollTop = 0;
    current = { name: r.name, hash: location.hash, leave: P.leave, cleanup: null };
    try {
      const cleanup = await P.render(page, r.q);
      current.cleanup = cleanup || null;
    } catch (e) {
      page.innerHTML = FT.stateBlock("error-target", "This screen couldn't load", esc(e.message), `<button class="btn" id="retry">${icon("refresh", "sm")}Try again</button>`, true);
      $("#retry").onclick = () => FT.rerender();
    }
  }
  FT.rerender = render;
  window.addEventListener("hashchange", render);

  // ---------- global keys ----------
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      const s = $("[data-search]");
      if (s) { e.preventDefault(); s.focus(); s.select(); }
    }
  });
  $("#target-mini").onclick = () => (location.hash = "#/settings?sec=target");
  $("#acct-chip").onclick = () => (location.hash = "#/settings?sec=account");

  // heartbeat keeps the server alive while the window is open
  setInterval(() => { fetch("/api/ping", { headers: { "X-Firetier-Token": TOKEN } }).catch(() => {}); }, 5000);

  // ---------- onboarding (first run) ----------
  function onboarding() {
    const steps = [
      ["Pick a profile", "Start from <b>Rivals: No Textures</b> or <b>Max FPS</b>. Every flag in them is on Roblox's allowlist."],
      ["Check the preview", "The before/after view is an offline approximation. It is not a capture of Roblox."],
      ["Apply", "Firetier backs up your current flags file, writes the profile, then re-reads the file to verify it."],
      ["Restart Roblox", "Flags load when Roblox starts. Firetier can't see inside the game, so the in-game effect stays “not verified”."],
    ];
    modal({
      title: "", cls: "onboard-modal",
      body: `<div class="onboard" style="box-shadow:none;animation:none;width:100%">
        <div class="art" style="background-image:url(assets/illus/welcome.svg);background-size:contain;background-color:var(--s1)"></div>
        <div class="body"><div class="eyebrow">Welcome to Firetier</div><h2>FastFlag profiles for Rivals, done carefully</h2>
          <ol>${steps.map((s) => `<li><b style="color:var(--tx)">${s[0]}.</b> ${s[1]}</li>`).join("")}</ol>
          <div class="callout">${icon("shield")}<div><b>What Firetier doesn't do</b><p>No asset swapping, no injection, no anti-cheat bypass. The only network request is the optional Roblox account lookup you start yourself. It edits the same ClientAppSettings.json that Bloxstrap and Fishstrap use.</p></div></div>
          <div class="btn-row" style="margin-top:auto"><span class="dots"><i class="on"></i><i></i><i></i></span><span style="flex:1"></span>
            <button class="btn primary" data-go>Get started</button></div></div></div>`,
      wide: true,
      onOpen: (m, close) => {
        m.querySelector(".modal").style.width = "min(900px, 100%)";
        m.querySelector(".modal-hd").style.display = "none";
        m.querySelector(".modal-bd").style.padding = "0";
        m.querySelector("[data-go]").onclick = () => { localStorage.setItem("ft-onboarded", "1"); close(); };
      },
    });
  }

  // ---------- boot ----------
  // Each splash row reports a real start-up call; nothing is faked or padded except a short minimum display time.
  const withTimeout = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(() => r("timeout"), ms)),
    (FT.splash && FT.splash.skipped) || new Promise(() => {})]);
  async function boot() {
    const sp = FT.splash;
    if (boot.ran) return;
    boot.ran = true;
    if (!TOKEN) {
      sp.finish();
      $("#page").innerHTML = FT.stateBlock("error-target", "Open Firetier from its launcher", "This page needs the session token that Firetier.bat passes when it opens the window.", "", true);
      return;
    }
    sp.total(5);
    sp.step("engine", "Starting the local engine");
    try { await FT.refresh(); }
    catch (e) {
      sp.done("engine", "not responding", "warn");
      sp.finish();
      $("#page").innerHTML = FT.stateBlock("error-target", "Can't reach Firetier", esc(e.message), "", true);
      return;
    }
    const S = FT.S, t = FT.target();
    const ver = document.getElementById("splash-ver");
    if (ver) ver.textContent = `${S.app.name} ${S.app.version} · local only`;
    sp.done("engine", `${S.app.version} · 127.0.0.1`);
    sp.step("profiles", "Loading profiles");
    sp.done("profiles", `${S.presets.length} presets · ${plural(S.profiles.length, "custom profile")}`);
    sp.step("target", "Finding the flags file");
    sp.done("target", t ? t.label : "none found", t && !t.error ? "ok" : "warn");
    sp.step("account", "Roblox account");
    try {
      const r = await withTimeout(FT.loadAccount(), 2000);
      if (r === "timeout" || r === "skipped") sp.done("account", "skipped", "info");
      else if (r.account) { sp.done("account", "@" + r.account.name); sp.hello(r.account); }
      else sp.done("account", r.detected_user_id ? "seen in Roblox logs · not connected" : "not connected", "info");
    } catch (e) { sp.done("account", "unavailable", "info"); }
    sp.step("diag", "Health checks");
    if (S.prefs.diag_on_start) {
      const d = await withTimeout(api("diagnostics").then((d) => { FT.lastDiag = d; paintShell(); return d; }).catch(() => null), 2500);
      if (d && d !== "timeout" && d !== "skipped") {
        const bad = d.checks.filter((c) => c.status === "fail" || c.status === "warn").length;
        sp.done("diag", bad ? plural(bad, "issue") + " to review" : `${d.checks.length} passed`, bad ? "warn" : "ok");
      } else sp.done("diag", d === "timeout" || d === "skipped" ? "still running" : "couldn't run", "info");
    } else sp.done("diag", "off in Settings", "info");
    await render();
    await sp.finish();
    if (FT.flags.onboard || (!FT.deepLink && !localStorage.getItem("ft-onboarded"))) onboarding();
    if (FT.flags.modal === "import") FT.importFlow();
    if (FT.flags.modal === "apply") FT.apply(FT.S.last_profile);
    autoCheckUpdate();
  }
  FT.paintShell = paintShell;
  window.addEventListener("DOMContentLoaded", boot);
  if (document.readyState !== "loading") boot();
})();

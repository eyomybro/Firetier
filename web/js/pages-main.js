/* Dashboard, Game Library and Preset Library screens. */
(function () {
  "use strict";
  const FT = window.FT, PAGES = window.FTPages, { esc, icon, $, $$, plural, api } = FT;

  // ---------- shared preset card ----------
  function presetCard(p, t) {
    const kind = FT.kindOf(p);
    const tag = p.builtin ? `<span class="badge ac">${icon("lock")}Built-in</span>`
      : kind === "imported" ? `<span class="badge outline">${icon("import")}Imported</span>`
      : `<span class="badge outline">${icon("edit")}Mine</span>`;
    const inFile = !p.unsupported && t && p.total && p.present === p.total
      ? `<span class="badge ok" data-tip="Every flag in this profile is in ${esc(t.label)}">${icon("check")}In target file</span>` : "";
    const first = p.unsupported
      ? `<button class="btn sm" data-act="edit" data-id="${esc(p.id)}">${icon("eye", "sm")}Inspect</button>`
      : `<button class="btn primary sm" data-act="apply" data-id="${esc(p.id)}">${icon("bolt", "sm")}Apply</button>
         <button class="btn sm" data-act="edit" data-id="${esc(p.id)}">${icon(p.builtin ? "eye" : "edit", "sm")}${p.builtin ? "View" : "Edit"}</button>`;
    return `<article class="preset ${p.unsupported ? "locked" : ""}">
      <div class="thumb"><img src="${FT.thumbFor(p)}" alt="" loading="lazy">${tag}</div>
      <div class="body"><h3 title="${esc(p.name)}">${esc(p.name)}</h3>
        <p>${esc(p.description || (p.unsupported ? "Asset replacement list kept for reference." : "No description."))}</p>
        <div class="meta">${FT.countBadges(p)}${inFile}</div></div>
      <div class="foot">${first}
        <button class="btn ghost icon sm" data-act="more" data-id="${esc(p.id)}" aria-label="More actions for ${esc(p.name)}" data-tip="More">${icon("more", "sm")}</button></div>
    </article>`;
  }
  function moreMenu(btn, p) {
    FT.menu(btn, [
      { label: "Duplicate", icon: "copy", disabled: p.unsupported, onClick: () => FT.newProfile(p.id) },
      { label: "Export ClientAppSettings.json", icon: "export", disabled: p.unsupported, onClick: () => FT.exportProfile(p.id, "flat") },
      { label: p.unsupported ? "Export original import" : "Export Firetier profile", icon: "download", onClick: () => FT.exportProfile(p.id, p.unsupported ? "original" : "firetier") },
      "-",
      { label: "Move to trash", icon: "trash", danger: true, disabled: p.builtin, onClick: async () => { if (await FT.deleteProfile(p.id)) FT.rerender(); } },
    ]);
  }
  function bindCards(root) {
    root.addEventListener("click", (e) => {
      const b = e.target.closest("[data-act]");
      if (!b || !root.contains(b)) return;
      const p = FT.findProfile(b.dataset.id);
      if (!p) return;
      if (b.dataset.act === "apply") FT.apply(p.id);
      else if (b.dataset.act === "edit") location.hash = "#/editor?id=" + encodeURIComponent(p.id);
      else if (b.dataset.act === "more") moreMenu(b, p);
    });
  }
  FT.presetCard = presetCard;

  function runningCallout() {
    const S = FT.S;
    if (!S.running.length) return "";
    return `<div class="callout warn" style="margin-bottom:16px">${icon("alert")}<div><b>Roblox is running</b>
      <p>${esc(S.running.join(", "))} is open. Roblox reads flags only when it starts, so restart it after applying.</p></div></div>`;
  }
  FT.runningCallout = runningCallout;

  // ---------- Dashboard ----------
  PAGES.dashboard = {
    async render(page) {
      const S = FT.S, t = FT.target();
      const p = FT.findProfile(S.last_profile) || S.presets[0];
      const applied = t && p.total && p.present === p.total;
      FT.setTop("Dashboard", `Rivals FFA · ${t ? "writing to " + t.label : "no target selected"}`,
        `<button class="btn ghost" id="d-imp">${icon("import", "sm")}<span class="lbl">Import</span></button>
         <button class="btn" id="d-new">${icon("plus", "sm")}<span class="lbl">New profile</span></button>`);
      const minis = ["preset-rivals-notex", "preset-rivals-fps", "preset-balanced"].map(FT.findProfile).filter(Boolean);
      const latestBackup = S.backups[0];

      page.innerHTML = `${runningCallout()}
      <div class="dash">
        <div class="dash-col">
          <section class="hero" aria-labelledby="hero-ttl">
            <div class="art" style="background-image:url(assets/arena-1280.jpg)"></div>
            <div class="body">
              <div class="eyebrow">${applied ? "Applied profile" : "Suggested profile"}</div>
              <h2 id="hero-ttl">${esc(p.name)}</h2>
              <p class="muted">${esc(p.description || "")}</p>
              ${FT.ladder(p, t)}
              <div class="kv">
                <div><span class="eyebrow">Target</span><b>${t ? esc(t.label) : "None"}</b></div>
                <div><span class="eyebrow">Mode</span><b>${S.mode === "replace" ? "Replace" : "Merge"}</b></div>
                <div><span class="eyebrow">Flags</span><b>${p.active} honored${p.ignored + p.invalid ? ` · ${p.ignored + p.invalid} skipped` : ""}</b></div>
              </div>
              <div class="btn-row" style="margin-top:4px">
                <button class="btn primary lg" id="h-apply" ${p.unsupported ? "disabled" : ""}>${icon("bolt")}${applied ? "Apply again" : "Apply profile"}</button>
                <button class="btn lg" id="h-edit">${icon("compare")}Preview &amp; edit</button>
              </div>
            </div>
            <span class="ill">Illustration · not a Roblox screenshot</span>
          </section>

          <section class="card">
            <div class="card-hd"><h3>Target file</h3>
              <span class="end">${t ? `<span class="badge ${t.error ? "err" : t.writable ? "outline" : "warn"}">${esc(t.error ? "Unreadable" : t.writable ? t.kind : "Read-only")}</span>
                <button class="btn ghost sm" id="t-open">${icon("folder", "sm")}Open folder</button>` : ""}</span></div>
            ${!t ? FT.stateBlock("error-target", "No target selected", "Pick Fishstrap, Bloxstrap or the Roblox client folder in Settings.", `<a class="btn" href="#/settings?sec=target">Choose target</a>`)
              : t.error ? `<div class="callout err">${icon("x-circle")}<div><b>Couldn't read the file</b><p>${esc(t.error)}</p></div></div>`
              : `<div class="stat-row">
                  <div class="stat ok"><div class="v">${t.honored}</div><div class="l">Honored by Roblox</div></div>
                  <div class="stat ${t.ignored ? "warn" : ""}"><div class="v">${t.ignored}</div><div class="l">Ignored (not allowlisted)</div></div>
                  <div class="stat ${t.invalid ? "err" : ""}"><div class="v">${t.invalid}</div><div class="l">Invalid values</div></div>
                </div>
                <p class="hint mono" style="margin-top:12px;overflow-wrap:anywhere">${esc(t.path)}${t.exists ? "" : " · not created yet"}</p>`}
          </section>

          <div class="section-hd" style="margin:4px 0 -4px"><h2>Start from a preset</h2><a class="end" href="#/presets">All presets ${icon("chevron-right", "sm")}</a></div>
          <div class="mini-presets">${minis.map((m) => `<button class="mini-preset" data-id="${esc(m.id)}">
              <img src="${FT.thumbFor(m)}" alt=""><div><b>${esc(m.name)}</b><span>${plural(m.active, "flag")}${m.id === S.last_profile ? " · last used" : ""}</span></div></button>`).join("")}</div>
        </div>

        <div class="dash-col side">
          <section class="card">
            <div class="card-hd"><h3>Quick actions</h3></div>
            <div class="qa">
              <button id="qa-apply" ${p.unsupported || !t ? "disabled" : ""}>${icon("bolt")}<span>Apply last profile</span></button>
              <button id="qa-import">${icon("import")}<span>Import profile</span></button>
              <button id="qa-load" ${!t || !t.count ? "disabled" : ""}>${icon("file")}<span>Load from target</span></button>
              <button id="qa-diag">${icon("diagnostics")}<span>Run diagnostics</span></button>
              <button id="qa-folder" ${!t ? "disabled" : ""}>${icon("folder")}<span>Open target folder</span></button>
              <button id="qa-restore" ${!latestBackup ? "disabled" : ""}>${icon("undo")}<span>Restore last backup</span></button>
            </div>
          </section>
          <section class="card">
            <div class="card-hd"><h3>Health</h3><a class="end" href="#/diagnostics">Details ${icon("chevron-right", "sm")}</a></div>
            <div id="health"><div class="skel line"></div><div class="skel line"></div><div class="skel line" style="width:70%"></div></div>
          </section>
          <section class="card">
            <div class="card-hd"><h3>Activity</h3><a class="end" href="#/diagnostics?sec=log">Full log ${icon("chevron-right", "sm")}</a></div>
            <div class="activity">${S.activity.length ? S.activity.slice(0, 6).map((a) => {
              const l = FT.lvlOf(a.level);
              return `<div class="row"><time>${esc(String(a.time).slice(11, 16))}</time><span class="lvl ${l}">${icon(FT.lvlIcon[l])}</span>
                <span class="grow" style="font-size:var(--t-sm);color:var(--tx2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${esc(a.msg)}">${esc(a.msg.split("\n")[0])}</span></div>`;
            }).join("") : FT.stateBlock("empty-log", "Nothing yet", "Applies, imports and restores show up here.")}</div>
          </section>
        </div>
      </div>`;

      const go = (h) => () => (location.hash = h);
      $("#d-imp").onclick = $("#qa-import").onclick = FT.importFlow;
      $("#d-new").onclick = () => FT.newProfile();
      $("#h-apply").onclick = $("#qa-apply").onclick = () => FT.apply(p.id);
      $("#h-edit").onclick = go("#/editor?id=" + encodeURIComponent(p.id));
      $("#qa-diag").onclick = go("#/diagnostics?run=1");
      const openT = async () => { try { await api("open", { which: "target" }); } catch (e) { FT.fail(e); } };
      $("#qa-folder").onclick = openT;
      if ($("#t-open")) $("#t-open").onclick = openT;
      $("#qa-load").onclick = async () => {
        try { const d = await api("load-target", {}); await FT.refresh(); FT.toast("ok", "Loaded as a new profile", d.name); location.hash = "#/editor?id=" + d.id; }
        catch (e) { FT.fail(e); }
      };
      $("#qa-restore").onclick = async () => {
        const b = latestBackup;
        if (!(await FT.confirm("Restore the latest backup?", `<p>Puts <b>${esc(b.target_label)}</b> back the way it was at ${esc(FT.fmtDateTime(b.created))}.</p><p class="dim" style="margin-top:6px">${esc(b.reason || "")}</p><p class="hint" style="margin-top:10px">The current file is backed up first.</p>`, "Restore"))) return;
        try { const r = await api("restore", { id: b.id }); FT.toast(r.ok ? "ok" : "err", r.ok ? "Backup restored" : "Restore failed", r.message); await FT.refresh(); FT.rerender(); }
        catch (e) { FT.fail(e); }
      };
      $$(".mini-preset", page).forEach((b) => (b.onclick = go("#/editor?id=" + encodeURIComponent(b.dataset.id))));

      // Health: summarize diagnostics (cached for the session, refreshed on Diagnostics).
      const paintHealth = (d) => {
        const h = $("#health");
        if (!h) return;
        const order = { fail: 0, warn: 1, ok: 2, info: 3 };
        const checks = d.checks.slice().sort((a, b) => order[a.status] - order[b.status]).slice(0, 5);
        const bad = d.checks.filter((c) => c.status === "fail" || c.status === "warn").length;
        h.innerHTML = `<div class="health-row" style="padding-top:0"><span class="badge ${bad ? "warn" : "ok"}">${bad ? plural(bad, "issue") : "All checks passed"}</span>
            <span class="grow dim" style="font-size:var(--t-sm)">${d.checks.length} checks · ${esc(FT.fmtTime(d.ran))}</span></div>` +
          checks.map((c) => { const l = FT.lvlOf(c.status); return `<div class="health-row"><span class="lvl ${l}">${icon(FT.lvlIcon[l])}</span><span class="grow" title="${esc(c.detail)}">${esc(c.name)}</span></div>`; }).join("");
      };
      if (FT.lastDiag) paintHealth(FT.lastDiag);
      else api("diagnostics").then((d) => { FT.lastDiag = d; FT.paintShell(); paintHealth(d); })
        .catch((e) => { const h = $("#health"); if (h) h.innerHTML = `<p class="hint err">${esc(e.message)}</p>`; });
    },
  };

  // ---------- Game Library ----------
  PAGES.games = {
    async render(page, q) {
      const S = FT.S, t = FT.target();
      const st = { text: (q.get("q") || "").trim(), show: q.get("show") === "fav" ? "fav" : "all" };
      const g = S.games.find((x) => x.id === "rivals"), all = S.games.find((x) => x.id === "all");
      const rivalsProfiles = FT.allProfiles().filter((p) => p.game === "rivals" && !p.unsupported);
      const allProfiles = FT.allProfiles().filter((p) => p.game !== "rivals" && !p.unsupported);
      const favBtn = (id, name) => {
        const on = S.favorites.includes(id);
        return `<button class="btn icon sm fav" data-fav="${id}" aria-pressed="${on}" aria-label="Favorite ${esc(name)}" data-tip="${on ? "Favorited" : "Favorite"}">${icon("star", "sm")}</button>`;
      };
      // The same three facts hold for every game: Firetier only writes FastFlags, and it can't see inside Roblox.
      const compat = `<ul class="compat" aria-label="Compatibility">
        <li class="ok" data-tip="Allowlisted FastFlags are written to ClientAppSettings.json">${icon("check", "sm")}FastFlags: supported</li>
        <li class="off" data-tip="Firetier never swaps, uploads or replaces Roblox assets">${icon("x-circle", "sm")}Asset swaps: unsupported</li>
        <li class="unk" data-tip="Roblox decides what it honors. Firetier can't observe the game">${icon("info", "sm")}In-game effect: not verified</li></ul>`;
      FT.setTop("Games", "Organize profiles by game", `<button class="btn ghost" id="g-imp">${icon("import", "sm")}<span class="lbl">Import</span></button>`);
      page.innerHTML = `
      <div class="toolbar">
        <label class="input-wrap">${icon("search")}<input class="input" data-search id="g-q" placeholder="Search games, place IDs and profiles" aria-label="Search games"><span class="kbd">Ctrl K</span></label>
        ${FT.seg("show", [["all", "All games"], ["fav", `${icon("star", "sm")}Favorites`]], st.show, "Show")}
        <span class="grow"></span>
        <span class="dim" id="g-count" style="font-size:var(--t-sm)"></span>
      </div>
      <div id="g-empty"></div>
      <div class="games" id="g-cards">
        <article class="game-card" data-game="rivals">
          <div class="thumb" style="background-image:url(assets/arena-1280.jpg)"><span class="ill">Illustration · not a Roblox screenshot</span>
            ${favBtn("rivals", g.name)}</div>
          <div class="body">
            <div class="btn-row"><span class="badge ac">${icon("flame")}Featured</span><span class="badge outline">FFA FPS</span></div>
            <h2 style="font-size:24px">${esc(g.name)}</h2>
            <p class="muted">${esc(g.notes)}</p>
            <div class="meta">
              <div>Place ID<b class="num">${esc(g.place_id)}</b></div>
              <div>Profiles<b>${g.profiles}</b></div>
              <div>Best start<b>Rivals: No Textures</b></div>
            </div>
            ${compat}
            <div class="callout">${icon("info")}<div><b>Flags aren't per-game</b><p>${esc(S.app.game_scope_note)}</p></div></div>
            <div class="foot">
              <a class="btn primary" href="#/presets?game=rivals">${icon("presets", "sm")}Browse Rivals presets</a>
              <a class="btn" href="#/editor?id=preset-rivals-notex">${icon("compare", "sm")}Preview No Textures</a>
            </div>
          </div>
        </article>
        <article class="game-card small" data-game="all">
          <div class="body">
            <div class="btn-row"><span class="badge outline">${icon("games")}Every game</span>${favBtn("all", all.name)}</div>
            <h2 style="font-size:18px">${esc(all.name)}</h2>
            <p class="muted">General presets: balanced quality and graphics API choices (Vulkan, D3D11, OpenGL).</p>
            ${compat}
            <ul class="game-list" id="g-list"></ul>
            <div class="foot"><a class="btn" href="#/presets?game=all">${icon("presets", "sm")}Browse all</a></div>
          </div>
        </article>
      </div>
      <div id="g-rivals">
        <div class="section-hd"><h2>Profiles tagged Rivals</h2><span class="dim" id="g-rn"></span>
          <span class="end"><button class="btn ghost sm" id="g-new">${icon("plus", "sm")}New Rivals profile</button></span></div>
        <div class="preset-grid" id="g-grid"></div>
      </div>`;
      const qIn = $("#g-q"), cards = $("#g-cards");
      qIn.value = st.text;
      bindCards($("#g-grid"));
      const profHit = (p, s) => (p.name + " " + (p.description || "") + " " + (p.category || "")).toLowerCase().includes(s);
      const gameHit = (gm, s) => (gm.name + " " + (gm.notes || "") + " " + (gm.place_id || "")).toLowerCase().includes(s);
      // A query that names the game keeps its whole list; otherwise the list narrows to matching profiles.
      const pick = (gm, list, s) => (!s || gameHit(gm, s) ? list : list.filter((p) => profHit(p, s)));
      const paint = () => {
        const s = st.text.toLowerCase();
        const rows = [["rivals", g, rivalsProfiles], ["all", all, allProfiles]].map(([id, gm, list]) => {
          const shown = pick(gm, list, s);
          const vis = (st.show === "all" || FT.S.favorites.includes(id)) && (!s || gameHit(gm, s) || shown.length > 0);
          cards.querySelector(`[data-game="${id}"]`).classList.toggle("hidden", !vis);
          return { id, vis, shown };
        });
        const n = rows.filter((r) => r.vis).length;
        cards.classList.toggle("hidden", !n);
        cards.classList.toggle("solo", n === 1);
        $("#g-count").textContent = `${n} of ${rows.length} games`;
        const gen = rows[1].shown;
        $("#g-list").innerHTML = gen.slice(0, 7).map((p) => `<li><a href="#/editor?id=${encodeURIComponent(p.id)}">
            ${icon(p.builtin ? "lock" : "editor", "sm")}<span>${esc(p.name)}</span><b class="num">${plural(p.rules, "flag")}</b></a></li>`).join("")
          || `<li class="dim">No general profiles yet.</li>`;
        const riv = rows[0];
        $("#g-rivals").classList.toggle("hidden", !riv.vis);
        $("#g-rn").textContent = s && riv.shown.length !== rivalsProfiles.length ? `${riv.shown.length} of ${rivalsProfiles.length}` : String(rivalsProfiles.length);
        $("#g-grid").innerHTML = riv.shown.slice(0, 8).map((p) => presetCard(p, t)).join("");
        const empty = $("#g-empty");
        empty.innerHTML = n ? "" : st.show === "fav" && !s
          ? FT.stateBlock("empty-search", "No favorite games yet", "Star a game to keep it here.", `<button class="btn" data-clear>Show all games</button>`)
          : FT.stateBlock("empty-search", "No games match", s ? `Nothing matches “${esc(st.text)}”. Try a game name, place ID or profile name.` : "Try a different filter.", `<button class="btn" data-clear>Clear filters</button>`);
        const c = empty.querySelector("[data-clear]");
        if (c) c.onclick = () => {
          st.text = ""; st.show = "all"; qIn.value = "";
          $$("[data-seg=show] button", page).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === "all")));
          paint();
        };
      };
      qIn.oninput = (e) => { st.text = e.target.value.trim(); paint(); };
      FT.bindSeg(page, "show", (v) => { st.show = v; paint(); });
      $("#g-imp").onclick = FT.importFlow;
      $("#g-new").onclick = () => FT.newProfile();
      cards.addEventListener("click", async (e) => {
        const b = e.target.closest("[data-fav]");
        if (!b) return;
        const id = b.dataset.fav, on = b.getAttribute("aria-pressed") !== "true";
        const favs = FT.S.favorites.filter((x) => x !== id).concat(on ? [id] : []);
        b.setAttribute("aria-pressed", String(on));
        b.dataset.tip = on ? "Favorited" : "Favorite";
        try { await api("prefs", { favorites: favs }); FT.S.favorites = favs; if (st.show === "fav") paint(); }
        catch (err) { b.setAttribute("aria-pressed", String(!on)); FT.fail(err); }
      });
      paint();
    },
  };

  // ---------- Preset Library ----------
  PAGES.presets = {
    async render(page, q) {
      const S = FT.S, t = FT.target();
      const st = { text: "", kind: q.get("kind") || "all", game: q.get("game") || "any" };
      const all = FT.allProfiles();
      const counts = { all: all.length, builtin: 0, mine: 0, imported: 0 };
      all.forEach((p) => counts[FT.kindOf(p)]++);
      FT.setTop("Presets", `${plural(S.presets.length, "built-in preset")} · ${plural(S.profiles.length, "of yours", "of yours")}`,
        `<button class="btn ghost" id="p-imp">${icon("import", "sm")}<span class="lbl">Import</span></button>
         <button class="btn primary" id="p-new">${icon("plus", "sm")}<span class="lbl">New profile</span></button>`);
      const errs = S.profile_errors.length ? `<div class="callout err" style="margin-bottom:16px">${icon("x-circle")}<div><b>${plural(S.profile_errors.length, "profile file")} couldn't be read</b>
        <p>${S.profile_errors.map((e) => `${esc(e.file)}: ${esc(e.error)}`).join("<br>")}</p></div></div>` : "";
      page.innerHTML = `${errs}
        <div class="toolbar">
          <label class="input-wrap">${icon("search")}<input class="input" data-search id="p-q" placeholder="Search presets and flags" aria-label="Search presets"><span class="kbd">Ctrl K</span></label>
          ${FT.seg("kind", [["all", `All <span class="dim">${counts.all}</span>`], ["builtin", `Built-in <span class="dim">${counts.builtin}</span>`],
            ["mine", `Mine <span class="dim">${counts.mine}</span>`], ["imported", `Imported <span class="dim">${counts.imported}</span>`]], st.kind, "Filter by source")}
          <select class="select" id="p-game" aria-label="Filter by game" style="width:auto">
            <option value="any">Any game</option><option value="rivals">Roblox Rivals</option><option value="all">All Roblox games</option></select>
          <span class="grow"></span>
          <span class="dim" id="p-count" style="font-size:var(--t-sm)"></span>
        </div>
        <div class="preset-grid" id="p-grid"></div>`;
      $("#p-game").value = st.game;
      const grid = $("#p-grid");
      bindCards(grid);
      const paint = () => {
        const s = st.text.toLowerCase();
        const list = FT.allProfiles().filter((p) =>
          (st.kind === "all" || FT.kindOf(p) === st.kind) && (st.game === "any" || p.game === st.game) &&
          (!s || (p.name + " " + p.description + " " + (p.category || "")).toLowerCase().includes(s)));
        $("#p-count").textContent = `${list.length} shown`;
        grid.innerHTML = list.length ? list.map((p) => presetCard(p, t)).join("")
          : `<div style="grid-column:1/-1">${st.kind === "mine" && !s
            ? FT.stateBlock("empty-profiles", "No profiles of your own yet", "Duplicate a built-in preset or start from an empty profile.", `<button class="btn primary" data-new>${icon("plus", "sm")}New profile</button>`)
            : FT.stateBlock("empty-search", "No presets match", s ? `Nothing matches “${esc(st.text)}”. Try a flag name or clear the filters.` : "Try a different filter.", `<button class="btn" data-clear>Clear filters</button>`)}</div>`;
        const c = grid.querySelector("[data-clear]"), n = grid.querySelector("[data-new]");
        if (c) c.onclick = () => { st.text = ""; st.kind = "all"; st.game = "any"; $("#p-q").value = ""; $("#p-game").value = "any"; $$("[data-seg=kind] button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === "all"))); paint(); };
        if (n) n.onclick = () => FT.newProfile();
      };
      $("#p-q").oninput = (e) => { st.text = e.target.value.trim(); paint(); };
      $("#p-game").onchange = (e) => { st.game = e.target.value; paint(); };
      FT.bindSeg(page, "kind", (v) => { st.kind = v; paint(); });
      $("#p-imp").onclick = FT.importFlow;
      $("#p-new").onclick = () => FT.newProfile();
      paint();
    },
  };
})();

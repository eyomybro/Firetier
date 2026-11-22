/* Customization Editor: profile tree, live before/after preview, flag table and inspector. */
(function () {
  "use strict";
  const FT = window.FT, PAGES = window.FTPages, { esc, icon, $, $$, plural, api } = FT;
  let ED = null; // live editor state, also read by leave()

  const snap = () => JSON.stringify({ name: ED.w.name, description: ED.w.description, game: ED.w.game, rules: ED.w.rules });
  const restore = (s) => Object.assign(ED.w, JSON.parse(s));
  const isDirty = () => ED && snap() !== ED.saved;

  function effectiveFlags(allow) {
    const out = {};
    for (const r of ED.w.rules) {
      const [st] = FT.ruleStatus(r, allow);
      if (st === "active" || st === "ignored") out[r.flag] = FT.normalize(r.flag, r.value);
    }
    return out;
  }

  PAGES.editor = {
    full: true,
    async leave() {
      if (!isDirty()) return true;
      return FT.confirm("Discard unsaved changes?", `<p>Your edits to <b>${esc(ED.w.name)}</b> haven't been saved.</p>`, "Discard", true);
    },
    async render(page, q) {
      const S = FT.S, allow = FT.allow();
      const id = q.get("id") || S.last_profile || (S.presets[0] && S.presets[0].id);
      let detail;
      try { detail = await api("profile?id=" + encodeURIComponent(id)); }
      catch (e) {
        FT.setTop("Editor", "");
        page.innerHTML = `<div style="padding:32px">${FT.stateBlock("empty-search", "Profile not found", esc(e.message), `<a class="btn" href="#/presets">Open presets</a>`, true)}</div>`;
        return;
      }
      const ro = detail.builtin || detail.unsupported;
      ED = {
        d: detail, ro, sel: -1, undo: [], redo: [], tree: "", mode: "split", split: 50,
        w: { name: detail.name, description: detail.description || "", game: detail.game, rules: detail.rules_list.map((r) => ({ flag: r.flag, value: String(r.value), enabled: r.enabled })) },
      };
      ED.saved = snap();
      FT.setTop("Editor", detail.builtin ? "Built-in preset · read-only" : detail.unsupported ? "Imported asset list · reference only" : "Your profile");

      page.innerHTML = `<div class="editor">
        <aside class="dock left" aria-label="Profiles">
          <div class="dock-hd"><span class="eyebrow">Profiles</span><span class="end">
            <button class="btn ghost icon sm" id="e-new" aria-label="New profile" data-tip="New profile">${icon("plus", "sm")}</button>
            <button class="btn ghost icon sm" id="e-imp" aria-label="Import" data-tip="Import">${icon("import", "sm")}</button></span></div>
          <label class="input-wrap">${icon("search")}<input class="input" data-search id="e-q" placeholder="Filter profiles" aria-label="Filter profiles"><span class="kbd">Ctrl K</span></label>
          <div class="tree" id="e-tree" role="listbox" aria-label="Profiles"></div>
        </aside>
        <section class="center" aria-label="Preview and flags">
          <div class="center-bar" id="e-bar"></div>
          <div id="e-main" style="display:contents"></div>
        </section>
        <aside class="dock right" id="e-insp" aria-label="Inspector"></aside>
        <footer class="statusbar" id="e-status"></footer>
      </div>`;

      // ---------- tree ----------
      const paintTree = () => {
        const s = ED.tree.toLowerCase();
        const groups = [["Built-in", S.presets], ["My profiles", S.profiles.filter((p) => FT.kindOf(p) === "mine")], ["Imported", S.profiles.filter((p) => FT.kindOf(p) === "imported")]];
        $("#e-tree").innerHTML = groups.map(([label, list]) => {
          const items = list.filter((p) => !s || p.name.toLowerCase().includes(s));
          if (!items.length) return "";
          return `<div class="eyebrow">${label}</div>` + items.map((p) => `<button class="tree-item ${p.unsupported ? "locked" : ""}" role="option" data-id="${esc(p.id)}" aria-selected="${p.id === detail.id}">
            ${icon(p.unsupported ? "lock" : p.builtin ? "presets" : "file", "sm")}<span>${esc(p.id === detail.id ? ED.w.name : p.name)}</span><small>${p.rules}</small></button>`).join("");
        }).join("") || `<p class="hint" style="padding:12px 8px">No profiles match.</p>`;
      };
      $("#e-tree").onclick = async (e) => {
        const b = e.target.closest(".tree-item");
        if (!b || b.dataset.id === detail.id) return;
        if (isDirty() && !(await PAGES.editor.leave())) return;
        ED.saved = snap(); // discard accepted
        location.hash = "#/editor?id=" + encodeURIComponent(b.dataset.id);
      };
      $("#e-q").oninput = (e) => { ED.tree = e.target.value.trim(); paintTree(); };
      $("#e-new").onclick = () => FT.newProfile();
      $("#e-imp").onclick = FT.importFlow;

      // ---------- center bar ----------
      const paintBar = () => {
        const dirty = isDirty();
        const tag = detail.builtin ? `<span class="badge ac">${icon("lock")}Built-in</span>` : detail.unsupported ? `<span class="badge err">${icon("lock")}Not applicable</span>` : dirty ? `<span class="badge warn">Unsaved</span>` : `<span class="badge outline">Saved</span>`;
        $("#e-bar").innerHTML = `<h2 style="font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:32ch" title="${esc(ED.w.name)}">${esc(ED.w.name)}</h2>${tag}
          <span class="grow"></span>
          ${detail.unsupported ? "" : FT.seg("cmp", [["split", "Split"], ["side", "Side by side"], ["after", "After only"]], ED.mode, "Comparison layout")}
          <button class="btn ghost icon sm" id="e-undo" aria-label="Undo" data-tip="Undo (Ctrl Z)" ${ED.undo.length ? "" : "disabled"}>${icon("undo", "sm")}</button>
          <button class="btn ghost icon sm" id="e-redo" aria-label="Redo" data-tip="Redo (Ctrl Y)" ${ED.redo.length ? "" : "disabled"}>${icon("redo", "sm")}</button>
          ${ro ? "" : `<button class="btn sm" id="e-add">${icon("plus", "sm")}Add flag</button>`}
          ${detail.unsupported ? `<button class="btn sm" id="e-orig">${icon("export", "sm")}Export original</button>`
            : detail.builtin ? `<button class="btn sm" id="e-dup">${icon("copy", "sm")}Duplicate to edit</button>`
            : `<button class="btn sm" id="e-save" ${dirty ? "" : "disabled"}>${icon("check", "sm")}Save</button>`}
          <button class="btn primary sm" id="e-apply" ${detail.unsupported ? "disabled data-tip=\"Asset replacement is never applied\"" : ""}>${icon("bolt", "sm")}${dirty ? "Save &amp; apply" : "Apply"}</button>`;
        FT.bindSeg($("#e-bar"), "cmp", (v) => { ED.mode = v; layoutCompare(); });
        $("#e-undo").onclick = undo; $("#e-redo").onclick = redo;
        if ($("#e-add")) $("#e-add").onclick = addFlag;
        if ($("#e-save")) $("#e-save").onclick = save;
        if ($("#e-dup")) $("#e-dup").onclick = () => FT.newProfile(detail.id);
        if ($("#e-orig")) $("#e-orig").onclick = () => FT.exportProfile(detail.id, "original");
        $("#e-apply").onclick = async () => { if (isDirty() && !(await save())) return; FT.apply(detail.id); };
      };

      // ---------- main area ----------
      const main = $("#e-main");
      if (detail.unsupported) {
        const src = detail.source || {};
        main.innerHTML = `<div class="callout err">${icon("lock")}<div><b>Asset replacement list: stored, never applied</b>
            <p>This import swaps Roblox assets (textures, sounds, meshes). Firetier keeps it for reference only and never modifies Roblox files or cache.</p></div></div>
          <div class="card"><dl class="kv-list">
            <dt>Format</dt><dd>${esc(src.kind || "unknown")}</dd>
            <dt>Imported</dt><dd>${src.imported ? esc(FT.fmtDateTime(src.imported)) : "—"}</dd>
            <dt>Top-level keys</dt><dd class="mono">${esc((src.top_keys || []).join(", ") || "—")}</dd>
            <dt>Asset IDs</dt><dd>${src.asset_ids_counted || 0}</dd>
            <dt>Size</dt><dd>${FT.fmtBytes(src.bytes || 0)}</dd></dl></div>
          <div class="flags"><table class="table"><thead><tr><th>Path</th><th>Asset ID</th></tr></thead><tbody>
            ${(src.asset_ids_shown || []).map((a) => `<tr style="cursor:default"><td title="${esc(a.path)}">${esc(a.path)}</td><td class="val">${esc(a.value)}</td></tr>`).join("") || `<tr><td colspan="2" class="dim">No asset IDs found.</td></tr>`}
          </tbody></table></div>`;
      } else {
        main.innerHTML = `<div class="compare" id="cmp" style="--split:50%">
            <canvas class="before" aria-label="Preview with Roblox defaults" role="img"></canvas>
            <canvas class="after" aria-label="Preview with this profile" role="img"></canvas>
            <div class="handle"><button type="button" id="cmp-h" role="slider" aria-label="Comparison divider" aria-valuemin="0" aria-valuemax="100" aria-valuenow="50">${icon("compare", "sm")}</button></div>
            <span class="tag l" id="tag-l">Roblox defaults</span><span class="tag r">With this profile</span>
            <span class="note">Offline approximation · not a Roblox capture</span>
          </div>
          <div class="flags" id="e-flags"></div>`;
      }

      // ---------- preview ----------
      let timer = 0, ro2 = null;
      const drawCanvas = (c, params) => {
        const dpr = window.devicePixelRatio || 1, q2 = S.prefs.preview_quality === "fast" ? 0.5 : 1;
        let w = Math.round(c.clientWidth * dpr * q2), h = Math.round(c.clientHeight * dpr * q2);
        const cap = 1.2e6;
        if (w * h > cap) { const k = Math.sqrt(cap / (w * h)); w = Math.round(w * k); h = Math.round(h * k); }
        if (w < 2 || h < 2) return;
        if (c.width !== w || c.height !== h) { c.width = w; c.height = h; c._p = null; }
        const key = JSON.stringify(params);
        if (c._p === key) return;
        c._p = key;
        window.FTPreview.render(c, params);
      };
      const drawPreview = () => {
        const cmp = $("#cmp");
        if (!cmp) return;
        drawCanvas($("canvas.before", cmp), window.FTPreview.DEFAULT);
        drawCanvas($("canvas.after", cmp), window.FTPreview.fromFlags(effectiveFlags(allow), allow));
      };
      const schedulePreview = (ms) => { clearTimeout(timer); timer = setTimeout(drawPreview, ms == null ? 90 : ms); };
      const setSplit = (v) => {
        ED.split = Math.max(0, Math.min(100, v));
        const cmp = $("#cmp");
        cmp.style.setProperty("--split", ED.split + "%");
        $("#cmp-h").setAttribute("aria-valuenow", String(Math.round(ED.split)));
      };
      const layoutCompare = () => {
        const cmp = $("#cmp");
        if (!cmp) return;
        cmp.classList.toggle("side", ED.mode === "side");
        cmp.classList.toggle("single", ED.mode === "after");
        $("#tag-l").style.display = ED.mode === "after" ? "none" : "";
        schedulePreview(0);
      };
      if (!detail.unsupported) {
        const cmp = $("#cmp");
        let dragging = false;
        const fromX = (x) => { const r = cmp.getBoundingClientRect(); setSplit(((x - r.left) / r.width) * 100); };
        cmp.addEventListener("pointerdown", (e) => {
          if (ED.mode !== "split") return;
          dragging = true; cmp.setPointerCapture(e.pointerId); fromX(e.clientX);
          $("#cmp-h").focus({ preventScroll: true });
        });
        cmp.addEventListener("pointermove", (e) => { if (dragging) fromX(e.clientX); });
        const stop = () => (dragging = false);
        cmp.addEventListener("pointerup", stop);
        cmp.addEventListener("pointercancel", stop);
        $("#cmp-h").addEventListener("keydown", (e) => {
          const step = e.shiftKey ? 10 : 2;
          const m = { ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step }[e.key];
          if (m) { e.preventDefault(); setSplit(ED.split + m); }
          else if (e.key === "Home") { e.preventDefault(); setSplit(0); }
          else if (e.key === "End") { e.preventDefault(); setSplit(100); }
        });
        ro2 = new ResizeObserver(() => schedulePreview(120));
        ro2.observe(cmp);
      }

      // ---------- flags table ----------
      const paintFlags = () => {
        const box = $("#e-flags");
        if (!box) return;
        if (!ED.w.rules.length) {
          box.innerHTML = `<div class="flags-empty">${FT.stateBlock("empty-profiles", "No flags yet", "Add allowlisted flags to build this profile. The preview updates as you go.", ro ? "" : `<button class="btn primary" data-add>${icon("plus", "sm")}Add flag</button>`)}</div>`;
          const b = box.querySelector("[data-add]");
          if (b) b.onclick = addFlag;
          return;
        }
        box.innerHTML = `<table class="table"><thead><tr><th>Flag</th><th>Value</th><th>Status</th><th style="width:56px"><span class="sr-only">Enabled</span></th></tr></thead><tbody>
          ${ED.w.rules.map((r, i) => {
            const [st, msg] = FT.ruleStatus(r, allow);
            return `<tr data-i="${i}" class="${i === ED.sel ? "sel" : ""} ${r.enabled ? "" : "off"}" tabindex="0" aria-selected="${i === ED.sel}">
              <td title="${esc(r.flag)}">${esc(r.flag)}</td><td class="val">${esc(r.value === "" ? "—" : r.value)}</td><td>${FT.statusBadge(st, msg)}</td>
              <td><label class="switch" data-tip="${r.enabled ? "Turn off" : "Turn on"}"><input type="checkbox" data-en="${i}" ${r.enabled ? "checked" : ""} ${ro ? "disabled" : ""} aria-label="Enable ${esc(r.flag)}"><span class="track"><span></span></span></label></td></tr>`;
          }).join("")}</tbody></table>`;
      };
      const flagsBox = $("#e-flags");
      if (flagsBox) {
        flagsBox.addEventListener("click", (e) => {
          const en = e.target.closest("[data-en]");
          if (en) { e.stopPropagation(); return; }
          if (e.target.closest(".switch")) return;
          const tr = e.target.closest("tr[data-i]");
          if (tr) select(+tr.dataset.i);
        });
        flagsBox.addEventListener("change", (e) => {
          const en = e.target.closest("[data-en]");
          if (!en || ro) return;
          const before = snap();
          ED.w.rules[+en.dataset.en].enabled = en.checked;
          commit(before);
        });
        flagsBox.addEventListener("keydown", (e) => {
          const tr = e.target.closest("tr[data-i]");
          if (!tr || e.target !== tr) return;
          const i = +tr.dataset.i;
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(i); }
          else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            const n = Math.max(0, Math.min(ED.w.rules.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)));
            select(n);
            const row = flagsBox.querySelector(`tr[data-i="${n}"]`);
            if (row) row.focus();
          } else if ((e.key === "Delete" || e.key === "Backspace") && !ro) { e.preventDefault(); removeRule(i); }
        });
      }

      // ---------- inspector ----------
      const reportHtml = () => {
        const lv = (l) => FT.lvlOf(l);
        return `<div class="insp-grp"><div class="eyebrow">${icon("diagnostics", "sm")}Check${isDirty() ? ` <span class="badge warn" style="margin-left:auto">From last save</span>` : ""}</div>
          <div class="report">${(detail.report || []).map((r) => `<div><span style="color:var(--${{ fail: "err" }[lv(r.level)] || lv(r.level)})">${icon(FT.lvlIcon[lv(r.level)])}</span><span>${esc(r.text)}</span></div>`).join("") || `<div><span></span><span class="dim">Nothing to report.</span></div>`}</div></div>
          <div class="insp-grp"><div class="eyebrow">${icon("shield", "sm")}Where it stands</div>${FT.ladder(FT.findProfile(detail.id) || detail, FT.target())}</div>`;
      };
      const flagControl = (r, i) => {
        const k = FT.flagKind(r.flag), a = allow.get(r.flag), dis = ro ? "disabled" : "";
        if (k === "Flag") {
          const on = FT.normalize(r.flag, r.value) === "True";
          return `<label class="switch"><input type="checkbox" id="v-bool" ${on ? "checked" : ""} ${dis}><span class="track"><span></span></span><span>${on ? "True" : "False"}</span></label>`;
        }
        if ((k === "Int" || k === "Log") && a && a.range) {
          const [lo, hi] = a.range, n = Number(r.value), pct = isFinite(n) ? Math.max(0, Math.min(100, ((n - lo) / (hi - lo)) * 100)) : 0;
          return `<input type="range" class="range" id="v-range" min="${lo}" max="${hi}" step="1" value="${isFinite(n) ? n : lo}" style="--pct:${pct}%" aria-label="Value" ${dis}>
            <div class="btn-row"><input class="input mono" id="v-text" value="${esc(r.value)}" aria-label="Value" style="width:120px" ${dis}><span class="hint">Usual range ${lo}–${hi}</span></div>`;
        }
        return `<input class="input mono" id="v-text" value="${esc(r.value)}" aria-label="Value" ${k === "Int" || k === "Log" ? 'inputmode="numeric"' : ""} ${dis}>`;
      };
      const paintInspector = () => {
        const box = $("#e-insp");
        const games = S.games.map((g) => `<option value="${esc(g.id)}" ${g.id === ED.w.game ? "selected" : ""}>${esc(g.name)}</option>`).join("");
        let top;
        if (ED.sel >= 0 && ED.w.rules[ED.sel]) {
          const r = ED.w.rules[ED.sel], [st, msg] = FT.ruleStatus(r, allow), a = allow.get(r.flag);
          top = `<div class="insp-grp">
              <div class="eyebrow">${icon("sliders-h", "sm")}Flag<button class="btn ghost sm" id="i-back" style="margin-left:auto">${icon("chevron-right", "sm")}Profile</button></div>
              <div class="mono" style="font-size:13px;overflow-wrap:anywhere">${esc(r.flag)}</div>
              <div class="btn-row">${FT.statusBadge(st, msg)}<span class="badge outline">${esc(a ? a.group : "Not allowlisted")}</span></div>
              <p class="help">${esc((a && a.help) || (st === "ignored" ? "Roblox only reads flags on its allowlist. This one is skipped when applying." : st === "invalid" ? msg : "No description for this flag."))}</p>
            </div>
            <div class="insp-grp"><div class="eyebrow">Value</div>${flagControl(r, ED.sel)}
              ${st === "invalid" ? `<p class="hint err">${esc(msg)}</p>` : st === "active" && msg !== "honored by Roblox" ? `<p class="hint warn">${esc(msg)}</p>` : ""}
              <div class="set-row" style="padding:8px 0 0;border:0"><div class="txt"><b>Enabled</b><span>Off flags stay in the profile but aren't written.</span></div>
                <div class="ctl"><label class="switch"><input type="checkbox" id="v-en" ${r.enabled ? "checked" : ""} ${ro ? "disabled" : ""} aria-label="Enabled"><span class="track"><span></span></span></label></div></div>
              ${ro ? "" : `<button class="btn danger sm" id="v-del" style="align-self:flex-start">${icon("trash", "sm")}Remove flag</button>`}
            </div>`;
        } else {
          top = `<div class="insp-grp"><div class="eyebrow">${icon("edit", "sm")}Profile</div>
              ${detail.builtin ? `<div class="callout">${icon("lock")}<div><b>Built-in presets are read-only</b><p>Duplicate it to change flags. You can still apply it as-is.</p>
                <button class="btn sm" id="i-dup" style="margin-top:8px">${icon("copy", "sm")}Duplicate</button></div></div>` : ""}
              <div class="field"><label for="i-name">Name</label><input class="input" id="i-name" value="${esc(ED.w.name)}" maxlength="120" ${ro ? "disabled" : ""}></div>
              <div class="field"><label for="i-desc">Description</label><textarea class="input" id="i-desc" rows="3" ${ro ? "disabled" : ""}>${esc(ED.w.description)}</textarea></div>
              <div class="field"><label for="i-game">Game tag</label><select class="select" id="i-game" ${ro ? "disabled" : ""}>${games}</select>
                <p class="hint" style="margin-top:4px">A label for organizing. Roblox applies flags to every game.</p></div>
              ${detail.created ? `<p class="hint">Created ${esc(FT.fmtDateTime(detail.created))}${detail.modified ? ` · modified ${esc(FT.fmtAgo(detail.modified))}` : ""}</p>` : ""}
              ${detail.unsupported ? "" : `<p class="hint">Select a flag in the table to edit it.</p>`}
            </div>`;
        }
        box.innerHTML = top + reportHtml();
        bindInspector();
      };
      function bindInspector() {
        const on = (sel, ev, fn) => { const el = $(sel); if (el) el.addEventListener(ev, fn); };
        on("#i-back", "click", () => select(-1));
        on("#i-dup", "click", () => FT.newProfile(detail.id));
        let pre = null;
        const begin = () => { if (pre === null) pre = snap(); };
        const end = () => { if (pre !== null) { const b = pre; pre = null; commit(b, true); } };
        const live = () => { paintFlags(); paintStatus(); paintBar(); schedulePreview(); };
        on("#i-name", "focus", begin); on("#i-name", "input", (e) => { begin(); ED.w.name = e.target.value; paintBar(); paintTree(); }); on("#i-name", "change", end);
        on("#i-desc", "focus", begin); on("#i-desc", "input", (e) => { begin(); ED.w.description = e.target.value; }); on("#i-desc", "change", end);
        on("#i-game", "change", (e) => { const b = snap(); ED.w.game = e.target.value; commit(b, true); });
        const r = ED.w.rules[ED.sel];
        if (!r) return;
        on("#v-bool", "change", (e) => { const b = snap(); r.value = e.target.checked ? "True" : "False"; e.target.parentElement.lastElementChild.textContent = r.value; commit(b, true); });
        on("#v-range", "pointerdown", begin); on("#v-range", "keydown", begin);
        on("#v-range", "input", (e) => {
          begin(); r.value = e.target.value;
          const t = $("#v-text"); if (t) t.value = r.value;
          const a = allow.get(r.flag); e.target.style.setProperty("--pct", ((r.value - a.range[0]) / (a.range[1] - a.range[0])) * 100 + "%");
          live();
        });
        on("#v-range", "change", end);
        on("#v-text", "focus", begin);
        on("#v-text", "input", (e) => {
          begin(); r.value = e.target.value;
          const rg = $("#v-range"), a = allow.get(r.flag);
          if (rg && a && /^-?\d+$/.test(r.value)) { rg.value = r.value; rg.style.setProperty("--pct", Math.max(0, Math.min(100, ((r.value - a.range[0]) / (a.range[1] - a.range[0])) * 100)) + "%"); }
          live();
        });
        on("#v-text", "change", (e) => { r.value = FT.normalize(r.flag, e.target.value); e.target.value = r.value; end(); paintInspector(); });
        on("#v-en", "change", (e) => { const b = snap(); r.enabled = e.target.checked; commit(b); });
        on("#v-del", "click", () => removeRule(ED.sel));
      }

      // ---------- status bar ----------
      const paintStatus = () => {
        let a = 0, ig = 0, inv = 0, off = 0;
        ED.w.rules.forEach((r) => { const [st] = FT.ruleStatus(r, allow); if (st === "active") a++; else if (st === "ignored") ig++; else if (st === "invalid") inv++; else off++; });
        const t = FT.target();
        $("#e-status").innerHTML = detail.unsupported
          ? `<span>${icon("lock", "sm")}Reference only</span><span class="end">${(detail.source && detail.source.asset_ids_counted) || 0} asset IDs</span>`
          : `<span>${plural(ED.w.rules.length, "flag")}</span><span><i class="dot ok"></i>${a} honored</span>${ig ? `<span><i class="dot warn"></i>${ig} ignored</span>` : ""}${inv ? `<span><i class="dot err"></i>${inv} invalid</span>` : ""}${off ? `<span>${off} off</span>` : ""}
            ${isDirty() ? `<span class="dirty">${icon("edit", "sm")}Unsaved changes · Ctrl S</span>` : ""}
            <span class="end">${t ? `${esc(t.label)} · ${FT.S.mode === "replace" ? "replace" : "merge"}` : "No target"}</span>`;
      };

      // ---------- edits ----------
      function update(keepInspector) {
        paintBar(); paintFlags(); paintStatus(); paintTree(); schedulePreview();
        if (!keepInspector) paintInspector();
      }
      function commit(before, keepInspector) {
        if (before === snap()) { paintBar(); return; }
        ED.undo.push(before); if (ED.undo.length > 100) ED.undo.shift();
        ED.redo = [];
        update(keepInspector);
      }
      function undo() { if (!ED.undo.length) return; ED.redo.push(snap()); restore(ED.undo.pop()); if (ED.sel >= ED.w.rules.length) ED.sel = -1; update(); }
      function redo() { if (!ED.redo.length) return; ED.undo.push(snap()); restore(ED.redo.pop()); if (ED.sel >= ED.w.rules.length) ED.sel = -1; update(); }
      function select(i) {
        ED.sel = i;
        $$("#e-flags tr[data-i]").forEach((tr) => { const s = +tr.dataset.i === i; tr.classList.toggle("sel", s); tr.setAttribute("aria-selected", String(s)); });
        paintInspector();
      }
      function removeRule(i) {
        const b = snap(), f = ED.w.rules[i].flag;
        ED.w.rules.splice(i, 1);
        ED.sel = -1;
        commit(b);
        FT.toast("info", "Flag removed", `${f} · Ctrl Z to undo`, 3500);
      }
      function addFlag() {
        const have = new Set(ED.w.rules.map((r) => r.flag)), groups = new Map();
        S.allowlist.filter((a) => !have.has(a.flag)).forEach((a) => { if (!groups.has(a.group)) groups.set(a.group, []); groups.get(a.group).push(a); });
        FT.modal({
          title: "Add a flag", sub: "Only allowlisted flags are honored by Roblox.",
          body: `<div class="field"><label for="af-pick">Allowlisted flag</label><select class="select" id="af-pick"><option value="">Choose…</option>
              ${[...groups].map(([g, list]) => `<optgroup label="${esc(g)}">${list.map((a) => `<option value="${esc(a.flag)}">${esc(a.flag)}</option>`).join("")}</optgroup>`).join("")}</select></div>
            <p class="help hint" id="af-help" style="margin-top:6px;min-height:18px"></p>
            <div class="field" style="margin-top:12px"><label for="af-custom">Or type a flag name</label><input class="input mono" id="af-custom" placeholder="FIntExampleFlag" spellcheck="false">
              <p class="hint warn" id="af-warn" style="margin-top:4px"></p></div>`,
          actions: [{ label: "Cancel", cls: "ghost" }, {
            label: "Add", cls: "primary", icon: "plus", onClick: (m) => {
              const flag = (m.querySelector("#af-custom").value.trim() || m.querySelector("#af-pick").value).trim();
              if (!flag) { FT.toast("warn", "Pick a flag first"); return true; }
              if (have.has(flag)) { FT.toast("warn", "Already in this profile", flag); return true; }
              const k = FT.flagKind(flag), a = allow.get(flag);
              const value = k === "Flag" ? "True" : k === "Int" || k === "Log" ? String(a && a.range ? a.range[0] : 0) : "";
              const b = snap();
              ED.w.rules.push({ flag, value, enabled: true });
              ED.sel = ED.w.rules.length - 1;
              commit(b);
              const row = $(`#e-flags tr[data-i="${ED.sel}"]`); if (row) row.scrollIntoView({ block: "nearest" });
            },
          }],
          onOpen: (m) => {
            const pick = m.querySelector("#af-pick"), cus = m.querySelector("#af-custom");
            pick.focus();
            pick.onchange = () => { const a = allow.get(pick.value); m.querySelector("#af-help").textContent = a ? a.help || a.group : ""; };
            cus.oninput = () => {
              const f = cus.value.trim(), w = m.querySelector("#af-warn");
              w.textContent = !f ? "" : !FT.flagKind(f) ? "Not a FastFlag name. It will be marked invalid." : !allow.has(f) ? "Not on Roblox's allowlist. Roblox will ignore it." : "";
            };
          },
        });
      }
      async function save() {
        if (ro) return false;
        if (!ED.w.name.trim()) { FT.toast("warn", "Name required"); return false; }
        try {
          const d = await api("profile/save", { profile: { id: detail.id, name: ED.w.name.trim(), description: ED.w.description, category: detail.category, game: ED.w.game, rules: ED.w.rules } });
          detail = ED.d = d;
          ED.w.rules = d.rules_list.map((r) => ({ flag: r.flag, value: String(r.value), enabled: r.enabled }));
          ED.w.name = d.name;
          ED.saved = snap();
          await FT.refresh();
          FT.toast("ok", "Saved", `${d.name} · ${plural(d.rules_list.length, "flag")}`);
          update();
          return true;
        } catch (e) { FT.fail(e); return false; }
      }

      // ---------- keys ----------
      const onKey = (e) => {
        if (document.querySelector(".scrim")) return;
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
        const k = e.key.toLowerCase();
        if ((e.ctrlKey || e.metaKey) && k === "s") { e.preventDefault(); if (!ro && isDirty()) save(); }
        else if ((e.ctrlKey || e.metaKey) && !typing && k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
        else if ((e.ctrlKey || e.metaKey) && !typing && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); redo(); }
      };
      document.addEventListener("keydown", onKey);
      const onUnload = (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } };
      window.addEventListener("beforeunload", onUnload);

      paintTree(); paintBar(); paintFlags(); paintInspector(); paintStatus(); layoutCompare();
      const sel = $(`#e-tree [aria-selected="true"]`); if (sel) sel.scrollIntoView({ block: "nearest" });

      return () => {
        document.removeEventListener("keydown", onKey);
        window.removeEventListener("beforeunload", onUnload);
        if (ro2) ro2.disconnect();
        clearTimeout(timer);
      };
    },
  };
})();

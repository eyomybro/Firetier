#!/usr/bin/env python3
"""Firetier: FastFlag profile manager for Roblox, tuned for Rivals FPS.

Run:  python firetier.py
Edits only ClientAppSettings.json (Roblox's own local config file).
"""
from __future__ import annotations

import copy
import json
import os
import threading
import queue
import sys
import time
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine as E  # noqa: E402

LEVEL_COLORS = {"ok": "#1f7a3a", "warn": "#9a6400", "fail": "#b3261e", "info": "#3d4f66"}
LEVEL_ICONS = {"ok": "✔", "warn": "▲", "fail": "✖", "info": "•"}
STATUS_COLORS = {E.ACTIVE: "#1f7a3a", E.IGNORED: "#8a8a8a", E.INVALID: "#b3261e", E.DISABLED: "#a0a0a0"}
STATUS_ORDER = {E.ACTIVE: 0, E.INVALID: 1, E.DISABLED: 2, E.IGNORED: 3}
PREVIEW_W, PREVIEW_H = 300, 180


# --- Offline preview renderer (pure Python, no Roblox involved) -------------------
def _hash(x: int, y: int) -> int:
    h = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return (h ^ (h >> 16)) & 255


def _clamp(v: float) -> int:
    return 0 if v < 0 else 255 if v > 255 else int(v)


def _brick(u: int, v: int) -> tuple[int, int, int]:
    bh, bw = 12, 26
    row = v // bh
    off = bw // 2 if row % 2 else 0
    if v % bh < 2 or (u + off) % bw < 2:
        n = _hash(u, v) % 16
        return (196 + n, 190 + n, 180 + n)
    tone = _hash((u + off) // bw, row) % 40 - 20
    n = _hash(u, v) % 24 - 12
    return (_clamp(150 + tone + n), _clamp(72 + tone // 2 + n), _clamp(48 + n))


def _ground(u: int, v: int) -> tuple[int, int, int]:
    n = _hash(u, v) % 36 - 18
    patch = (_hash(u // 9, v // 9) % 20) - 10
    return (_clamp(92 + n + patch), _clamp(128 + n + patch), _clamp(64 + n // 2))


def _texture_layer(fn, w: int, h: int, d: int):
    full = [[fn(x, y) for x in range(w)] for y in range(h)]
    if d <= 1:
        return full
    out = [[(0, 0, 0)] * w for _ in range(h)]
    for by in range(0, h, d):
        ys = range(by, min(by + d, h))
        for bx in range(0, w, d):
            xs = range(bx, min(bx + d, w))
            r = g = b = 0
            for yy in ys:
                row = full[yy]
                for xx in xs:
                    c = row[xx]
                    r += c[0]; g += c[1]; b += c[2]
            n = len(ys) * len(xs)
            avg = (r // n, g // n, b // n)
            for yy in ys:
                out[yy][bx:bx + len(xs)] = [avg] * len(xs)
    return out


def render_rows(params: dict, w: int = PREVIEW_W, h: int = PREVIEW_H) -> list[list[str]]:
    """Draws a small made-up scene (sky, brick wall, ground) from preview_params().
    It's a schematic, not a Roblox render."""
    d = params["texture_downscale"]
    horizon = int(h * 0.42)
    x0, y0, x1, y1 = int(w * 0.2), int(h * 0.18), int(w * 0.8), int(h * 0.7)
    brick = _texture_layer(_brick, w, h, d)
    ground = _texture_layer(_ground, w, h, d)
    flat = params["flat_lighting"]
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            if x0 <= x < x1 and y0 <= y < y1:
                c, lit = brick[y][x], True
            elif y < horizon:
                if params["sky_gray"]:
                    c = (150, 150, 150)
                else:
                    t = y / horizon
                    c = (int(70 + 120 * t), int(140 + 85 * t), int(220 + 35 * t))
                    if (x - w * 0.1) ** 2 + (y - h * 0.12) ** 2 < 90:
                        c = (255, 240, 185)
                lit = False
            else:
                c, lit = ground[y][x], True
                if params["grass"] and y >= horizon + 4 and _hash(x, y // 4) < 34:
                    c = (70, 150 + _hash(x, y) % 40, 50)
            if lit:
                s = 0.9 if flat else 1.08 - 0.42 * x / w
                if not flat and y1 <= y < y1 + 10 and x0 - 2 <= x < x1 + 14:
                    s *= 0.58
                c = (_clamp(c[0] * s), _clamp(c[1] * s), _clamp(c[2] * s))
            row.append("#%02x%02x%02x" % c)
        rows.append(row)
    return rows


def describe_preview(params: dict) -> str:
    lvl = params["texture_level"]
    tex = ("normal (no override)" if lvl is None else
           f"quality {lvl}" + (f", drawn at 1/{params['texture_downscale']} resolution"
                               if params["texture_downscale"] > 1 else ""))
    parts = [f"Textures: {tex}", "Sky: grey" if params["sky_gray"] else "Sky: normal",
             "Grass: on" if params["grass"] else "Grass: off",
             "Lighting: flat" if params["flat_lighting"] else "Lighting: normal"]
    if params["quality_level"] is not None:
        parts.append(f"Render quality: {params['quality_level']} (not drawn)")
    return "  ·  ".join(parts)


# --- App --------------------------------------------------------------------------
class App:
    def __init__(self, root: tk.Tk, home: Path | None = None, lad: Path | None = None):
        self.root = root
        self.home = Path(home) if home else E.home_dir()
        self.lad = lad
        self.store = E.ProfileStore(self.home)
        self.backups = E.BackupStore(self.home)
        self.settings_path = self.home / "settings.json"
        self.settings, recovery_notice = E.load_preferences(self.settings_path)
        self.presets = {p.id: p for p in E.builtin_presets()}
        self.user_profiles: dict[str, E.Profile] = {}
        self.targets: list[E.Target] = []
        self.target: E.Target | None = None
        self.current: E.Profile | None = None
        self.dirty = False
        self.undo_stack: list = []
        self.redo_stack: list = []
        self.diag_ran = False
        self.diag_pending = False
        self._copy_when_ready = False
        self._diag_after = None
        self._imgs: list[tk.PhotoImage | None] = [None, None]

        self._preview_keys = [None, None]
        self._preview_cache = {}
        self.mode = tk.StringVar(value=self.settings.get("mode", "merge"))
        self.mode.trace_add("write", lambda *_: self._save_setting("mode", self.mode.get()))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self.refresh_rules())

        self._build()
        root.report_callback_exception = self._callback_error
        self.refresh_targets()
        self.refresh_profiles()
        start = self.settings.get("last_profile")
        if start not in self.presets and start not in self.user_profiles:
            start = "preset-rivals-notex"
        self.select_profile(start)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if recovery_notice:
            self.log(recovery_notice)

    # settings / log
    def _callback_error(self, kind, error, trace):
        self.log("".join(traceback.format_exception(kind, error, trace)).strip())
        messagebox.showerror("Firetier operation failed", str(error) or kind.__name__, parent=self.root)

    def _save_setting(self, key, value):
        if self.settings.get(key) == value:
            return
        updated = dict(self.settings, **{key: value})
        try:
            E.save_preferences(self.settings_path, self.settings, updated)
        except (OSError, ValueError) as exc:
            self.log(f"Preferences could not be saved: {exc}")
            return
        self.settings = updated

    def restore_preferences(self):
        if not self._confirm_leave() or not messagebox.askyesno("Restore preferences",
                "Reset the target selection, active profile and apply mode? Your profiles and target files are kept."):
            return
        E.write_json_atomic(self.home / "settings.before-reset.json", self.settings)
        E.save_preferences(self.settings_path, self.settings, {})
        self.settings = {}
        self.mode.set("merge")
        self.refresh_targets()
        self.select_profile("preset-rivals-notex")
        self.log("Restored Firetier preferences to defaults.")

    def log(self, msg: str):
        self.statusbar.config(text=msg)
        try:
            with open(self.home / "firetier.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
        except OSError as exc:
            self.statusbar.config(text=f"{msg} (Log unavailable: {exc})")

    # UI construction
    def _build(self):
        r = self.root
        r.title(f"{E.APP_NAME} {E.APP_VERSION}: FastFlag manager")
        r.geometry("1200x780")
        r.minsize(1000, 640)
        st = ttk.Style()
        if "vista" in st.theme_names():
            st.theme_use("vista")
        st.configure("Treeview", rowheight=22)
        st.configure("Head.TLabel", font=("Segoe UI", 14, "bold"))
        st.configure("Sub.TLabel", foreground="#555555")
        st.configure("Name.TLabel", font=("Segoe UI", 12, "bold"))
        st.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        top = ttk.Frame(r, padding=(10, 8, 10, 2))
        top.pack(fill="x")
        ttk.Label(top, text="Firetier", style="Head.TLabel").pack(side="left")
        ttk.Label(top, text="   FastFlag profiles for Roblox. Only edits ClientAppSettings.json.",
                  style="Sub.TLabel").pack(side="left")
        tf = ttk.Frame(top)
        tf.pack(side="right")
        ttk.Label(tf, text="Target:").pack(side="left")
        self.target_var = tk.StringVar()
        self.target_cb = ttk.Combobox(tf, textvariable=self.target_var, state="readonly", width=46)
        self.target_cb.pack(side="left", padx=4)
        self.target_cb.bind("<<ComboboxSelected>>", lambda e: self.on_target_change())
        ttk.Button(tf, text="Custom file…", command=self.pick_custom_target).pack(side="left")
        ttk.Button(tf, text="Rescan", command=self.refresh_targets).pack(side="left", padx=(4, 0))

        self.target_note = ttk.Label(r, text="", style="Sub.TLabel", padding=(10, 0, 10, 0),
                                     wraplength=1160, justify="left")
        self.target_note.pack(fill="x")

        self.statusbar = ttk.Label(r, text="Ready.", relief="sunken", anchor="w", padding=(8, 2))
        self.statusbar.pack(fill="x", side="bottom")
        bottom = ttk.Frame(r, padding=(10, 4, 10, 6))
        bottom.pack(fill="x", side="bottom")
        ttk.Label(bottom, text="Apply mode:").pack(side="left")
        ttk.Radiobutton(bottom, text="Merge (keep the file's other flags)", value="merge",
                        variable=self.mode).pack(side="left", padx=6)
        ttk.Radiobutton(bottom, text="Replace (file holds only this profile's flags)", value="replace",
                        variable=self.mode).pack(side="left", padx=6)
        ttk.Button(bottom, text="Remove all flags from target", command=self.clear_target).pack(side="right")
        ttk.Button(bottom, text="Apply to target", style="Accent.TButton",
                   command=self.apply).pack(side="right", padx=6)

        pw = ttk.PanedWindow(r, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=10, pady=6)
        left = ttk.Frame(pw)
        right = ttk.Frame(pw)
        pw.add(left, weight=1)
        pw.add(right, weight=4)
        def _init_sash(e, done=[False]):
            if not done[0] and e.width > 600:
                done[0] = True
                pw.after_idle(lambda: pw.sashpos(0, 290))
        pw.bind("<Configure>", _init_sash, add="+")

        ttk.Label(left, text="Profiles", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        lf = ttk.Frame(left)
        lf.pack(fill="both", expand=True)
        self.ptree = ttk.Treeview(lf, show="tree", selectmode="browse")
        psb = ttk.Scrollbar(lf, orient="vertical", command=self.ptree.yview)
        self.ptree.configure(yscrollcommand=psb.set)
        self.ptree.pack(side="left", fill="both", expand=True)
        psb.pack(side="right", fill="y")
        self.ptree.bind("<<TreeviewSelect>>", self.on_profile_pick)
        bf = ttk.Frame(left)
        bf.pack(fill="x", pady=(6, 0))
        buttons = [("New", self.new_profile), ("Duplicate", self.duplicate_profile),
                   ("Rename", self.rename_profile), ("Delete", self.delete_profile),
                   ("Import…", self.import_profile), ("Export…", self.export_profile),
                   ("Export flags JSON…", self.export_flat), ("Load target as profile", self.load_target_as_profile)]
        for i, (t, c) in enumerate(buttons):
            ttk.Button(bf, text=t, command=c).grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        bf.columnconfigure(0, weight=1)
        bf.columnconfigure(1, weight=1)

        self.pname = ttk.Label(right, text="", style="Name.TLabel")
        self.pname.pack(anchor="w")
        self.pdesc = ttk.Label(right, text="", wraplength=880, justify="left", style="Sub.TLabel")
        self.pdesc.pack(anchor="w", fill="x")
        self.pdesc.bind("<Configure>", lambda e: self.pdesc.configure(wraplength=max(100, e.width - 4)))
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True, pady=(6, 0))
        self._build_flags_tab()
        self._build_status_tab()
        self._build_preview_tab()
        self._build_backups_tab()
        self._build_diag_tab()
        self.nb.bind("<<NotebookTabChanged>>", self.on_tab)

        r.bind_all("<Control-s>", lambda e: self.save_profile())
        r.bind_all("<Control-z>", lambda e: self.undo())
        r.bind_all("<Control-y>", lambda e: self.redo())

    def _build_flags_tab(self):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text="Flags")
        sf = ttk.Frame(f)
        sf.pack(fill="x")
        ttk.Label(sf, text="Search:").pack(side="left")
        ttk.Entry(sf, textvariable=self.search, width=32).pack(side="left", padx=4)
        self.show_ignored = tk.BooleanVar(value=True)
        ttk.Checkbutton(sf, text="Show flags Roblox ignores", variable=self.show_ignored,
                        command=self.refresh_rules).pack(side="left", padx=8)
        self.counts = ttk.Label(sf, text="", style="Sub.TLabel")
        self.counts.pack(side="right")

        tf = ttk.Frame(f)
        tf.pack(fill="both", expand=True, pady=(6, 0))
        cols = ("on", "flag", "value", "status", "group", "note")
        tv = ttk.Treeview(tf, columns=cols, show="headings", selectmode="extended")
        for c, t, w, stretch in [("on", "On", 40, False), ("flag", "Flag", 330, True),
                                 ("value", "Value", 90, False), ("status", "Status", 80, False),
                                 ("group", "Group", 110, False), ("note", "Note", 300, True)]:
            tv.heading(c, text=t)
            tv.column(c, width=w, stretch=stretch, anchor="w")
        for s, col in STATUS_COLORS.items():
            tv.tag_configure(s, foreground=col)
        sb = ttk.Scrollbar(tf, orient="vertical", command=tv.yview)
        horizontal = ttk.Scrollbar(tf, orient="horizontal", command=tv.xview)
        horizontal.pack(side="bottom", fill="x")
        tv.configure(yscrollcommand=sb.set, xscrollcommand=horizontal.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.bind("<<TreeviewSelect>>", self.on_rule_pick)
        tv.bind("<Double-1>", lambda e: self.toggle_rules())
        tv.bind("<Delete>", lambda e: self.remove_rules())
        self.rtree = tv

        ed = ttk.LabelFrame(f, text="Edit flag", padding=6)
        ed.pack(fill="x", pady=(6, 0))
        self.flag_var = tk.StringVar()
        self.value_var = tk.StringVar()
        ttk.Label(ed, text="Flag").grid(row=0, column=0, sticky="w")
        self.flag_cb = ttk.Combobox(ed, textvariable=self.flag_var, values=sorted(E.ALLOWLIST), width=48)
        self.flag_cb.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(ed, text="Value").grid(row=0, column=2)
        ve = ttk.Entry(ed, textvariable=self.value_var, width=14)
        ve.grid(row=0, column=3, padx=4)
        ve.bind("<Return>", lambda e: self.add_rule())
        actions = ttk.Frame(ed)
        actions.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        col = 0
        for t, c in [("Add / Update", self.add_rule), ("Enable/Disable", self.toggle_rules),
                     ("Remove", self.remove_rules), ("Undo", self.undo), ("Redo", self.redo),
                     ("Save", self.save_profile)]:
            ttk.Button(actions, text=t, command=c).grid(row=0, column=col, padx=2)
            col += 1
        self.flag_help = ttk.Label(ed, text="", style="Sub.TLabel", wraplength=860, justify="left")
        self.flag_help.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ed.columnconfigure(1, weight=1)
        self.flag_var.trace_add("write", lambda *_: self.update_flag_help())

    def _build_status_tab(self):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text="Status")
        self.stext = tk.Text(f, wrap="word", font=("Segoe UI", 10), relief="flat", padx=8, pady=6)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.stext.yview)
        self.stext.configure(yscrollcommand=sb.set)
        self.stext.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for lvl, c in LEVEL_COLORS.items():
            self.stext.tag_configure(lvl, foreground=c)
        self.stext.tag_configure("h", font=("Segoe UI", 11, "bold"), spacing1=8, spacing3=2)
        self.stext.tag_configure("mono", font=("Consolas", 9))

    def _build_preview_tab(self):
        f = ttk.Frame(self.nb, padding=10)
        self.nb.add(f, text="Preview")
        ttk.Label(f, text="Offline approximation drawn by Firetier. Not a Roblox screenshot, and not proof "
                          "of what Roblox will render.", foreground=LEVEL_COLORS["warn"]).pack(anchor="w")
        g = ttk.Frame(f)
        g.pack(anchor="w", pady=8)
        self.prev_labels, self.prev_caps = [], []
        for i, title in enumerate(("Default (no flags)", "With this profile")):
            ttk.Label(g, text=title, font=("Segoe UI", 10, "bold")).grid(row=0, column=i, sticky="w", padx=(0, 16))
            lab = ttk.Label(g, relief="solid")
            lab.grid(row=1, column=i, padx=(0, 16), sticky="nw")
            cap = ttk.Label(g, text="", style="Sub.TLabel", wraplength=PREVIEW_W, justify="left")
            cap.grid(row=2, column=i, sticky="nw", padx=(0, 16), pady=(4, 0))
            self.prev_labels.append(lab)
            self.prev_caps.append(cap)
        ttk.Label(f, style="Sub.TLabel", wraplength=860, justify="left", text=(
            "What this shows: texture quality as lower resolution, grey sky, grass on/off and flat "
            "lighting. What it can't show: real Roblox materials, Rivals' maps, or frame rate. "
            "In busy FFA lobbies most of the cost is CPU work for characters and effects, which "
            "FastFlags barely touch.")).pack(anchor="w")

    def _build_backups_tab(self):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text="Backups")
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        self.all_backups = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show backups for all targets", variable=self.all_backups,
                        command=self.refresh_backups).pack(side="left")
        ttk.Button(bar, text="Open backups folder", command=lambda: self._open(self.backups.dir)).pack(side="right")
        ttk.Button(bar, text="Show contents", command=self.show_backup).pack(side="right", padx=4)
        ttk.Button(bar, text="Restore selected", command=self.restore_backup).pack(side="right")
        tf = ttk.Frame(f)
        tf.pack(fill="both", expand=True, pady=(6, 0))
        cols = ("when", "target", "flags", "reason")
        tv = ttk.Treeview(tf, columns=cols, show="headings", selectmode="browse")
        for c, t, w, s in [("when", "Created", 150, False), ("target", "Target", 200, False),
                           ("flags", "File then", 150, False), ("reason", "Reason", 400, True)]:
            tv.heading(c, text=t)
            tv.column(c, width=w, stretch=s, anchor="w")
        sb = ttk.Scrollbar(tf, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tv.bind("<Double-1>", lambda e: self.show_backup())
        self.btree = tv

    def _build_diag_tab(self):
        f = ttk.Frame(self.nb, padding=6)
        self.nb.add(f, text="Diagnostics")
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Button(bar, text="Run diagnostics", command=self.run_diag).pack(side="left")
        ttk.Button(bar, text="Copy report", command=self.copy_diag).pack(side="left", padx=4)
        ttk.Button(bar, text="Open Firetier folder", command=lambda: self._open(self.home)).pack(side="right")
        ttk.Button(bar, text="Restore preferences", command=self.restore_preferences).pack(side="left")
        tf = ttk.Frame(f)
        tf.pack(fill="both", expand=True, pady=(6, 0))
        cols = ("st", "name", "detail", "fix")
        tv = ttk.Treeview(tf, columns=cols, show="headings")
        for c, t, w, s in [("st", "", 30, False), ("name", "Check", 220, False),
                           ("detail", "Result", 420, True), ("fix", "Suggested fix", 320, True)]:
            tv.heading(c, text=t)
            tv.column(c, width=w, stretch=s, anchor="w")
        for lvl, c in LEVEL_COLORS.items():
            tv.tag_configure(lvl, foreground=c)
        sb = ttk.Scrollbar(tf, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.diag_detail = ttk.Label(f, text="Select a check to read its full result.", wraplength=670, justify="left")
        self.diag_detail.pack(fill="x", pady=4)
        def detail(_event):
            selection = tv.selection()
            if selection:
                _, name, result, fix = tv.item(selection[0], "values")
                self.diag_detail.config(text="\n".join(x for x in (name, result, fix) if x))
        tv.bind("<<TreeviewSelect>>", detail)
        self.dtree = tv
        self.diag_checks: list[E.Check] = []

    # targets
    def refresh_targets(self):
        self.targets = E.detect_targets(self.lad)
        custom = self.settings.get("custom_target")
        if custom:
            self.targets.append(E.Target("custom", "Custom file", Path(custom), "custom",
                                         ["You picked this file by hand."]))
        self.target_cb["values"] = [t.label for t in self.targets]
        want = self.settings.get("target_id")
        idx = next((i for i, t in enumerate(self.targets) if t.id == want), 0 if self.targets else None)
        if idx is None:
            self.target_var.set("No Roblox install found")
            self.target = None
        else:
            self.target_cb.current(idx)
        self.on_target_change()

    def on_target_change(self):
        i = self.target_cb.current()
        self.target = self.targets[i] if 0 <= i < len(self.targets) else None
        if self.target:
            t = self.target
            exists = "exists" if t.path.is_file() else "doesn't exist yet"
            self.target_note.config(text=f"File: {t.path}  ({exists})\n" + "  ".join(t.notes))
            self._save_setting("target_id", t.id)
        else:
            self.target_note.config(text="No Roblox, Fishstrap or Bloxstrap install found. "
                                         "Use 'Custom file...' to pick a ClientAppSettings.json.")
        self.refresh_status()
        self.refresh_backups()

    def pick_custom_target(self):
        p = filedialog.asksaveasfilename(title="Pick or create a ClientAppSettings.json",
                                         initialfile="ClientAppSettings.json", defaultextension=".json",
                                         filetypes=[("JSON", "*.json")], confirmoverwrite=False)
        if not p:
            return
        self._save_setting("custom_target", p)
        self._save_setting("target_id", "custom")
        self.refresh_targets()

    # profiles
    def refresh_profiles(self, select: str | None = None):
        t = self.ptree
        t.delete(*t.get_children())
        groups: dict[str, str] = {}

        def grp(name):
            if name not in groups:
                groups[name] = t.insert("", "end", iid="grp:" + name, text=name, open=True)
            return groups[name]

        for p in self.presets.values():
            t.insert(grp("Built-in presets"), "end", iid=p.id, text=p.name)
        self.user_profiles = {p.id: p for p in self.store.list()}
        for p in self.user_profiles.values():
            t.insert(grp("Unsupported imports" if p.unsupported else "My profiles"), "end",
                     iid=p.id, text=p.name)
        if "grp:My profiles" not in groups:
            grp("My profiles")
        sel = select or (self.current.id if self.current else None)
        if sel and t.exists(sel):
            t.selection_set(sel)
            t.see(sel)
        if self.store.load_errors:
            self.log(f"{len(self.store.load_errors)} profile file(s) couldn't be read. See Diagnostics.")

    def _load(self, pid: str) -> E.Profile | None:
        if pid in self.presets:
            return copy.deepcopy(self.presets[pid])
        try:
            return self.store.get(pid)
        except (OSError, ValueError) as e:
            messagebox.showerror("Can't open profile", str(e))
            return None

    def _confirm_leave(self) -> bool:
        if not self.dirty or not self.current:
            return True
        ans = messagebox.askyesnocancel("Unsaved changes", f"Save changes to '{self.current.name}'?")
        if ans is None:
            return False
        if ans:
            return self.save_profile()
        return True

    def on_profile_pick(self, _=None):
        sel = self.ptree.selection()
        if not sel or sel[0].startswith("grp:"):
            return
        if self.current and sel[0] == self.current.id:
            return
        if not self._confirm_leave():
            self.ptree.selection_set(self.current.id)
            return
        self.select_profile(sel[0])

    def select_profile(self, pid: str):
        p = self._load(pid)
        if p is None:
            return
        self.current = p
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        if self.ptree.exists(pid) and self.ptree.selection() != (pid,):
            self.ptree.selection_set(pid)
            self.ptree.see(pid)
        self._save_setting("last_profile", pid)
        self.refresh_all()

    def refresh_all(self):
        self.refresh_header()
        self.refresh_rules()
        self.refresh_status()
        if self._tab() == "Preview":
            self.refresh_preview()

    def refresh_header(self):
        p = self.current
        if not p:
            self.pname.config(text="")
            self.pdesc.config(text="")
            return
        badge = "  [built-in, read-only]" if p.builtin else "  [unsupported import]" if p.unsupported else ""
        self.pname.config(text=p.name + (" *" if self.dirty else "") + badge)
        g = E.GAMES.get(p.game, E.GAMES["all"])
        desc = p.description + ("\n" if p.description else "") + f"Game: {g['name']}. {E.GAME_SCOPE_NOTE}"
        if g.get("notes"):
            desc += f"\n{g['notes']}"
        self.pdesc.config(text=desc)

    def _editable(self) -> bool:
        p = self.current
        if not p:
            return False
        if p.unsupported:
            messagebox.showinfo("Stored only", "This is stored asset-replacement data. Firetier keeps "
                                               "it unchanged and can export it, but can't edit or apply it.")
            return False
        if p.builtin:
            if messagebox.askyesno("Built-in preset", "Built-in presets are read-only.\n\n"
                                                      "Make an editable copy and edit that?"):
                return self.duplicate_profile(ask_name=False)
            return False
        return True

    def new_profile(self):
        if not self._confirm_leave():
            return
        name = simpledialog.askstring("New profile", "Name:", parent=self.root)
        if not name or not name.strip():
            return
        p = E.Profile(name=name.strip(), rules=[])
        self.store.save(p)
        self.current = None
        self.refresh_profiles(p.id)
        self.select_profile(p.id)
        self.log(f"Created profile '{p.name}'.")

    def duplicate_profile(self, ask_name: bool = True) -> bool:
        if not self.current or not self._confirm_leave():
            return False
        name = f"{self.current.name} (copy)"
        if ask_name:
            name = simpledialog.askstring("Duplicate profile", "Name for the copy:", initialvalue=name,
                                          parent=self.root)
            if not name or not name.strip():
                return False
        p = self.store.duplicate(self.current, name.strip())
        self.current = None
        self.refresh_profiles(p.id)
        self.select_profile(p.id)
        self.log(f"Created '{p.name}'.")
        return True

    def rename_profile(self):
        p = self.current
        if not p or p.builtin:
            messagebox.showinfo("Rename", "Built-in presets can't be renamed. Duplicate it first.")
            return
        name = simpledialog.askstring("Rename profile", "New name:", initialvalue=p.name, parent=self.root)
        if not name or not name.strip():
            return
        old = p.name
        p.name = name.strip()
        if self.dirty:
            self.refresh_header()
        else:
            self.store.save(p)
        self.refresh_profiles(p.id)
        self.refresh_header()
        self.log(f"Renamed '{old}' to '{p.name}'.")

    def delete_profile(self):
        p = self.current
        if not p or p.builtin:
            messagebox.showinfo("Delete", "Built-in presets can't be deleted.")
            return
        if not messagebox.askyesno("Delete profile", f"Delete '{p.name}'?\n\nIt's moved to "
                                                    f"{self.store.trash}, so you can get it back."):
            return
        dst = self.store.delete(p.id)
        self.dirty = False
        self.current = None
        self.refresh_profiles()
        self.select_profile("preset-rivals-notex")
        self.log(f"Moved '{p.name}' to {dst}.")

    def import_profile(self):
        if not self._confirm_leave():
            return
        path = filedialog.askopenfilename(title="Import profile or FastFlag JSON",
                                          filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        res = E.import_profile_file(Path(path))
        if res.profile is None:
            messagebox.showerror("Import failed", "\n".join(res.messages))
            return
        self.store.save(res.profile)
        self.current = None
        self.refresh_profiles(res.profile.id)
        self.select_profile(res.profile.id)
        (messagebox.showinfo if res.supported else messagebox.showwarning)("Import", "\n\n".join(res.messages))
        self.log(f"Imported {Path(path).name} as '{res.profile.name}' ({res.kind}).")

    def export_profile(self):
        p = self.current
        if not p:
            return
        path = filedialog.asksaveasfilename(title="Export Firetier profile", defaultextension=".json",
                                            initialfile=f"{_safe(p.name)}.firetier.json",
                                            filetypes=[("JSON", "*.json")])
        if not path:
            return
        E.export_profile(p, Path(path))
        self.log(f"Exported '{p.name}' to {path}.")

    def export_flat(self):
        p = self.current
        if not p:
            return
        if p.unsupported:
            messagebox.showinfo("Export", "This profile has no FastFlags. Use Export... to save the "
                                          "original data.")
            return
        path = filedialog.asksaveasfilename(title="Export plain FastFlag JSON", defaultextension=".json",
                                            initialfile=f"{_safe(p.name)}.json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        n = E.export_flat(p, Path(path))
        self.log(f"Wrote {n} honored flag(s) to {path}.")

    def load_target_as_profile(self):
        t = self.target
        if not t:
            return
        state = E.read_target(t)
        if not state.exists:
            messagebox.showinfo("Load target", f"{t.path} doesn't exist yet. Nothing to load.")
            return
        if state.error:
            messagebox.showerror("Load target", f"Can't read {t.path}: {state.error}")
            return
        if not self._confirm_leave():
            return
        rules = [E.Rule(str(k), E.normalize_value(str(k), v)) for k, v in state.flags.items()]
        p = E.Profile(name=f"{t.label} snapshot {time.strftime('%Y-%m-%d %H.%M')}", rules=rules,
                      description=f"Copy of {t.path} as it was when loaded.", game="all",
                      source={"kind": "target-snapshot", "path": str(t.path), "imported": time.time(),
                              "original": state.flags})
        self.store.save(p)
        self.current = None
        self.refresh_profiles(p.id)
        self.select_profile(p.id)
        s = E.analyze_flags(state.flags)
        messagebox.showinfo("Loaded target", (
            f"{s.total} flags in {t.label}:\n\n"
            f"• {len(s.active)} honored by Roblox\n"
            f"• {len(s.ignored)} ignored (not on Roblox's allowlist)\n"
            f"• {len(s.invalid)} invalid\n\n"
            "To clean the file so it holds only the honored flags, apply this profile in Replace "
            "mode. A backup is made first."))

    def save_profile(self) -> bool:
        p = self.current
        if not p or p.builtin or p.unsupported:
            return False
        try:
            self.store.save(p)
        except (OSError, ValueError) as e:
            messagebox.showerror("Save failed", str(e))
            return False
        self.dirty = False
        self.refresh_profiles(p.id)
        self.refresh_header()
        self.log(f"Saved '{p.name}'.")
        return True

    # rule editing
    def _selected_rule_idx(self) -> list[int]:
        return [int(i) for i in self.rtree.selection()]

    def _push_undo(self):
        self.undo_stack.append(copy.deepcopy(self.current.rules))
        del self.undo_stack[:-200]
        self.redo_stack.clear()

    def _changed(self, select: list[int] | None = None):
        self.dirty = True
        self.refresh_header()
        self.refresh_rules(select)
        self.refresh_status()
        if self._tab() == "Preview":
            self.refresh_preview()

    def add_rule(self):
        flag, val = self.flag_var.get().strip(), self.value_var.get().strip()
        if not flag:
            return
        err = E.value_error(flag, val)
        if err:
            messagebox.showerror("Invalid", f"{flag}: {err}")
            return
        if flag not in E.ALLOWLIST and not messagebox.askyesno(
                "Not on the allowlist", f"{flag} isn't on Roblox's allowlist, so Roblox ignores it and "
                                        "Firetier won't write it.\n\nKeep it in the profile anyway?"):
            return
        if not self._editable():
            return
        self._push_undo()
        val = E.normalize_value(flag, val)
        idx = next((i for i in range(len(self.current.rules) - 1, -1, -1)
                    if self.current.rules[i].flag == flag), None)
        if idx is None:
            self.current.rules.append(E.Rule(flag, val))
            idx = len(self.current.rules) - 1
        else:
            self.current.rules[idx].value = val
            self.current.rules[idx].enabled = True
        self._changed([idx])

    def toggle_rules(self):
        idx = self._selected_rule_idx()
        if not idx or not self._editable():
            return
        self._push_undo()
        for i in idx:
            self.current.rules[i].enabled = not self.current.rules[i].enabled
        self._changed(idx)

    def remove_rules(self):
        idx = self._selected_rule_idx()
        if not idx or not self._editable():
            return
        self._push_undo()
        for i in sorted(idx, reverse=True):
            del self.current.rules[i]
        self._changed()

    def undo(self):
        if not self.undo_stack or not self.current:
            return
        self.redo_stack.append(copy.deepcopy(self.current.rules))
        self.current.rules = self.undo_stack.pop()
        self._changed()

    def redo(self):
        if not self.redo_stack or not self.current:
            return
        self.undo_stack.append(copy.deepcopy(self.current.rules))
        self.current.rules = self.redo_stack.pop()
        self._changed()

    def on_rule_pick(self, _=None):
        idx = self._selected_rule_idx()
        if idx and self.current:
            r = self.current.rules[idx[0]]
            self.flag_var.set(r.flag)
            self.value_var.set(r.value)

    def update_flag_help(self):
        f = self.flag_var.get().strip()
        if not f:
            self.flag_help.config(text="Pick a flag from the list (all 18 allowlisted flags are there).")
            return
        kind = E.flag_kind(f)
        typ = {"Flag": "True or False", "Int": "whole number", "Log": "whole number",
               "String": "text"}.get(kind or "", "")
        parts = []
        if f in E.ALLOWLIST:
            parts.append(E.FLAG_HELP.get(f, ""))
        elif kind:
            parts.append("Not on Roblox's allowlist: Roblox ignores this flag.")
        else:
            parts.append("Not a valid FastFlag name.")
        if typ:
            parts.append(f"Value: {typ}.")
        if f in E.RANGES:
            parts.append("Usual range: %d-%d." % E.RANGES[f])
        self.flag_help.config(text="  ".join(p for p in parts if p))

    def refresh_rules(self, select: list[int] | None = None):
        tv = self.rtree
        tv.delete(*tv.get_children())
        p = self.current
        if not p:
            self.counts.config(text="")
            return
        q = self.search.get().strip().lower()
        counts = {E.ACTIVE: 0, E.IGNORED: 0, E.INVALID: 0, E.DISABLED: 0}
        items = []
        for i, r in enumerate(p.rules):
            st, note = r.status()
            counts[st] += 1
            if q and q not in r.flag.lower() and q not in r.value.lower():
                continue
            if st == E.IGNORED and not self.show_ignored.get():
                continue
            items.append((STATUS_ORDER[st], r.flag.lower(), i, r, st, note))
        for _, _, i, r, st, note in sorted(items):
            tv.insert("", "end", iid=str(i), tags=(st,),
                      values=("✔" if r.enabled else "—", r.flag, _short(r.value), st, r.group, note))
        self.counts.config(text=f"{counts[E.ACTIVE]} honored · {counts[E.IGNORED]} ignored · "
                                f"{counts[E.INVALID]} invalid · {counts[E.DISABLED]} disabled")
        if select:
            keep = [str(i) for i in select if tv.exists(str(i))]
            if keep:
                tv.selection_set(keep)
                tv.see(keep[0])
        if p.unsupported:
            src = p.source.get("original")
            n = E._count_asset_ids(src, [200000])
            self.counts.config(text=f"Stored asset-replacement data (~{n} asset ids). Not applicable.")

    # status
    def refresh_status(self):
        if not hasattr(self, "stext"):
            return
        tx = self.stext
        tx.config(state="normal")
        tx.delete("1.0", "end")
        p, t = self.current, self.target
        if not p:
            tx.config(state="disabled")
            return
        state = E.read_target(t) if t else None
        tx.insert("end", "Status\n", "h")
        for lvl, line in E.profile_report(p, t, state):
            tx.insert("end", f"{LEVEL_ICONS[lvl]}  {line}\n", lvl)
        if not p.unsupported:
            conf = E.find_conflicts(p.rules)
            tx.insert("end", "Conflicts and warnings\n", "h")
            if conf:
                for c in conf:
                    tx.insert("end", f"{LEVEL_ICONS['warn']}  {c}\n", "warn")
            else:
                tx.insert("end", f"{LEVEL_ICONS['ok']}  None.\n", "ok")
            skipped = [(r.flag, r.status()[1]) for r in p.rules if r.status()[0] in (E.IGNORED, E.INVALID)]
            if skipped:
                tx.insert("end", f"Not written when applying ({len(skipped)})\n", "h")
                for f, why in skipped[:400]:
                    tx.insert("end", f"   {f}: {why}\n", "info")
                if len(skipped) > 400:
                    tx.insert("end", f"   …and {len(skipped) - 400} more\n", "info")
            eff = p.effective_flags()
            tx.insert("end", f"What Apply writes ({len(eff)} flags)\n", "h")
            tx.insert("end", json.dumps(eff, indent=2) + "\n", "mono")
        if state and state.exists and not state.error:
            s = E.analyze_flags(state.flags)
            tx.insert("end", f"Target file right now: {t.path}\n", "h")
            tx.insert("end", f"{s.total} flags: {len(s.active)} honored, {len(s.ignored)} ignored by "
                             f"Roblox, {len(s.invalid)} invalid.\n", "warn" if s.ignored or s.invalid else "ok")
        tx.config(state="disabled")

    # preview
    def _tab(self) -> str:
        try:
            return self.nb.tab(self.nb.select(), "text")
        except tk.TclError:
            return ""

    def on_tab(self, _=None):
        tab = self._tab()
        if tab == "Preview":
            self.refresh_preview()
        elif tab == "Diagnostics" and not self.diag_ran:
            self.run_diag()
        elif tab == "Backups":
            self.refresh_backups()

    def refresh_preview(self):
        if not self.current:
            return
        flags = {} if self.current.unsupported else self.current.effective_flags()
        for i, fl in enumerate(({}, flags)):
            if i == 1 and self.current.unsupported:
                self.prev_labels[1].configure(image="", text="Asset preview unavailable", padding=8)
                self.prev_caps[1].configure(text="Stored asset references. Firetier can export this data.")
                self._preview_keys[i] = None
                continue
            params = E.preview_params(fl)
            if self._preview_keys[i] == params:
                continue
            key = tuple(params.items())
            img = self._preview_cache.pop(key, None)
            if img is None:
                img = tk.PhotoImage(master=self.root, width=PREVIEW_W, height=PREVIEW_H)
                rows = render_rows(params)
                img.put(" ".join("{" + " ".join(r) + "}" for r in rows), to=(0, 0))
            self._preview_cache[key] = img
            if len(self._preview_cache) > 6:
                del self._preview_cache[next(iter(self._preview_cache))]
            self._imgs[i] = img
            self._preview_keys[i] = params
            self.prev_labels[i].config(image=img, text="", padding=0)
            self.prev_caps[i].config(text=describe_preview(params))

    # backups
    def refresh_backups(self):
        if not hasattr(self, "btree"):
            return
        tv = self.btree
        tv.delete(*tv.get_children())
        tid = None if self.all_backups.get() or not self.target else self.target.id
        for m in self.backups.list(tid):
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m.get("created", 0)))
            then = "no file" if not m.get("existed") else self._backup_summary(m)
            tv.insert("", "end", iid=m["id"], values=(when, m.get("target_label", "?"), then, m.get("reason", "")))

        if self.backups.load_errors:
            self.log(f"{len(self.backups.load_errors)} incomplete or invalid backup(s). See Diagnostics.")

    def _backup_summary(self, m: dict) -> str:
        try:
            data = E.read_json(self.backups.dir / m["id"] / "ClientAppSettings.json")
            if isinstance(data, dict):
                s = E.analyze_flags(data)
                return f"{s.total} flags ({len(s.active)} honored)"
            return "not a JSON object"
        except (OSError, ValueError):
            return "unreadable"

    def restore_backup(self):
        sel = self.btree.selection()
        if not sel:
            messagebox.showinfo("Restore", "Pick a backup first.")
            return
        m = self.backups.get(sel[0])
        what = ("put the backed-up file back" if m.get("existed")
                else "remove the file (there was none when this backup was taken)")
        if not messagebox.askyesno("Restore backup", f"This will {what}:\n\n{m['target_path']}\n\n"
                                                     "The current file is backed up first."):
            return
        try:
            msg = self.backups.restore(sel[0])
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror("Restore failed", str(e))
            self.log(f"Restore of {sel[0]} failed: {e}")
            return
        self.log(msg)
        messagebox.showinfo("Restored", msg + "\n\nRestart Roblox for it to load the restored flags.")
        self.refresh_backups()
        self.refresh_status()
        self.on_target_change()

    def show_backup(self):
        sel = self.btree.selection()
        if not sel:
            return
        m = self.backups.get(sel[0])
        p = self.backups.dir / sel[0] / "ClientAppSettings.json"
        if m["existed"]:
            with p.open("rb") as f:
                data = f.read(256 * 1024 + 1)
            text = data[:256 * 1024].decode("utf-8-sig", errors="replace")
            if len(data) > 256 * 1024:
                text += "\n[Preview limited to 256 KiB]"
        else:
            text = "(no file existed when this backup was made)"
        w = tk.Toplevel(self.root)
        w.title(f"Backup {sel[0]}")
        w.geometry("700x520")
        ttk.Label(w, text=f"{m['target_path']}\n{m.get('reason', '')}", padding=6).pack(anchor="w")
        tx = tk.Text(w, wrap="none", font=("Consolas", 9))
        tx.insert("1.0", text)
        tx.config(state="disabled")
        tx.pack(fill="both", expand=True)

    # diagnostics
    def run_diag(self):
        if self.diag_pending:
            return
        self.diag_pending = True
        self.statusbar.config(text="Running diagnostics...")
        result = queue.SimpleQueue()

        def worker():
            try:
                checks = E.run_diagnostics(self.home, E.ProfileStore(self.home), self.lad, str(tk.TkVersion))
            except Exception as exc:
                checks = [E.Check("fail", "Diagnostics could not finish", str(exc) or type(exc).__name__)]
            result.put(checks)

        def display_when_ready():
            try:
                checks = result.get_nowait()
            except queue.Empty:
                self._diag_after = self.root.after(50, display_when_ready)
                return
            self._diag_after = None
            self.diag_pending = False
            self.diag_ran = True
            self.diag_checks = checks
            self._display_diagnostics()
            if self._copy_when_ready:
                self._copy_when_ready = False
                self.copy_diag()

        threading.Thread(target=worker, name="Firetier diagnostics", daemon=True).start()
        display_when_ready()

    def _display_diagnostics(self):
        tv = self.dtree
        tv.delete(*tv.get_children())
        for c in self.diag_checks:
            tv.insert("", "end", tags=(c.status,), values=(LEVEL_ICONS[c.status], c.name, c.detail, c.fix))
        n = {s: sum(1 for c in self.diag_checks if c.status == s) for s in LEVEL_COLORS}
        self.log(f"Diagnostics: {n['ok']} ok, {n['warn']} warning(s), {n['fail']} problem(s).")

    def copy_diag(self):
        if self.diag_pending or not self.diag_checks:
            self._copy_when_ready = True
            self.run_diag()
            return
        lines = [f"{E.APP_NAME} {E.APP_VERSION} diagnostics, {time.strftime('%Y-%m-%d %H:%M')}"]
        for c in self.diag_checks:
            lines.append(f"[{c.status.upper()}] {c.name}: {c.detail}" + (f"  -> {c.fix}" if c.fix else ""))
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.log("Diagnostics report copied to the clipboard.")

    # apply
    def apply(self):
        p, t = self.current, self.target
        if not p or not t:
            messagebox.showerror("Apply", "Pick a profile and a target first.")
            return
        if p.unsupported:
            messagebox.showerror("Apply", "Asset replacement data can't be applied. Firetier only writes FastFlags.")
            return
        if self.dirty:
            ans = messagebox.askyesnocancel("Unsaved changes", "Save the profile before applying?\n\n"
                                                               "(No applies it without saving.)")
            if ans is None:
                return
            if ans and not self.save_profile():
                return
        mode = self.mode.get()
        eff = p.effective_flags()
        state = E.read_target(t)
        skipped = sum(1 for r in p.rules if r.status()[0] in (E.IGNORED, E.INVALID))
        lines = [f"Profile: {p.name}", f"Target: {t.label}", f"File: {t.path}",
                 f"Mode: {'Replace' if mode == 'replace' else 'Merge'}", "", f"Flags to write: {len(eff)}"]
        if skipped:
            lines.append(f"Not written (ignored by Roblox or invalid): {skipped}")
        if state.exists and not state.error:
            if mode == "replace":
                removed = [k for k in state.flags if k not in eff]
                lines.append(f"Removed from the file: {len(removed)} flag(s)"
                             + (f", {sum(1 for k in removed if k not in E.ALLOWLIST)} of them ignored by "
                                "Roblox anyway" if removed else ""))
            else:
                changed = sum(1 for k, v in eff.items()
                              if k not in state.flags or E.normalize_value(k, state.flags[k]) != v)
                lines.append(f"Added or changed: {changed}; other flags in the file kept: "
                             f"{len([k for k in state.flags if k not in eff])}")
        elif state.error:
            lines.append(f"The current file is unreadable ({state.error}).")
        conf = E.find_conflicts(p.rules)
        if conf:
            lines += ["", "Warnings:"] + [f"• {c}" for c in conf]
        lines += ["", "The current file is backed up first."]
        lines.append("Restart Roblox after applying for the settings to load.")
        if not messagebox.askokcancel("Apply profile", "\n".join(lines)):
            return
        res = E.apply_profile(p, t, self.backups, mode)
        self.log(res.message)
        if res.ok:
            how = (f"Start Roblox through {t.label.split()[0]} so it copies the flags in."
                   if t.kind == "bootstrapper" else "Restart Roblox so it loads them.")
            messagebox.showinfo("Applied", f"{res.message}\nBackup: {res.backup_id}\n\n{how}\n\n"
                                           "In-game effect isn't verified: Firetier can't see inside Roblox.")
        else:
            messagebox.showerror("Apply failed", res.message)
        self.on_target_change()

    def clear_target(self):
        t = self.target
        if not t:
            return
        state = E.read_target(t)
        if not state.exists:
            messagebox.showinfo("Remove flags", "The target has no flags file. Nothing to remove.")
            return
        if not messagebox.askyesno("Remove all flags", f"Replace {t.path} with an empty flag list "
                                                       f"({len(state.flags)} flag(s) now)?\n\n"
                                                       "The current file is backed up first."):
            return
        res = E.clear_target(t, self.backups)
        self.log(res.message)
        (messagebox.showinfo if res.ok else messagebox.showerror)("Remove flags", res.message)
        self.on_target_change()

    # misc
    def _open(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606

    def on_close(self):
        if self._confirm_leave():
            if self._diag_after is not None:
                self.root.after_cancel(self._diag_after)
            self.root.destroy()


def _short(v: str, n: int = 60) -> str:
    v = " ".join(v.split())
    return v if len(v) <= n else v[:n - 1] + "…"


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in name).strip() or "profile"


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    try:
        home = E.home_dir()
        home.mkdir(parents=True, exist_ok=True)
        with E.operation_lock(home / "settings.json"):
            App(root, home)
            root.mainloop()
    except (OSError, ValueError, MemoryError) as exc:
        root.withdraw()
        messagebox.showerror("Firetier could not start", str(exc) or type(exc).__name__, parent=root)
        root.destroy()


if __name__ == "__main__":
    main()

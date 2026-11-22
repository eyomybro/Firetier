#!/usr/bin/env python3
"""Firetier web UI: a localhost-only JSON API over engine.py plus the static files in web/.

Run:  python server.py            (opens an Edge app window)
      python server.py --no-browser --port 8790 --token dev   (for testing)

Security: binds 127.0.0.1 only, checks the Host header (DNS rebinding), and every /api call
must carry the per-run random token in X-Firetier-Token. The only outbound traffic is the opt-in
Roblox account lookup in account.py (when the user clicks Connect) and update checks and downloads
from the GitHub repo set in Settings (updater.py).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import account as A  # noqa: E402
import engine as E  # noqa: E402
import updater as U  # noqa: E402

WEB = Path(__file__).resolve().parent / "web"
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".jpg": "image/jpeg", ".ico": "image/x-icon", ".json": "application/json",
        ".woff2": "font/woff2"}
MAX_BODY = E.MAX_JSON_BYTES + 1024 * 1024
# Motion defaults to full: the fire splash and click effects are the point, and Windows' "Animation
# effects" switch (often off on low-end PCs) would otherwise hide them. "system" follows Windows.
UI_PREFS = {"motion": ("full", "system", "reduced"), "density": ("comfortable", "compact"),
            "preview_quality": ("full", "fast"), "diag_on_start": (True, False)}
OPENABLE_URLS = {E.ALLOWLIST_SOURCE}


class ApiError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


class Api:
    def __init__(self, home: Path, lad: Path | None = None):
        self.home = Path(home)
        self.lad = lad
        self.store = E.ProfileStore(self.home)
        self.backups = E.BackupStore(self.home)
        self.settings_path = self.home / "settings.json"
        self.settings, notice = E.load_preferences(self.settings_path)
        self.presets = {p.id: p for p in E.builtin_presets()}
        self.account = A.AccountStore(self.home)
        self.lookup = A.lookup
        # Updates. The functions are attributes so tests can stand in for the network and the process.
        self.exe = U.running_exe()
        self.update_info: dict | None = None
        self.update_progress: list[int] | None = None
        self.update_lock = threading.Lock()
        self.update_check_fn, self.update_download_fn = U.check, U.download
        self.update_install_fn, self.update_relaunch_fn = U.install, U.relaunch
        self.exit_fn = lambda: os._exit(0)
        self.lock = threading.RLock()
        self._procs: tuple[float, set[str] | None, str | None] = (0.0, None, None)
        if notice:
            self.log(notice, "WARN")

    # --- helpers ---------------------------------------------------------------
    def log(self, msg: str, level: str = "INFO"):
        try:
            with open(self.home / "firetier.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {level:<4}  {msg}\n")
        except OSError:
            pass

    def log_tail(self, n: int = 200) -> list[dict]:
        p = self.home / "firetier.log"
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 256 * 1024))
                lines = f.read().decode("utf-8", "replace").splitlines()[-n:]
        except OSError:
            return []
        out = []
        for line in lines:
            m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  (?:(INFO|OK|WARN|FAIL)\s*  )?(.*)", line)
            if m:
                lvl = (m.group(2) or "INFO").lower()
                msg = m.group(3)
                if not m.group(2) and re.search(r"fail|error|couldn't|could not|traceback", msg, re.I):
                    lvl = "fail"
                out.append({"time": m.group(1), "level": lvl, "msg": msg})
            elif out:
                out[-1]["msg"] += "\n" + line
        return out

    def save_pref(self, key, value):
        if self.settings.get(key) == value:
            return
        updated = dict(self.settings, **{key: value})
        E.save_preferences(self.settings_path, self.settings, updated)
        self.settings = updated

    def targets(self) -> list[E.Target]:
        ts = E.detect_targets(self.lad)
        custom = self.settings.get("custom_target")
        if custom:
            ts.append(E.Target("custom", "Custom file", Path(custom), "custom", ["You picked this file by hand."]))
        return ts

    def target(self, tid: str | None = None) -> E.Target | None:
        ts = self.targets()
        want = tid or self.settings.get("target_id")
        return next((t for t in ts if t.id == want), ts[0] if ts and not tid else None)

    def profile(self, pid: str) -> E.Profile:
        if not isinstance(pid, str) or not pid:
            raise ApiError("missing profile id")
        if pid in self.presets:
            return self.presets[pid]
        try:
            return self.store.get(pid)
        except FileNotFoundError:
            raise ApiError("profile not found", 404)
        except ValueError as e:
            raise ApiError(f"profile can't be read: {e}")

    def processes(self) -> tuple[set[str] | None, str | None]:
        t, procs, err = self._procs
        if time.time() - t > 5:
            try:
                procs, err = E.running_processes(), None
            except OSError as e:
                procs, err = None, str(e)
            self._procs = (time.time(), procs, err)
        return procs, err

    @staticmethod
    def rule_view(r: E.Rule) -> dict:
        st, msg = r.status()
        return {"flag": r.flag, "value": r.value, "enabled": r.enabled, "status": st, "msg": msg,
                "group": r.group, "kind": E.flag_kind(r.flag), "help": E.FLAG_HELP.get(r.flag, ""),
                "range": list(E.RANGES[r.flag]) if r.flag in E.RANGES else None}

    def summary(self, p: E.Profile, state: E.TargetState | None) -> dict:
        sts = [r.status()[0] for r in p.rules]
        present, total = E.profile_presence(p, state) if state and not state.error else (0, len(p.effective_flags()))
        return {"id": p.id, "name": p.name, "description": p.description, "category": p.category,
                "game": p.game, "builtin": p.builtin, "unsupported": p.unsupported,
                "rules": len(p.rules), "active": sts.count(E.ACTIVE), "ignored": sts.count(E.IGNORED),
                "invalid": sts.count(E.INVALID), "disabled": sts.count(E.DISABLED),
                "conflicts": len(E.find_conflicts(p.rules)), "present": present, "total": total,
                "modified": p.modified, "source_kind": (p.source or {}).get("kind")}

    def source_summary(self, p: E.Profile) -> dict | None:
        if not p.source:
            return None
        orig = p.source.get("original")
        pairs, count = [], 0
        budget = [5000]

        def walk(node, path):
            nonlocal count
            if budget[0] <= 0 or len(pairs) >= 200:
                return
            budget[0] -= 1
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, f"{path}/{k}" if path else str(k))
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")
            elif not isinstance(node, bool) and re.fullmatch(r"(rbxassetid://)?\d{6,20}", str(node).strip()):
                count += 1
                pairs.append({"path": path, "value": str(node)})

        walk(orig, "")
        return {"kind": p.source.get("kind"), "imported": p.source.get("imported"),
                "top_keys": list(orig.keys())[:50] if isinstance(orig, dict) else [],
                "asset_ids_shown": pairs, "asset_ids_counted": E._count_asset_ids(orig, [200000]),
                "bytes": len(json.dumps(orig)) if orig is not None else 0}

    def detail(self, p: E.Profile) -> dict:
        t = self.target()
        state = E.read_target(t) if t else None
        d = self.summary(p, state)
        d.update({"rules_list": [self.rule_view(r) for r in p.rules],
                  "conflicts_list": E.find_conflicts(p.rules),
                  "report": [{"level": a, "text": b} for a, b in E.profile_report(p, t, state)],
                  "preview": E.preview_params(p.effective_flags()),
                  "source": self.source_summary(p), "created": p.created})
        return d

    def target_view(self, t: E.Target) -> dict:
        st = E.read_target(t)
        s = E.analyze_flags(st.flags) if not st.error else None
        return {"id": t.id, "label": t.label, "path": str(t.path), "kind": t.kind, "notes": t.notes,
                "version": t.version, "exists": st.exists, "error": st.error,
                "count": s.total if s else 0, "honored": len(s.active) if s else 0,
                "ignored": len(s.ignored) if s else 0, "invalid": len(s.invalid) if s else 0,
                "conflicts": E.find_conflicts([E.Rule(k, E.normalize_value(k, v)) for k, v in st.flags.items()])
                if not st.error else [], "flags": {k: E.normalize_value(k, v) for k, v in st.flags.items()},
                "writable": E._writable(t.path)}

    # --- endpoints ---------------------------------------------------------------
    def state(self, _q=None) -> dict:
        ts = self.targets()
        t = self.target()
        state = E.read_target(t) if t else None
        profiles = self.store.list()
        procs, perr = self.processes()
        prefs = {k: self.settings.get(k, v[0]) for k, v in UI_PREFS.items()}
        games = []
        for gid, g in E.GAMES.items():
            n = sum(1 for p in list(self.presets.values()) + profiles if p.game == gid)
            games.append({"id": gid, "name": g["name"], "place_id": g["place_id"], "notes": g["notes"],
                          "profiles": n})
        backups = self.backups.list()
        return {
            "app": {"name": E.APP_NAME, "version": E.APP_VERSION, "home": str(self.home),
                    "allowlist_posted": E.ALLOWLIST_POSTED, "allowlist_checked": E.ALLOWLIST_CHECKED,
                    "allowlist_source": E.ALLOWLIST_SOURCE, "game_scope_note": E.GAME_SCOPE_NOTE,
                    "python": sys.version.split()[0]},
            "allowlist": [{"flag": k, "group": g, "help": E.FLAG_HELP.get(k, ""), "kind": E.flag_kind(k),
                           "range": list(E.RANGES[k]) if k in E.RANGES else None} for k, g in E.ALLOWLIST.items()],
            "targets": [self.target_view(x) for x in ts],
            "target_id": t.id if t else None,
            "mode": self.settings.get("mode", "merge"),
            "last_profile": self.settings.get("last_profile") or "preset-rivals-notex",
            "favorites": self.settings.get("favorites", ["rivals"]),
            "prefs": prefs,
            "presets": [self.summary(p, state) for p in self.presets.values()],
            "profiles": [self.summary(p, state) for p in profiles],
            "profile_errors": [{"file": p.name, "error": e} for p, e in self.store.load_errors],
            "games": games,
            "backups": backups[:100],
            "backup_count": len(backups),
            "running": sorted(n for n in (procs or set()) if n in (
                "robloxplayerbeta.exe", "fishstrap.exe", "bloxstrap.exe", "voidstrap.exe")),
            "process_error": perr,
            "activity": list(reversed(self.log_tail(40))),
            "update": self.update_get(),
        }

    def get_profile(self, q):
        return self.detail(self.profile(q.get("id", "")))

    def save_profile(self, b):
        d = b.get("profile")
        if not isinstance(d, dict):
            raise ApiError("missing profile")
        old = self.profile(d.get("id", ""))
        if old.builtin:
            raise ApiError("Built-in presets are read-only. Duplicate it first.")
        d = dict(d, format=E.PROFILE_FORMAT, version=1, source=old.source, created=old.created)
        try:
            p = E.Profile.from_dict(d)
        except ValueError as e:
            raise ApiError(str(e))
        p.id = old.id
        self.store.save(p)
        self.log(f"Saved profile '{p.name}' ({len(p.rules)} rules).", "OK")
        return self.detail(p)

    def new_profile(self, b):
        name = str(b.get("name") or "New profile").strip()[:120] or "New profile"
        src = b.get("from")
        if src:
            p = self.store.duplicate(self.profile(src), name)
        else:
            p = E.Profile(name=name, game=b.get("game") if b.get("game") in E.GAMES else "rivals")
            self.store.save(p)
        self.log(f"Created profile '{p.name}'.", "OK")
        return self.detail(p)

    def rename_profile(self, b):
        p = self.profile(b.get("id", ""))
        if p.builtin:
            raise ApiError("Built-in presets can't be renamed.")
        p = self.store.rename(p.id, str(b.get("name", ""))[:120])
        self.log(f"Renamed profile to '{p.name}'.", "OK")
        return self.detail(p)

    def delete_profile(self, b):
        p = self.profile(b.get("id", ""))
        if p.builtin:
            raise ApiError("Built-in presets can't be deleted.")
        dst = self.store.delete(p.id)
        self.log(f"Moved profile '{p.name}' to {dst}.", "OK")
        if self.settings.get("last_profile") == p.id:
            self.save_pref("last_profile", "preset-rivals-notex")
        return {"ok": True, "message": f"'{p.name}' moved to the trash folder.", "path": str(dst)}

    def import_text(self, b):
        text = b.get("text")
        if not isinstance(text, str):
            raise ApiError("missing text")
        hint = re.sub(r"\.json$", "", str(b.get("name") or "Imported"), flags=re.I)[:80] or "Imported"
        r = E.import_profile_text(text, hint)
        out = {"kind": r.kind, "messages": r.messages, "supported": r.supported, "profile": None}
        if r.profile:
            self.store.save(r.profile)
            out["profile"] = self.detail(r.profile)
            self.log(f"Imported '{r.profile.name}' ({r.kind}). " + " ".join(r.messages),
                     "OK" if r.supported else "WARN")
        else:
            self.log(f"Import failed ({r.kind}): " + " ".join(r.messages), "FAIL")
        return out

    def export(self, q):
        p = self.profile(q.get("id", ""))
        if q.get("kind") == "flat":
            if p.unsupported:
                raise ApiError("Asset replacement imports have no FastFlags to export.")
            data = p.effective_flags()
            fname = f"{_safe(p.name)}.ClientAppSettings.json"
        elif p.unsupported and q.get("kind") == "original":
            data = p.source.get("original")
            fname = f"{_safe(p.name)}.original.json"
        else:
            data = p.to_dict()
            fname = f"{_safe(p.name)}.firetier.json"
        return {"filename": fname, "content": json.dumps(data, indent=2)}

    def apply(self, b):
        p = self.profile(b.get("id", ""))
        t = self.target(b.get("target_id"))
        if t is None:
            raise ApiError("No target selected. Pick one in Settings › Target file.")
        mode = b.get("mode") or self.settings.get("mode", "merge")
        if mode not in ("merge", "replace"):
            raise ApiError("mode must be merge or replace")
        r = E.apply_profile(p, t, self.backups, mode)
        self.log(f"Apply '{p.name}' to {t.label} ({mode}): {r.message}", "OK" if r.ok else "FAIL")
        if r.ok:
            self.save_pref("last_profile", p.id)
        return {"ok": r.ok, "message": r.message, "backup_id": r.backup_id, "written": len(r.written),
                "skipped": [{"flag": f, "why": w} for f, w in r.skipped], "verified": r.verified,
                "rolled_back": r.rolled_back, "target": t.label, "mode": mode}

    def clear(self, b):
        t = self.target(b.get("target_id"))
        if t is None:
            raise ApiError("No target selected.")
        r = E.clear_target(t, self.backups)
        self.log(f"Cleared {t.label}: {r.message}", "OK" if r.ok else "FAIL")
        return {"ok": r.ok, "message": r.message, "backup_id": r.backup_id, "verified": r.verified}

    def restore(self, b):
        bid = str(b.get("id", ""))
        try:
            msg = self.backups.restore(bid)
        except (OSError, ValueError) as e:
            self.log(f"Restore of backup {bid} failed: {e}", "FAIL")
            return {"ok": False, "message": str(e)}
        self.log(msg, "OK")
        return {"ok": True, "message": msg}

    def load_target(self, b):
        t = self.target(b.get("target_id"))
        if t is None:
            raise ApiError("No target selected.")
        st = E.read_target(t)
        if st.error:
            raise ApiError(f"Target file unreadable: {st.error}")
        if not st.flags:
            raise ApiError("The target file has no flags to load.")
        p = E.Profile(name=f"From {t.label} ({time.strftime('%H:%M')})",
                      rules=[E.Rule(k, E.normalize_value(k, v)) for k, v in st.flags.items()],
                      description=f"Loaded from {t.path}", game="all",
                      source={"kind": "target", "imported": time.time(), "original": st.flags})
        self.store.save(p)
        self.log(f"Loaded {len(p.rules)} flags from {t.label} as '{p.name}'.", "OK")
        return self.detail(p)

    def diagnostics(self, _q=None):
        checks = E.run_diagnostics(self.home, self.store, self.lad)
        self.log(f"Diagnostics: {sum(c.status == 'fail' for c in checks)} fail, "
                 f"{sum(c.status == 'warn' for c in checks)} warn.", "INFO")
        return {"checks": [c.__dict__ for c in checks], "ran": time.time()}

    def report(self, _q=None):
        st = self.state()
        checks = E.run_diagnostics(self.home, self.store, self.lad)
        lines = [f"Firetier {E.APP_VERSION} diagnostics report", time.strftime("%Y-%m-%d %H:%M:%S"),
                 f"Python {sys.version.split()[0]} on {sys.platform}", f"Data folder: {self.home}", "",
                 "Checks:"]
        lines += [f"  [{c.status.upper():4}] {c.name}: {c.detail}" + (f"\n         fix: {c.fix}" if c.fix else "")
                  for c in checks]
        lines += ["", "Targets:"]
        lines += [f"  {t['label']}: {t['path']} exists={t['exists']} flags={t['count']} honored={t['honored']} "
                  f"ignored={t['ignored']} invalid={t['invalid']}" for t in st["targets"]]
        lines += ["", f"Backups: {st['backup_count']}", "", "Recent log:"]
        lines += [f"  {e['time']} {e['level'].upper():4} {e['msg']}" for e in self.log_tail(60)]
        lines += ["", "In-game effect: not verified. Firetier can't see inside Roblox."]
        return {"filename": f"firetier-report-{time.strftime('%Y%m%d-%H%M%S')}.txt", "content": "\n".join(lines)}

    def log_get(self, q):
        return {"entries": list(reversed(self.log_tail(min(int(q.get("n", 300) or 300), 2000))))}

    def set_prefs(self, b):
        changed = []
        for k, v in b.items():
            if k in UI_PREFS:
                if v not in UI_PREFS[k]:
                    raise ApiError(f"invalid value for {k}")
            elif k == "mode":
                if v not in ("merge", "replace"):
                    raise ApiError("invalid mode")
            elif k == "target_id":
                if not any(t.id == v for t in self.targets()):
                    raise ApiError("unknown target")
            elif k == "last_profile":
                self.profile(v)
            elif k == "favorites":
                if not isinstance(v, list) or any(g not in E.GAMES for g in v):
                    raise ApiError("invalid favorites")
            elif k == "update_repo":
                v = v.strip() if isinstance(v, str) else v
                if v != "" and not U.valid_repo(v):
                    raise ApiError("Set the GitHub repo as owner/name, for example yourname/Firetier.")
                if v != self.settings.get("update_repo", U.DEFAULT_REPO):
                    self.update_info = None
            elif k == "update_auto":
                if not isinstance(v, bool):
                    raise ApiError("invalid value for update_auto")
            elif k == "custom_target":
                if v:
                    p = Path(str(v))
                    if not p.is_absolute() or p.suffix.lower() != ".json":
                        raise ApiError("Custom target must be an absolute path to a .json file.")
                    v = str(p)
                else:
                    v = ""
            else:
                raise ApiError(f"unknown setting {k}")
            self.save_pref(k, v)
            changed.append(k)
        if "custom_target" in changed:
            self.log(f"Custom target set to {b['custom_target'] or '(none)'}.", "OK")
            if b["custom_target"]:
                self.save_pref("target_id", "custom")
            elif self.settings.get("target_id") == "custom":
                self.save_pref("target_id", "")
        return {"ok": True, "changed": changed}

    def reset_prefs(self, _b):
        E.write_json_atomic(self.home / "settings.before-reset.json", self.settings)
        E.save_preferences(self.settings_path, self.settings, {})
        self.settings = {}
        self.log("Restored Firetier preferences to defaults.", "OK")
        return {"ok": True}

    def storage(self, _q=None):
        def size(d: Path):
            n = c = 0
            if d.is_dir():
                for f in d.rglob("*"):
                    if f.is_file():
                        n += f.stat().st_size
                        c += 1
            return n, c
        out = {}
        for name in ("profiles", "backups", "trash"):
            n, c = size(self.home / name)
            out[name] = {"bytes": n, "files": c, "path": str(self.home / name)}
        lg = self.home / "firetier.log"
        out["log"] = {"bytes": lg.stat().st_size if lg.exists() else 0, "files": int(lg.exists()), "path": str(lg)}
        return out

    def open_path(self, b):
        which = b.get("which")
        paths = {"home": self.home, "profiles": self.store.dir, "backups": self.backups.dir,
                 "trash": self.store.trash}
        if which == "target":
            t = self.target()
            if not t:
                raise ApiError("No target selected.")
            p = t.path.parent
        elif which in paths:
            p = paths[which]
        else:
            raise ApiError("unknown folder")
        if not p.exists():
            raise ApiError(f"{p} doesn't exist yet.")
        if sys.platform == "win32":
            os.startfile(str(p))  # noqa: S606 - opens Explorer on a folder we own or the user's target folder
        return {"ok": True, "path": str(p)}

    def open_url(self, b):
        url = b.get("url")
        info = self.update_info or {}
        page = info.get("page") if isinstance(info.get("page"), str) else ""
        release = page.lower().startswith(f"https://github.com/{info.get('repo', '')}/releases".lower())
        if url not in OPENABLE_URLS and not (release and url == page):
            raise ApiError("This link can't be opened from Firetier.")
        if sys.platform == "win32":
            os.startfile(url)  # noqa: S606 - fixed allowlisted URL, user-initiated
        return {"ok": True}


    def account_get(self, _q=None):
        lad = Path(self.lad) if self.lad else E.localappdata()
        return {"account": self.account.load(), "detected_user_id": A.detect_user_id(lad / "Roblox" / "logs")}

    def account_connect(self, b):
        try:
            info = self.lookup(b.get("query", ""))
        except A.AccountError as e:
            raise ApiError(str(e), 400 if isinstance(e, A.InputError) else 502) from e
        with self.lock:  # the lookup above runs unlocked so a slow network can't stall the UI
            acc = self.account.save(info)
            self.log("Connected a Roblox account" + (" with avatar." if acc.get("avatar_data") else " (no avatar available)."), "OK")
        return {"ok": True, "account": acc}

    def account_disconnect(self, _b):
        self.account.clear()
        self.log("Disconnected the Roblox account.", "OK")
        return {"ok": True}

    # --- updates -----------------------------------------------------------------
    def update_get(self, _q=None):
        info = self.update_info
        return {"repo": self.settings.get("update_repo", U.DEFAULT_REPO), "auto": self.settings.get("update_auto", True),
                "checked": self.settings.get("update_checked"), "can_install": self.exe is not None,
                "busy": self.update_lock.locked(), "progress": self.update_progress,
                "result": {k: v for k, v in info.items() if k != "exe_url"} if info else None}

    def update_check(self, b):
        repo = self.settings.get("update_repo", U.DEFAULT_REPO)
        if not repo:
            raise ApiError("Set the GitHub repo first (Settings › Updates).")
        try:
            info = self.update_check_fn(repo, E.APP_VERSION)
        except U.UpdateError as e:
            if not b.get("quiet"):
                self.log(f"Update check failed: {e}", "WARN")
            raise ApiError(str(e), 502) from e
        with self.lock:
            self.update_info = info
            self.save_pref("update_checked", time.time())
            if info["available"]:
                self.log(f"Firetier {info['latest']} is available (this is {info['current']}).", "INFO")
            elif not b.get("quiet"):
                self.log(f"Firetier {info['current']} is up to date.", "INFO")
        return self.update_get()

    def update_install(self, _b):
        info = self.update_info
        if not info or not info.get("available"):
            raise ApiError("Check for updates first.")
        if self.exe is None:
            raise ApiError("Firetier is running from its source files, not Firetier.exe, so it can't replace "
                           "itself. Download the new version from the release page.")
        if not self.update_lock.acquire(blocking=False):
            raise ApiError("An update is already downloading.", 409)
        try:
            exe = self.exe
            staged = exe.with_name(exe.stem + ".update" + exe.suffix)
            self.update_progress = [0, info["size"]]

            def progress(done, total):
                self.update_progress = [done, total]
            try:
                self.update_download_fn(info, staged, progress=progress)
            except U.UpdateError as e:
                self.log(f"Update to {info['latest']} failed: {e}", "FAIL")
                raise ApiError(str(e), 502) from e
            try:
                old = self.update_install_fn(staged, exe)
            except OSError as e:
                staged.unlink(missing_ok=True)
                self.log(f"Update to {info['latest']} failed: couldn't replace {exe.name} ({e}).", "FAIL")
                raise ApiError(f"Couldn't replace {exe.name}: {e}") from e
            try:
                self.update_relaunch_fn(exe)
            except OSError as e:
                os.replace(old, exe)  # put the working build back
                self.log(f"Update to {info['latest']} failed: the new build wouldn't start ({e}). "
                         f"Kept {info['current']}.", "FAIL")
                raise ApiError(f"The new build wouldn't start ({e}), so {info['current']} was put back.") from e
            self.log(f"Updated Firetier {info['current']} → {info['latest']} (SHA-256 verified). "
                     f"The previous build is kept as {old.name}. Restarting.", "OK")
            threading.Timer(1.5, self.exit_fn).start()  # let this response reach the page first
            return {"ok": True, "restarting": True, "version": info["latest"]}
        finally:
            self.update_progress = None
            self.update_lock.release()


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in name).strip() or "profile"


GET_ROUTES = {"state": Api.state, "profile": Api.get_profile, "export": Api.export,
              "diagnostics": Api.diagnostics, "report": Api.report, "log": Api.log_get,
              "storage": Api.storage, "account": Api.account_get, "update": Api.update_get}
POST_ROUTES = {"profile/save": Api.save_profile, "profile/new": Api.new_profile,
               "profile/rename": Api.rename_profile, "profile/delete": Api.delete_profile,
               "import": Api.import_text, "apply": Api.apply, "clear": Api.clear,
               "restore": Api.restore, "load-target": Api.load_target, "prefs": Api.set_prefs,
               "prefs/reset": Api.reset_prefs, "open": Api.open_path, "open-url": Api.open_url,
               "account/connect": Api.account_connect, "account/disconnect": Api.account_disconnect,
               "update/check": Api.update_check, "update/install": Api.update_install}

# Network-bound routes that take the lock themselves only around local writes.
UNLOCKED = {Api.account_connect, Api.update_get, Api.update_check, Api.update_install}


def make_handler(api: Api, token: str, port_ref: list[int], beat: list[float]):
    class H(BaseHTTPRequestHandler):
        server_version = "Firetier"
        sys_version = ""

        def log_message(self, *a):
            pass

        def _send(self, status, body: bytes, ctype="application/json; charset=utf-8", extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if ctype.startswith("text/html"):
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
                                 "style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; "
                                 "frame-ancestors 'none'; base-uri 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj, allow_nan=False).encode())

        def _host_ok(self):
            host = self.headers.get("Host", "")
            port = port_ref[0]
            return host in (f"127.0.0.1:{port}", f"localhost:{port}")

        def _api(self, method):
            if not secrets.compare_digest(self.headers.get("X-Firetier-Token", ""), token):
                return self._json(403, {"error": "forbidden"})
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{port_ref[0]}", f"http://localhost:{port_ref[0]}"):
                return self._json(403, {"error": "forbidden origin"})
            u = urllib.parse.urlsplit(self.path)
            route = u.path[len("/api/"):]
            beat[0] = time.time()
            if route == "ping":
                return self._json(200, {"ok": True})
            try:
                if method == "GET":
                    fn = GET_ROUTES.get(route)
                    arg = dict(urllib.parse.parse_qsl(u.query))
                else:
                    fn = POST_ROUTES.get(route)
                    n = int(self.headers.get("Content-Length") or 0)
                    if n > MAX_BODY:
                        raise ApiError("request too large", 413)
                    if (self.headers.get("Content-Type") or "").split(";")[0] != "application/json":
                        raise ApiError("expected JSON", 415)
                    arg = E.parse_json(self.rfile.read(n).decode("utf-8")) if n else {}
                    if not isinstance(arg, dict):
                        raise ApiError("expected a JSON object")
                if fn is None:
                    raise ApiError("not found", 404)
                if fn in UNLOCKED:
                    return self._json(200, fn(api, arg))
                with api.lock:
                    return self._json(200, fn(api, arg))
            except ApiError as e:
                return self._json(e.status, {"error": str(e)})
            except ConnectionError:  # the page dropped the request (reload, navigation); nothing to report
                self.close_connection = True
                return None
            except (OSError, ValueError) as e:
                api.log(f"{method} {route} failed: {e}", "FAIL")
                return self._json(500, {"error": str(e) or type(e).__name__})
            except Exception as e:  # last-resort: report, keep serving
                api.log(f"{method} {route} crashed: {traceback.format_exc()}", "FAIL")
                return self._json(500, {"error": f"Internal error: {type(e).__name__}: {e}"})

        def do_GET(self):
            if not self._host_ok():
                return self._send(421, b"bad host", "text/plain")
            if self.path.startswith("/api/"):
                return self._api("GET")
            path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (WEB / rel).resolve()
            if WEB.resolve() not in f.parents or not f.is_file() or f.suffix not in MIME:
                return self._send(404, b"not found", "text/plain")
            self._send(200, f.read_bytes(), MIME[f.suffix])

        do_HEAD = do_GET

        def do_POST(self):
            if not self._host_ok():
                return self._send(421, b"bad host", "text/plain")
            if not self.path.startswith("/api/"):
                return self._send(404, b"not found", "text/plain")
            return self._api("POST")

    return H


def find_edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.is_file():
                return str(p)
    return shutil.which("msedge")


class UIServer(ThreadingHTTPServer):
    # socketserver's default listen backlog is 5. On Windows a full backlog refuses new connections
    # outright, so when the accept loop lags (Roblox loading the CPU) the browser's parallel first-load
    # requests lose a script and the window stays stuck on the splash.
    request_queue_size = 128
    daemon_threads = True


def serve(home: Path, port: int = 0, token: str | None = None, browser: bool = True, lad: Path | None = None):
    home.mkdir(parents=True, exist_ok=True)
    token = token or secrets.token_urlsafe(24)
    with E.operation_lock(home / "settings.json"):
        api = Api(home, lad)
        port_ref, beat = [0], [time.time()]
        httpd = UIServer(("127.0.0.1", port), make_handler(api, token, port_ref, beat))
        port_ref[0] = httpd.server_address[1]
        url = f"http://127.0.0.1:{port_ref[0]}/#t={token}"
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        api.log(f"Web UI started on 127.0.0.1:{port_ref[0]}.", "INFO")
        try:
            if not browser:
                print(url, flush=True)
                while True:
                    time.sleep(3600)
            edge = find_edge()
            if edge:
                prof = home / "webview"
                proc = subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={prof}",
                                         "--window-size=1440,900", "--no-first-run",
                                         "--no-default-browser-check", "--disable-sync"])
                proc.wait()
                # Edge can hand off to an already-running instance of the same profile; keep
                # serving while the page still pings.
                while time.time() - beat[0] < 30:
                    time.sleep(2)
            else:
                import webbrowser
                webbrowser.open(url)
                while time.time() - beat[0] < 60:
                    time.sleep(2)
        except KeyboardInterrupt:
            pass
        finally:
            httpd.shutdown()
            api.log("Web UI stopped.", "INFO")


def main():
    ap = argparse.ArgumentParser(description="Firetier web UI")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--token")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--home")
    a = ap.parse_args()
    home = Path(a.home) if a.home else E.home_dir()
    wait = os.environ.pop("FIRETIER_WAIT_PID", "")
    if wait.isdigit():  # started by an update: the old server still holds the lock for a moment
        U.wait_for_exit(int(wait))
    try:
        serve(home, a.port, a.token, not a.no_browser)
    except (OSError, ValueError) as exc:
        if sys.platform == "win32" and not a.no_browser:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc) or type(exc).__name__, "Firetier could not start", 0x10)
        else:
            print(f"Firetier could not start: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

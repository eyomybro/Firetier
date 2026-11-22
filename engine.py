"""Firetier engine: FastFlag profiles, allowlist validation, and safe apply
(backup -> validate -> write -> verify -> roll back on failure).

No GUI code here, so everything can be tested headless.
Firetier only edits ClientAppSettings.json, Roblox's own local configuration
file. It never touches the Roblox executable, its asset cache, or anti-cheat.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "Firetier"
APP_VERSION = "0.2.0"
PROFILE_FORMAT = "firetier-profile"

# --- Roblox FastFlag allowlist ------------------------------------------------
# Copied verbatim from Roblox's announcement. Flags not listed here are ignored
# by the Roblox client when they appear in ClientAppSettings.json.
ALLOWLIST_SOURCE = (
    "https://devforum.roblox.com/t/allowlist-for-local-client-configuration-via-fast-flags/3966569"
)
ALLOWLIST_POSTED = "2025-09-29 (post last edited 2025-10-16)"
ALLOWLIST_CHECKED = "2026-11-21"

ALLOWLIST: dict[str, str] = {
    "DFIntCSGLevelOfDetailSwitchingDistance": "Geometry",
    "DFIntCSGLevelOfDetailSwitchingDistanceL12": "Geometry",
    "DFIntCSGLevelOfDetailSwitchingDistanceL23": "Geometry",
    "DFIntCSGLevelOfDetailSwitchingDistanceL34": "Geometry",
    "FFlagHandleAltEnterFullscreenManually": "Rendering",
    "DFFlagTextureQualityOverrideEnabled": "Rendering",
    "DFIntTextureQualityOverride": "Rendering",
    "FIntDebugForceMSAASamples": "Rendering",
    "DFFlagDisableDPIScale": "Rendering",
    "FFlagDebugGraphicsPreferD3D11": "Rendering",
    "FFlagDebugSkyGray": "Rendering",
    "DFFlagDebugPauseVoxelizer": "Rendering",
    "DFIntDebugFRMQualityLevelOverride": "Rendering",
    "FIntFRMMaxGrassDistance": "Rendering",
    "FIntFRMMinGrassDistance": "Rendering",
    "FFlagDebugGraphicsPreferVulkan": "Rendering",
    "FFlagDebugGraphicsPreferOpenGL": "Rendering",
    "FIntGrassMovementReducedMotionFactor": "User Interface",
}

FLAG_HELP: dict[str, str] = {
    "DFIntCSGLevelOfDetailSwitchingDistance": "Distance at which parts/unions drop detail. 0 = lowest detail always.",
    "DFIntCSGLevelOfDetailSwitchingDistanceL12": "Level-of-detail switch distance, level 1 to 2.",
    "DFIntCSGLevelOfDetailSwitchingDistanceL23": "Level-of-detail switch distance, level 2 to 3.",
    "DFIntCSGLevelOfDetailSwitchingDistanceL34": "Level-of-detail switch distance, level 3 to 4.",
    "FFlagHandleAltEnterFullscreenManually": "How Alt+Enter fullscreen is handled.",
    "DFFlagTextureQualityOverrideEnabled": "Turns on the texture quality override below.",
    "DFIntTextureQualityOverride": "Forced texture quality. 0 is the lowest (closest to no textures).",
    "FIntDebugForceMSAASamples": "Anti-aliasing sample count. Lower = faster.",
    "DFFlagDisableDPIScale": "Ignore Windows display scaling.",
    "FFlagDebugGraphicsPreferD3D11": "Prefer the Direct3D 11 renderer.",
    "FFlagDebugSkyGray": "Plain grey sky instead of the skybox.",
    "DFFlagDebugPauseVoxelizer": "Pause lighting voxel updates: flatter lighting, less CPU work.",
    "DFIntDebugFRMQualityLevelOverride": "Forced render quality level. 1 is the lowest.",
    "FIntFRMMaxGrassDistance": "Maximum grass draw distance. 0 = no grass.",
    "FIntFRMMinGrassDistance": "Minimum grass draw distance.",
    "FFlagDebugGraphicsPreferVulkan": "Prefer the Vulkan renderer.",
    "FFlagDebugGraphicsPreferOpenGL": "Prefer the OpenGL renderer.",
    "FIntGrassMovementReducedMotionFactor": "Grass movement when Reduced Motion is on.",
}

# Below this, Roblox's texture budget can't hold a scene's textures (seen: Vulkan on a GT 1030 got 64 MB).
VRAM_WARN_MB = 256

RENDERER_FLAGS = (
    "FFlagDebugGraphicsPreferD3D11",
    "FFlagDebugGraphicsPreferVulkan",
    "FFlagDebugGraphicsPreferOpenGL",
)

# Usual ranges. Values outside are warnings, not errors.
RANGES: dict[str, tuple[int, int]] = {
    "DFIntTextureQualityOverride": (0, 3),
    "DFIntDebugFRMQualityLevelOverride": (1, 21),
    "FIntDebugForceMSAASamples": (0, 8),
}

GAMES: dict[str, dict] = {
    "rivals": {
        "name": "Roblox Rivals",
        "place_id": 17625359962,
        "notes": "Busy FFA lobbies are CPU-bound (many characters). Render-quality and "
        "lighting flags help more than texture quality.",
    },
    "all": {"name": "All Roblox games", "place_id": None, "notes": ""},
}
GAME_SCOPE_NOTE = (
    "FastFlags apply to every Roblox game. Game profiles only organize presets; "
    "they can't limit a flag to one game."
)

# Rule statuses
ACTIVE, IGNORED, INVALID, DISABLED = "active", "ignored", "invalid", "disabled"

_KIND_RE = re.compile(r"^(DF|F)(Flag|Int|String|Log)[A-Za-z0-9_]+$")
_INT_RE = re.compile(r"[+-]?\d+")


def flag_kind(name: str) -> str | None:
    m = _KIND_RE.match(name or "")
    return m.group(2) if m else None


def normalize_value(name: str, value) -> str:
    if isinstance(value, bool):
        value = "True" if value else "False"
    v = str(value).strip()
    kind = flag_kind(name)
    if kind == "Flag" and v.lower() in ("true", "false"):
        return "True" if v.lower() == "true" else "False"
    if kind in ("Int", "Log") and _INT_RE.fullmatch(v):
        if len(v.lstrip("+-")) <= 20:
            return str(int(v))
    return v


def value_error(name: str, value) -> str | None:
    kind = flag_kind(name)
    if kind is None:
        return ("not a FastFlag name (must start with FFlag, DFFlag, FInt, DFInt, "
                "FString, DFString, FLog or DFLog)")
    v = normalize_value(name, value)
    if kind == "Flag" and v not in ("True", "False"):
        return "value must be True or False"
    if kind in ("Int", "Log") and (not _INT_RE.fullmatch(v) or len(v.lstrip("+-")) > 20):
        return "value must be a whole number"
    return None


def range_warning(name: str, value) -> str | None:
    r = RANGES.get(name)
    if not r:
        return None
    try:
        n = int(normalize_value(name, value))
    except ValueError:
        return None
    lo, hi = r
    if not lo <= n <= hi:
        return f"{n} is outside the usual range {lo}-{hi}"
    return None


# --- Model ----------------------------------------------------------------------
@dataclass
class Rule:
    flag: str
    value: str
    enabled: bool = True

    def status(self) -> tuple[str, str]:
        if not self.enabled:
            return DISABLED, "disabled"
        err = value_error(self.flag, self.value)
        if err:
            return INVALID, err
        if self.flag not in ALLOWLIST:
            return IGNORED, "not on Roblox's allowlist: Roblox ignores it"
        return ACTIVE, range_warning(self.flag, self.value) or "honored by Roblox"

    @property
    def group(self) -> str:
        return ALLOWLIST.get(self.flag, "Not allowlisted")


@dataclass
class Profile:
    name: str
    rules: list[Rule] = field(default_factory=list)
    description: str = ""
    category: str = "User-created"
    game: str = "rivals"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    builtin: bool = False
    source: dict | None = None
    created: float = field(default_factory=time.time)
    modified: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "format": PROFILE_FORMAT,
            "version": 1,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "game": self.game,
            "created": self.created,
            "modified": self.modified,
            "rules": [{"flag": r.flag, "value": r.value, "enabled": r.enabled} for r in self.rules],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        if not isinstance(d, dict) or d.get("format") != PROFILE_FORMAT:
            raise ValueError("not a Firetier profile")
        if not isinstance(d.get("name"), str) or not d["name"].strip():
            raise ValueError("profile has no name")
        if type(d.get("version", 1)) is not int or d.get("version", 1) != 1:
            raise ValueError("unsupported profile version")
        rules_in = d.get("rules", [])
        if not isinstance(rules_in, list):
            raise ValueError("'rules' must be a list")
        rules = []
        for i, r in enumerate(rules_in):
            if not isinstance(r, dict) or not isinstance(r.get("flag"), str):
                raise ValueError(f"rule {i + 1} is malformed")
            if type(r.get("enabled", True)) is not bool or not _is_scalar(r.get("value", "")):
                raise ValueError(f"rule {i + 1} has an invalid value or enabled state")
            rules.append(Rule(r["flag"].strip(), normalize_value(r["flag"], r.get("value", "")),
                              bool(r.get("enabled", True))))
        game = d.get("game", "all")
        if not isinstance(game, str):
            raise ValueError("game must be a string")
        game = game if game in GAMES else "all"
        for key in ("created", "modified"):
            if key in d:
                validate_timestamp(d[key])
        return cls(
            name=d["name"].strip(),
            rules=rules,
            description=str(d.get("description", "")),
            category=str(d.get("category", "User-created")),
            game=game,
            id=str(d.get("id") or uuid.uuid4().hex[:12]),
            source=d.get("source") if isinstance(d.get("source"), dict) else None,
            created=float(d.get("created", time.time())),
            modified=float(d.get("modified", time.time())),
        )

    def effective_flags(self) -> dict[str, str]:
        """Flags that would actually be written: enabled, valid, allowlisted."""
        return {r.flag: normalize_value(r.flag, r.value) for r in self.rules if r.status()[0] == ACTIVE}

    def clone(self, name: str | None = None) -> "Profile":
        p = copy.deepcopy(self)
        p.id = uuid.uuid4().hex[:12]
        p.builtin = False
        p.name = name or f"{self.name} (copy)"
        if self.category.startswith("Built-in"):
            p.category = "User-created"
        p.created = p.modified = time.time()
        return p

    @property
    def unsupported(self) -> bool:
        return bool(self.source and self.source.get("kind") == "asset-replacement")


@dataclass
class FlagSummary:
    total: int
    active: list[str]
    ignored: list[str]
    invalid: list[str]


def analyze_flags(flags: dict) -> FlagSummary:
    active, ignored, invalid = [], [], []
    for k, v in flags.items():
        st = Rule(k, normalize_value(k, v)).status()[0]
        {ACTIVE: active, IGNORED: ignored, INVALID: invalid}[st].append(k)
    return FlagSummary(len(flags), active, ignored, invalid)


def find_conflicts(rules: list[Rule]) -> list[str]:
    out = []
    by_flag: dict[str, list[Rule]] = {}
    for r in rules:
        if r.enabled:
            by_flag.setdefault(r.flag, []).append(r)
    for f, rs in by_flag.items():
        if len(rs) > 1 and len({normalize_value(f, r.value) for r in rs}) > 1:
            out.append(f"{f} is set {len(rs)} times with different values; the last one wins.")
    eff = {r.flag: normalize_value(r.flag, r.value) for r in rules if r.status()[0] == ACTIVE}
    renderers = [f for f in RENDERER_FLAGS if eff.get(f) == "True"]
    if len(renderers) > 1:
        out.append("More than one graphics API is preferred (" + ", ".join(renderers)
                   + "). Keep only one; which one wins is not documented.")
    if "DFIntTextureQualityOverride" in eff and eff.get("DFFlagTextureQualityOverrideEnabled") != "True":
        out.append("DFIntTextureQualityOverride does nothing unless "
                   "DFFlagTextureQualityOverrideEnabled is True.")
    mn, mx = eff.get("FIntFRMMinGrassDistance"), eff.get("FIntFRMMaxGrassDistance")
    if mn is not None and mx is not None and int(mn) > int(mx):
        out.append("FIntFRMMinGrassDistance is larger than FIntFRMMaxGrassDistance.")
    for r in rules:
        if r.status()[0] == ACTIVE:
            w = range_warning(r.flag, r.value)
            if w:
                out.append(f"{r.flag}: {w}.")
    return out


# --- Built-in presets -------------------------------------------------------------
def _p(pid, name, category, desc, flags, game="rivals") -> Profile:
    return Profile(name=name, category=category, description=desc, game=game, id=pid, builtin=True,
                   rules=[Rule(k, v) for k, v in flags.items()], created=0, modified=0)


_LOW_GEOMETRY = {
    "DFIntCSGLevelOfDetailSwitchingDistance": "0",
    "DFIntCSGLevelOfDetailSwitchingDistanceL12": "0",
    "DFIntCSGLevelOfDetailSwitchingDistanceL23": "0",
    "DFIntCSGLevelOfDetailSwitchingDistanceL34": "0",
}


def builtin_presets() -> list[Profile]:
    def renderer_flags(preferred):
        return {flag: "True" if flag == preferred else "False" for flag in RENDERER_FLAGS}

    return [
        _p("preset-rivals-notex", "Rivals: No Textures (max allowed)", "Built-in: No Textures",
           "Lowest texture quality, grey sky, lowest render quality, no grass, lowest geometry detail, "
           "on Direct3D 11. This is as close to no textures as the allowlist permits. Lighting keeps "
           "updating so it doesn't go stale between rounds. Vulkan is switched off: on 2 GB cards "
           "Roblox's Vulkan path can budget only 64 MB of video memory, so textures flicker and "
           "reload and the game stutters.",
           {
               "DFFlagTextureQualityOverrideEnabled": "True",
               "DFIntTextureQualityOverride": "0",
               "FFlagDebugSkyGray": "True",
               "DFIntDebugFRMQualityLevelOverride": "1",
               "DFFlagDebugPauseVoxelizer": "False",
               "FIntDebugForceMSAASamples": "1",
               "FIntFRMMinGrassDistance": "0",
               "FIntFRMMaxGrassDistance": "0",
               **_LOW_GEOMETRY,
               **renderer_flags("FFlagDebugGraphicsPreferD3D11"),
           }),
        _p("preset-rivals-fps", "Rivals: Max FPS (keeps textures)", "Built-in: Low-detail visuals",
           "Cuts the expensive work (render quality, lighting, grass, geometry detail) "
           "and returns texture quality to Roblox's normal selection.",
           {
               "DFFlagTextureQualityOverrideEnabled": "False",
               "DFIntDebugFRMQualityLevelOverride": "1",
               "DFFlagDebugPauseVoxelizer": "True",
               "FIntDebugForceMSAASamples": "1",
               "FIntFRMMinGrassDistance": "0",
               "FIntFRMMaxGrassDistance": "0",
               **_LOW_GEOMETRY,
           }),
        _p("preset-balanced", "Balanced low detail", "Built-in: Low-detail visuals",
           "Moderate render quality with no grass. Looks better, still lighter than default.",
           {
               "DFIntDebugFRMQualityLevelOverride": "5",
               "FIntDebugForceMSAASamples": "2",
               "FIntFRMMinGrassDistance": "0",
               "FIntFRMMaxGrassDistance": "0",
           }, game="all"),
        _p("preset-vulkan", "Renderer: Vulkan", "Built-in: Renderer",
           "Prefer Vulkan. Try this and D3D11 and keep whichever is smoother on your PC.",
           renderer_flags("FFlagDebugGraphicsPreferVulkan"), game="all"),
        _p("preset-d3d11", "Renderer: Direct3D 11", "Built-in: Renderer",
           "Prefer Direct3D 11.", renderer_flags("FFlagDebugGraphicsPreferD3D11"), game="all"),
        _p("preset-opengl", "Renderer: OpenGL", "Built-in: Renderer",
           "Prefer OpenGL. Usually only useful on old GPUs.",
           renderer_flags("FFlagDebugGraphicsPreferOpenGL"), game="all"),
    ]


# --- Files ------------------------------------------------------------------------
MAX_JSON_BYTES = 20 * 1024 * 1024


def home_dir() -> Path:
    env = os.environ.get("FIRETIER_HOME")
    if env:
        return Path(env)
    return localappdata() / APP_NAME


def localappdata() -> Path:
    env = os.environ.get("FIRETIER_LOCALAPPDATA") or os.environ.get("LOCALAPPDATA")
    return Path(env) if env else Path.home() / "AppData" / "Local"


def validate_timestamp(value):
    try:
        valid = not isinstance(value, bool) and math.isfinite(float(value))
        if valid:
            time.localtime(float(value))
            return
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    raise ValueError("invalid timestamp")


_END = object()


def parse_json(text):
    def reject_constant(value):
        raise ValueError(f"invalid JSON number {value}")
    try:
        data = json.loads(text, parse_constant=reject_constant)
        if isinstance(data, (dict, list)):
            stack = [iter(data.values() if isinstance(data, dict) else data)]
            while stack:
                node = next(stack[-1], _END)
                if node is _END:
                    stack.pop()
                elif isinstance(node, (dict, list)):
                    if len(stack) >= 128:
                        raise ValueError("JSON nesting exceeds 128 levels")
                    stack.append(iter(node.values() if isinstance(node, dict) else node))
        return data
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc


def read_json(path: Path):
    path = Path(path)
    with path.open("rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size > MAX_JSON_BYTES:
            raise ValueError(f"JSON exceeds {MAX_JSON_BYTES} bytes")
        data = f.read(size + 1)
        if len(data) > size:
            raise ValueError("JSON file changed while being read")
    if len(data) > MAX_JSON_BYTES:
        raise ValueError(f"JSON exceeds {MAX_JSON_BYTES} bytes")
    return parse_json(data.decode("utf-8-sig"))


def write_json_atomic(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, allow_nan=False)
            f.flush()
            if f.tell() > MAX_JSON_BYTES:
                raise ValueError(f"Serialized JSON exceeds {MAX_JSON_BYTES} bytes")
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()



@contextmanager
def operation_lock(path):
    """Nonblocking, process-wide Windows mutex. The OS releases it on process exit."""
    if sys.platform != "win32":
        yield
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.ReleaseMutex.argtypes = kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    key = os.path.normcase(str(Path(path).resolve()))
    name = "Local\\Firetier-" + hashlib.sha256(os.fsencode(key)).hexdigest()
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        if result == 258:
            raise OSError(f"Another Firetier operation is using {path}. Try again when it finishes.")
        if result not in (0, 128):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            kernel.ReleaseMutex(handle)
    finally:
        kernel.CloseHandle(handle)

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Profile store ----------------------------------------------------------------

def load_preferences(path):
    def validated(file):
        settings = read_json(file)
        if not isinstance(settings, dict):
            raise ValueError("preferences must be a JSON object")
        for key in ("last_profile", "target_id", "custom_target"):
            if key in settings and not isinstance(settings[key], str):
                raise ValueError(f"invalid {key}")
        if settings.get("mode", "merge") not in ("merge", "replace"):
            raise ValueError("invalid apply mode")
        return settings

    previous = path.with_name("settings.previous.json")
    try:
        return validated(path), ""
    except FileNotFoundError:
        if not previous.exists():
            return {}, ""
        reason = "Preferences file is missing."
    except ValueError as exc:
        damaged = path.with_name(f"settings.damaged-{uuid.uuid4().hex}.json")
        path.replace(damaged)
        reason = f"Preserved invalid settings in {damaged.name} ({exc})."
    try:
        settings = validated(previous)
    except (FileNotFoundError, ValueError):
        settings = {}
        reason += " Loaded defaults."
    else:
        reason += " Recovered previous preferences."
    write_json_atomic(path, settings)
    return settings, reason


def save_preferences(path, current, updated):
    if path.exists():
        write_json_atomic(path.with_name("settings.previous.json"), current)
    write_json_atomic(path, updated)

class ProfileStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / "profiles"
        self.trash = self.root / "trash"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.load_errors: list[tuple[Path, str]] = []

    def _path(self, pid: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", pid):
            raise ValueError("bad profile id")
        return self.dir / f"{pid}.json"

    def list(self) -> list[Profile]:
        out, self.load_errors = [], []
        for p in sorted(self.dir.glob("*.json")):
            try:
                prof = self.get(p.stem)
                out.append(prof)
            except (OSError, ValueError) as e:
                self.load_errors.append((p, str(e)))
        return sorted(out, key=lambda x: x.name.lower())

    def get(self, pid: str) -> Profile:
        if pid.startswith("preset-"):
            raise ValueError("reserved preset id")
        prof = Profile.from_dict(read_json(self._path(pid)))
        prof.id = pid
        return prof

    def save(self, profile: Profile) -> None:
        if profile.builtin:
            raise ValueError("Built-in presets are read-only. Duplicate it first.")
        profile.modified = time.time()
        write_json_atomic(self._path(profile.id), profile.to_dict())

    def rename(self, pid: str, new_name: str) -> Profile:
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("name can't be empty")
        p = self.get(pid)
        p.name = new_name
        self.save(p)
        return p

    def duplicate(self, profile: Profile, name: str | None = None) -> Profile:
        p = profile.clone(name)
        self.save(p)
        return p

    def delete(self, pid: str) -> Path:
        """Moves the profile to the trash folder instead of deleting it."""
        src = self._path(pid)
        self.trash.mkdir(parents=True, exist_ok=True)
        dst = self.trash / f"{pid}-{uuid.uuid4().hex}.json"
        shutil.move(str(src), str(dst))
        return dst


# --- Import / export --------------------------------------------------------------
@dataclass
class ImportResult:
    profile: Profile | None
    kind: str
    messages: list[str]
    supported: bool


def _is_scalar(v) -> bool:
    return isinstance(v, (str, int, float, bool))


def _count_asset_ids(data, budget: list[int]) -> int:
    """Counts values that look like Roblox asset ids, walking at most budget[0] nodes."""
    if budget[0] <= 0:
        return 0
    budget[0] -= 1
    if isinstance(data, bool):
        return 0
    if isinstance(data, int):
        return 1 if data >= 100000 else 0
    if isinstance(data, str):
        s = data.strip()
        return 1 if re.fullmatch(r"(rbxassetid://)?\d{6,20}", s) else 0
    if isinstance(data, dict):
        count = 0
        for key, value in data.items():
            if budget[0] <= 0:
                break
            count += int(bool(re.fullmatch(r"\d{6,20}", key)))
            count += _count_asset_ids(value, budget)
        return count
    if isinstance(data, list):
        count = 0
        for value in data:
            if budget[0] <= 0:
                break
            count += _count_asset_ids(value, budget)
        return count
    return 0


def import_profile_text(text: str, name_hint: str = "Imported") -> ImportResult:
    if len(text.encode("utf-8", "ignore")) > MAX_JSON_BYTES:
        return ImportResult(None, "too-large", ["File is too large to import (limit 20 MB)."], False)
    try:
        data = parse_json(text)
    except json.JSONDecodeError as e:
        return ImportResult(None, "invalid-json",
                            [f"Not valid JSON: {e.msg} at line {e.lineno}, column {e.colno}."], False)

    except ValueError as e:
        return ImportResult(None, "invalid-json", [str(e)], False)

    if isinstance(data, dict) and data.get("format") == PROFILE_FORMAT:
        try:
            p = Profile.from_dict(data)
        except ValueError as e:
            return ImportResult(None, "firetier", [f"Broken Firetier profile: {e}."], False)
        p.id = uuid.uuid4().hex[:12]
        return ImportResult(p, "firetier", [f"Imported Firetier profile '{p.name}' "
                                            f"({len(p.rules)} rules)."], not p.unsupported)

    if isinstance(data, dict) and all(_is_scalar(v) for v in data.values()):
        flagish = sum(1 for k in data if flag_kind(k))
        if not data or flagish * 2 >= len(data):
            rules = [Rule(k.strip(), normalize_value(k, v)) for k, v in data.items()]
            s = analyze_flags(data)
            p = Profile(name=name_hint, rules=rules, description="Imported FastFlag JSON",
                        source={"kind": "fastflag-json", "imported": time.time(), "original": data})
            msgs = [f"Imported {s.total} flag(s).",
                    f"{len(s.active)} honored by Roblox, {len(s.ignored)} ignored (not on the "
                    f"allowlist), {len(s.invalid)} invalid."]
            return ImportResult(p, "fastflag-json", msgs, True)

    if _count_asset_ids(data, [200000]) > 0:
        p = Profile(name=f"{name_hint} (asset replacement)", rules=[], category="Unsupported import",
                    description="Fleasion-style asset replacement data, stored unchanged.",
                    game="all",
                    source={"kind": "asset-replacement", "imported": time.time(), "original": data})
        return ImportResult(p, "asset-replacement", [
            "This looks like a Fleasion-style asset replacement profile.",
            "Firetier keeps the original data unchanged and can export it again, but it can't "
            "apply it. Replacing Roblox's assets means modifying the game's asset cache or "
            "delivery, and Firetier doesn't do that. Firetier only applies FastFlags.",
        ], False)

    return ImportResult(None, "unknown", [
        'Unrecognized JSON. Expected a FastFlag object like {"DFIntTextureQualityOverride": "0"} '
        "or a Firetier profile."], False)


def import_profile_file(path: Path) -> ImportResult:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            return ImportResult(None, "too-large", ["File is too large to import (limit 20 MB)."], False)
        with path.open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size > MAX_JSON_BYTES:
                return ImportResult(None, "too-large", ["File exceeds the import limit."], False)
            raw = f.read(size + 1)
            if len(raw) > size:
                return ImportResult(None, "unreadable", ["File changed while being read."], False)
        if len(raw) > MAX_JSON_BYTES:
            return ImportResult(None, "too-large", ["File exceeds the import limit."], False)
        text = raw.decode("utf-8-sig")
    except MemoryError:
        return ImportResult(None, "out-of-memory", ["Insufficient memory to read this file."], False)
    except (OSError, UnicodeDecodeError) as e:
        return ImportResult(None, "unreadable", [f"Could not read the file: {e}"], False)
    try:
        return import_profile_text(text, path.stem)
    except MemoryError:
        return ImportResult(None, "out-of-memory", ["Insufficient memory to import this file. Close other applications and retry."], False)


def export_profile(profile: Profile, path: Path) -> None:
    write_json_atomic(path, profile.to_dict())


def export_flat(profile: Profile, path: Path) -> int:
    flags = profile.effective_flags()
    write_json_atomic(path, flags)
    return len(flags)


# --- Targets ----------------------------------------------------------------------
BOOTSTRAPPERS = ("Fishstrap", "Bloxstrap", "Voidstrap")


@dataclass
class Target:
    id: str
    label: str
    path: Path
    kind: str  # "bootstrapper" | "roblox" | "custom"
    notes: list[str] = field(default_factory=list)
    version: str | None = None


@dataclass
class TargetState:
    exists: bool
    flags: dict
    error: str | None = None


def _player_versions(d: Path) -> list[str]:
    if not d.is_dir():
        return []
    found = []
    for p in d.iterdir():
        if (p / "RobloxPlayerBeta.exe").is_file():
            found.append((p.stat().st_mtime, p.name))
    return [n for _, n in sorted(found, reverse=True)]


def detect_targets(lad: Path | None = None) -> list[Target]:
    lad = Path(lad) if lad else localappdata()
    out: list[Target] = []
    boots: list[str] = []
    for b in BOOTSTRAPPERS:
        root = lad / b
        if root.is_dir():
            vers = _player_versions(root / "Versions")
            out.append(Target(
                b.lower(), f"{b} FastFlags",
                root / "Modifications" / "ClientSettings" / "ClientAppSettings.json", "bootstrapper",
                [f"{b} copies this file into Roblox each time it launches it. "
                 f"Start Roblox through {b} for changes to load.",
                 f"If {b}'s own FastFlag editor saves afterwards, it can overwrite changes made here."],
                version=vers[0] if vers else None))
            boots.append(b)
    for v in _player_versions(lad / "Roblox" / "Versions"):
        notes = ["Roblox clears this folder when it updates, so re-apply after updates."]
        if boots:
            notes.insert(0, f"{boots[0]} is installed and rewrites this file when it launches Roblox. "
                            f"Use the {boots[0]} target instead.")
        out.append(Target(f"roblox-{v}", f"Roblox {v}",
                          lad / "Roblox" / "Versions" / v / "ClientSettings" / "ClientAppSettings.json",
                          "roblox", notes, version=v))
    return out


def read_target(target: Target) -> TargetState:
    p = target.path
    if not p.is_file():
        return TargetState(False, {})
    try:
        data = read_json(p)
    except (OSError, ValueError) as e:
        return TargetState(True, {}, str(e))
    if not isinstance(data, dict):
        return TargetState(True, {}, "file is JSON but not an object")
    return TargetState(True, data)


def profile_presence(profile: Profile, state: TargetState) -> tuple[int, int]:
    eff = profile.effective_flags()
    present = sum(1 for k, v in eff.items()
                  if k in state.flags and normalize_value(k, state.flags[k]) == v)
    return present, len(eff)


# --- Backups ----------------------------------------------------------------------
class BackupStore:
    def __init__(self, root: Path):
        self.dir = Path(root) / "backups"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.load_errors = []

    def create(self, target: Target, reason: str) -> str:
        bid = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        d = self.dir / bid
        d.mkdir(parents=True)
        existed = target.path.is_file()
        if target.path.exists() and not existed:
            raise OSError("Target is not a regular file")
        digest = None
        if existed:
            dst = d / "ClientAppSettings.json"
            shutil.copy2(target.path, dst)
            digest = sha256(dst)
            if sha256(target.path) != digest:
                raise OSError("backup copy doesn't match the original file")
        write_json_atomic(d / "meta.json", {
            "id": bid, "created": time.time(), "reason": reason,
            "target_id": target.id, "target_label": target.label, "target_kind": target.kind,
            "target_path": str(target.path), "existed": existed, "sha256": digest,
        })
        return bid

    def list(self, target_id: str | None = None) -> list[dict]:
        out, self.load_errors = [], []
        for d in self.dir.iterdir():
            if not d.is_dir():
                continue
            try:
                meta = self.get(d.name)
            except (OSError, ValueError) as exc:
                self.load_errors.append((d.name, str(exc)))
                continue
            if target_id is None or meta.get("target_id") == target_id:
                out.append(meta)
        return sorted(out, key=lambda x: x.get("created", 0), reverse=True)

    def get(self, bid: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", bid):
            raise ValueError("bad backup id")
        meta = read_json(self.dir / bid / "meta.json")
        fields = ("target_path", "target_id", "target_label", "reason")
        if (not isinstance(meta, dict) or meta.get("id") != bid
                or any(not isinstance(meta.get(k), str) or not meta[k] for k in fields)
                or type(meta.get("existed")) is not bool):
            raise ValueError("invalid backup manifest")
        validate_timestamp(meta.get("created"))
        path = Path(meta["target_path"])
        if not path.is_absolute() or path.suffix.lower() != ".json":
            raise ValueError("backup target must be an absolute JSON path")
        digest = meta.get("sha256")
        if meta["existed"] and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("invalid backup checksum")
        if not meta["existed"] and (digest is not None or (self.dir / bid / "ClientAppSettings.json").exists()):
            raise ValueError("backup contents conflict with manifest")
        return meta

    def restore(self, bid: str, pre_backup: bool = True) -> str:
        meta = self.get(bid)
        path = Path(meta["target_path"])
        with operation_lock(path):
            return self._restore(bid, meta, path, pre_backup)

    def _restore(self, bid, meta, path, pre_backup):
        if pre_backup:
            self.create(Target(meta["target_id"], meta["target_label"], path,
                               meta.get("target_kind", "custom")), f"before restoring backup {bid}")
        if meta["existed"]:
            src = self.dir / bid / "ClientAppSettings.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
            try:
                shutil.copy2(src, tmp)
                if sha256(tmp) != meta["sha256"]:
                    raise OSError("backup checksum mismatch; current file preserved")
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
            if sha256(path) != meta["sha256"]:
                raise OSError("restored file doesn't match the backup")
            return f"Restored {path} from backup {bid}. Verified (SHA-256 matches)."
        if path.exists():
            path.unlink()
        if path.exists():
            raise OSError("couldn't remove the file")
        return f"Backup {bid} was taken when no file existed, so {path} was removed. Verified."


# --- Apply ------------------------------------------------------------------------
@dataclass
class ApplyResult:
    ok: bool
    message: str
    target: Target
    backup_id: str | None = None
    written: dict = field(default_factory=dict)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    verified: bool = False
    rolled_back: bool = False


def apply_profile(profile: Profile, target: Target, backups: BackupStore, mode: str = "merge",
                  writer=write_json_atomic) -> ApplyResult:
    try:
        with operation_lock(target.path):
            return _apply_locked(profile, target, backups, mode, writer)
    except OSError as exc:
        return ApplyResult(False, str(exc), target)


def _apply_locked(profile, target, backups, mode, writer):
    """merge: set this profile's flags, keep the file's other flags.
    replace: the file afterwards holds only this profile's flags."""
    if mode not in ("merge", "replace"):
        raise ValueError("mode must be 'merge' or 'replace'")
    if profile.unsupported:
        return ApplyResult(False, "Asset replacement imports are stored only.", target)
    if not target.path.is_absolute() or target.path.suffix.lower() != ".json":
        return ApplyResult(False, "Choose an absolute JSON target path.", target)
    desired = profile.effective_flags()
    skipped = [(r.flag, r.status()[1]) for r in profile.rules if r.status()[0] in (IGNORED, INVALID)]
    if not desired and mode == "merge":
        return ApplyResult(False, "Nothing to apply: no enabled flags that Roblox honors.", target,
                           skipped=skipped)
    state = read_target(target)
    if state.error and mode == "merge":
        return ApplyResult(False, f"The target file isn't valid ({state.error}). Nothing was changed. "
                                  "Use Replace mode to overwrite it; a backup is made first.",
                           target, skipped=skipped)
    final = dict(state.flags) if mode == "merge" else {}
    final.update(desired)

    try:
        bid = backups.create(target, f"before applying '{profile.name}' ({mode})")
    except OSError as e:
        return ApplyResult(False, f"Couldn't make a backup, so nothing was changed: {e}", target,
                           skipped=skipped)

    if read_target(target) != state:
        return ApplyResult(False, "Target changed during backup. Review it and retry.", target, bid)
    err = None
    try:
        writer(target.path, final)
        after = read_target(target)
        verified = after.error is None and after.exists and after.flags == final
        if not verified:
            err = after.error or "the file on disk doesn't match what was written"
    except (OSError, ValueError, MemoryError) as e:
        verified, err = False, str(e) or type(e).__name__

    if verified:
        return ApplyResult(True, f"Wrote {len(desired)} flag(s) to {target.path} and read the file "
                                 "back to verify it.", target, bid, desired, skipped, True)
    try:
        backups.restore(bid, pre_backup=False)
        return ApplyResult(False, f"Write failed ({err}). The previous file was restored from "
                                  f"backup {bid}.", target, bid, {}, skipped, False, True)
    except (OSError, ValueError) as e2:
        return ApplyResult(False, f"Write failed ({err}) and restoring backup {bid} also failed "
                                  f"({e2}). Restore it from the Backups tab.", target, bid, {}, skipped)


def clear_target(target: Target, backups: BackupStore) -> ApplyResult:
    return apply_profile(Profile(name="Clear all flags", rules=[]), target, backups, mode="replace")


# --- Reports, preview, diagnostics -------------------------------------------------
def profile_report(profile: Profile, target: Target | None, state: TargetState | None) -> list[tuple[str, str]]:
    """Separate status lines, one per state, so nothing claims more than was shown."""
    lines: list[tuple[str, str]] = []
    if profile.unsupported:
        lines.append(("fail", "Live asset replacement: unsupported. Data kept unchanged; nothing to apply."))
        return lines
    sts = [r.status()[0] for r in profile.rules]
    n_active, n_ign, n_inv = sts.count(ACTIVE), sts.count(IGNORED), sts.count(INVALID)
    conflicts = find_conflicts(profile.rules)
    if n_inv or conflicts:
        lines.append(("warn", f"Configuration: {n_inv} invalid rule(s), {len(conflicts)} conflict/warning(s)."))
    else:
        lines.append(("ok", "Configuration: valid."))
    if profile.source:
        lines.append(("info", f"Imported from: {profile.source.get('kind')} (original data kept)."))
    lvl = "ok" if n_active and not n_ign else ("warn" if n_ign else "info")
    lines.append((lvl, f"Honored by Roblox: {n_active} of {len(profile.rules)} rule(s)"
                       + (f"; {n_ign} ignored (not on the allowlist)." if n_ign else ".")))
    if target is None:
        lines.append(("info", "Target: none found."))
    elif state is not None:
        if state.error:
            lines.append(("fail", f"Target file unreadable: {state.error}"))
        else:
            have, total = profile_presence(profile, state)
            if total == 0:
                lines.append(("info", f"In {target.label}: nothing to compare."))
            elif have == total:
                lines.append(("ok", f"In {target.label}: all {total} flag(s) present on disk."))
            else:
                lines.append(("warn", f"In {target.label}: {have} of {total} flag(s) present on disk."))
    lines.append(("info", "In-game effect: not verified. Firetier can't see inside Roblox. "
                          "Flags load when Roblox starts."))
    return lines


def preview_params(flags: dict) -> dict:
    f = {k: normalize_value(k, v) for k, v in flags.items()
         if k in ALLOWLIST and value_error(k, v) is None}
    level = None
    if f.get("DFFlagTextureQualityOverrideEnabled") == "True" and "DFIntTextureQualityOverride" in f:
        level = max(0, min(3, int(f["DFIntTextureQualityOverride"])))
    downscale = {None: 1, 3: 1, 2: 2, 1: 4, 0: 8}[level]
    q = f.get("DFIntDebugFRMQualityLevelOverride")
    return {
        "texture_level": level,
        "texture_downscale": downscale,
        "sky_gray": f.get("FFlagDebugSkyGray") == "True",
        "grass": f.get("FIntFRMMaxGrassDistance") != "0",
        "flat_lighting": f.get("DFFlagDebugPauseVoxelizer") == "True",
        "quality_level": int(q) if q is not None else None,
    }


def running_processes() -> set[str]:
    if sys.platform != "win32":
        return set()
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             errors="replace", check=True, timeout=4,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"Windows process check unavailable: {exc}") from exc
    names = set()
    for line in out.splitlines():
        if line.startswith('"'):
            names.add(line.split('","', 1)[0].strip('"').lower())
    return names


@dataclass
class Check:
    status: str  # ok | warn | fail | info
    name: str
    detail: str
    fix: str = ""


def _writable(path: Path) -> bool:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    return os.access(p, os.W_OK)


def player_session_checks(log_dir: Path) -> list[Check]:
    """Read bounded startup excerpts. Only expose known flag counts and a backend name."""
    logs = sorted((p for p in log_dir.glob("*_Player_*.log") if "CrashHandler" not in p.name),
                  key=lambda p: p.name.split("_Player_")[0].split("_")[-1], reverse=True)
    for path in logs[:6]:
        try:
            with path.open("rb") as stream:
                startup = stream.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
        except OSError:
            continue
        marker = '[FLog::Output] LoadClientSettingsFromLocal:'
        if marker not in startup:
            continue
        excerpt = startup.rsplit(marker, 1)[1].lstrip().removeprefix('"')
        if not excerpt.startswith("{"):
            continue
        # Player may truncate the printed JSON. Count only consecutive, complete flag rows.
        observed = {}
        for line in excerpt.splitlines()[1:]:
            pair = re.fullmatch(r'\s*"([A-Za-z0-9_]+)"\s*:\s*"(True|False|[+-]?\d+)"\s*,?\s*', line)
            if pair:
                key, value = pair.groups()
                if key in ALLOWLIST:
                    observed[key] = normalize_value(key, value)
            elif not re.match(r'\s*"[^"]+"\s*:', line):
                break
        denied = set(re.findall(r'\[FLog::FlagFetchingStarterModule\] Denied local configuration for: (\w+)', startup))
        checks = [Check("info", "Player session", path.name,
                        "Historical startup evidence. Restart through your usual launcher after applying a preset.")]
        for preset in builtin_presets():
            flags = preset.effective_flags()
            matches = sum(observed.get(k) == v and k not in denied for k, v in flags.items())
            rejected = sorted(flags.keys() & denied)
            detail = f"{matches}/{len(flags)} preset values seen in this settings load."
            if rejected:
                detail += " Player denied: " + ", ".join(rejected)
            checks.append(Check("warn" if rejected else "info", preset.name, detail))
        backends = re.findall(r'\[FLog::Graphics\] Loaded \d+ shaders from pack (d3d11|vulkan|glsl|gl3|opengl)(?:_\w+)?\b', startup, re.I)
        checks.append(Check("info", "Player renderer", backends[-1] if backends else "No recognized shader backend in the startup excerpt."))
        vram = re.findall(r'\[FLog::Graphics\] Video memory size: (\d+)', startup)
        if vram:
            mb = int(vram[-1]) // (1024 * 1024)
            renderer = backends[-1].lower() if backends else ""
            detail = f"Roblox budgeted {mb} MB of video memory" + (f" on {renderer}." if renderer else ".")
            if mb < VRAM_WARN_MB:
                fix = ("Apply Renderer: Direct3D 11 (No Textures already uses it) and restart Roblox."
                       if renderer == "vulkan" else "Try another renderer preset and restart Roblox.")
                checks.append(Check("warn", "Player video memory",
                                    detail + " That is far too little: textures get evicted and reloaded all the "
                                    "time, which shows as flickering or blurry textures and stutter. Long stalls "
                                    "can also show up as ping spikes in Roblox's stats.", fix))
            else:
                checks.append(Check("info", "Player video memory", detail))
        return checks
    return [Check("info", "Player session", "No readable settings-load excerpt in the six most recent Player logs.")]


def run_diagnostics(home: Path, store: ProfileStore, lad: Path | None = None,
                    tk_version: str | None = None) -> list[Check]:
    """Read-only checks. Nothing in the Roblox or bootstrapper folders is written."""
    c: list[Check] = []
    c.append(Check("ok", "Python", f"{sys.version.split()[0]}" + (f", Tk {tk_version}" if tk_version else "")))
    if _writable(home):
        c.append(Check("ok", "Firetier data folder", str(home)))
    else:
        c.append(Check("fail", "Firetier data folder", f"{home} is not writable.",
                       "Set FIRETIER_HOME to a folder you can write to."))

    lad = Path(lad) if lad else localappdata()
    targets = detect_targets(lad)
    c.extend(player_session_checks(lad / "Roblox" / "logs"))
    rob = _player_versions(lad / "Roblox" / "Versions")
    if rob:
        c.append(Check("ok", "Roblox installed", f"{len(rob)} player version(s). Newest: {rob[0]}"))
    elif any(t.kind == "bootstrapper" for t in targets):
        c.append(Check("info", "Roblox installed", "Only bootstrapper-managed Roblox found."))
    else:
        c.append(Check("fail", "Roblox installed", "No RobloxPlayerBeta.exe found.",
                       "Install Roblox (or Fishstrap/Bloxstrap) and start it once."))
    boots = [t for t in targets if t.kind == "bootstrapper"]
    if boots:
        c.append(Check("info", "Bootstrapper", ", ".join(t.label.split()[0] for t in boots)
                       + " found. It owns the FastFlags file; Firetier edits its copy.",
                       "Start Roblox through the bootstrapper so the flags get copied in."))

    for t in targets:
        st = read_target(t)
        name = f"Target: {t.label}"
        if not _writable(t.path):
            c.append(Check("fail", name, f"{t.path} is not writable.",
                           "Clear the read-only attribute or run Firetier as the same user."))
            continue
        if not st.exists:
            c.append(Check("info", name, "No flags file yet. Applying a profile creates it."))
            continue
        if st.error:
            c.append(Check("fail", name, f"Unreadable: {st.error}",
                           "Restore a backup or apply a profile in Replace mode."))
            continue
        s = analyze_flags(st.flags)
        rules = [Rule(k, normalize_value(k, v)) for k, v in st.flags.items()]
        conf = find_conflicts(rules)
        if s.ignored or s.invalid:
            c.append(Check("warn", name,
                           f"{s.total} flags: {len(s.active)} honored, {len(s.ignored)} ignored by Roblox, "
                           f"{len(s.invalid)} invalid.",
                           "Use 'Load target as profile', then Apply in Replace mode to keep only the "
                           "honored flags (a backup is made first)."))
        else:
            c.append(Check("ok", name, f"{s.total} flags, all honored by Roblox."))
        for msg in conf:
            c.append(Check("warn", f"{t.label}: conflict", msg, "Remove the extra flag."))

    for prof in store.list():
        sts = [r.status()[0] for r in prof.rules]
        if prof.unsupported:
            c.append(Check("info", f"Profile: {prof.name}", "Asset replacement import, stored only."))
        elif INVALID in sts:
            c.append(Check("warn", f"Profile: {prof.name}", f"{sts.count(INVALID)} invalid rule(s).",
                           "Open the profile and fix or remove the red rules."))
    for p, err in store.load_errors:
        c.append(Check("fail", "Profile file", f"{p.name}: {err}",
                       "Fix the file by hand or delete it from the profiles folder."))

    backup_index = BackupStore(home)
    backup_index.list()
    for bid, err in backup_index.load_errors:
        c.append(Check("fail", "Backup manifest", f"{bid}: {err}", "Inspect the backup folder before restoring."))
    try:
        procs = running_processes()
    except OSError as exc:
        procs = set()
        c.append(Check("warn", "Running processes", str(exc)))
    running = [n for n in ("robloxplayerbeta.exe", "fishstrap.exe", "bloxstrap.exe", "voidstrap.exe")
               if n in procs]
    if running:
        c.append(Check("warn", "Running now", ", ".join(running),
                       "Flags load at launch. Close Roblox and start it again after applying."))
    c.append(Check("info", "Allowlist", f"Embedded copy of Roblox's list from {ALLOWLIST_POSTED}, "
                                        f"checked {ALLOWLIST_CHECKED}. Roblox can change it at any time "
                                        "and Firetier can't detect that.", ALLOWLIST_SOURCE))
    return c

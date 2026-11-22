"""Optional Roblox account link: shows the player's name and avatar in Firetier.

Detection is offline: Roblox's own Player logs contain `userid:<N>` once a game was joined.
Connecting is opt-in and is the only network traffic Firetier makes: one public lookup on
users.roblox.com and one avatar headshot from thumbnails.roblox.com, over HTTPS with certificate
verification on. No cookies, passwords or tokens are read, sent or stored.
"""
from __future__ import annotations

import base64
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USERS_API = "https://users.roblox.com"
THUMBS_API = "https://thumbnails.roblox.com"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
USERID_RE = re.compile(r"^\d{1,19}$")
LOG_USERID_RE = re.compile(r"\buserid:(\d{1,19})\b")
MAX_AVATAR = 1024 * 1024
MAX_LOG_READ = 8 * 1024 * 1024
PNG_SIG = b"\x89PNG\r\n\x1a\n"
TIMEOUT = 8


class AccountError(Exception):
    """Roblox couldn't be reached or answered badly."""


class InputError(AccountError):
    """The username or id typed in isn't valid; nothing was sent."""


def detect_user_id(log_dir: Path) -> str | None:
    """The user id from the newest Roblox Player log that joined a game, read locally."""
    try:
        logs = sorted((p for p in Path(log_dir).glob("*_Player_*.log") if "CrashHandler" not in p.name),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for path in logs[:10]:
        try:
            with open(path, "rb") as f:
                text = f.read(MAX_LOG_READ).decode("utf-8", "replace")
        except OSError:
            continue
        found = LOG_USERID_RE.findall(text)
        if found and found[-1] != "0":
            return found[-1]
    return None


def _open(req: urllib.request.Request, limit: int) -> bytes:
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise AccountError("Roblox is rate-limiting lookups. Try again in a minute.") from e
        if e.code == 404:
            raise AccountError("No Roblox account has that user ID.") from e
        raise AccountError(f"Roblox answered with HTTP {e.code}.") from e
    except ssl.SSLError as e:
        raise AccountError("Couldn't verify Roblox's HTTPS certificate, so nothing was sent. "
                           "Check the system clock and any proxy or antivirus HTTPS scanning.") from e
    except (urllib.error.URLError, OSError) as e:
        raise AccountError("Couldn't reach Roblox. Check your internet connection.") from e
    if len(data) > limit:
        raise AccountError("Roblox sent an unexpectedly large response.")
    return data


def http_json(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", "User-Agent": "Firetier",
        **({"Content-Type": "application/json"} if data else {})})
    try:
        return json.loads(_open(req, 256 * 1024))
    except ValueError as e:
        raise AccountError("Roblox sent a reply Firetier couldn't read.") from e


def http_bytes(url: str) -> bytes:
    return _open(urllib.request.Request(url, headers={"User-Agent": "Firetier"}), MAX_AVATAR)


def _trusted_image_url(url) -> bool:
    try:
        u = urllib.parse.urlsplit(str(url))
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host == "rbxcdn.com" or host.endswith(".rbxcdn.com"))


def lookup(query: str, get_json=http_json, get_bytes=http_bytes, sleep=time.sleep) -> dict:
    """Resolve a username or numeric user id to {user_id, name, display_name, ...} plus avatar PNG bytes."""
    q = str(query or "").strip().lstrip("@")
    if USERID_RE.match(q) and q != "0":
        u = get_json("GET", f"{USERS_API}/v1/users/{q}")
    elif USERNAME_RE.match(q):
        r = get_json("POST", f"{USERS_API}/v1/usernames/users", {"usernames": [q], "excludeBannedUsers": False})
        data = r.get("data") if isinstance(r, dict) else None
        if not data:
            raise AccountError(f"No Roblox account is called “{q}”.")
        u = data[0]
    else:
        raise InputError("Enter a Roblox username (3–20 letters, digits or _) or a numeric user ID.")
    if not isinstance(u, dict) or not str(u.get("id", "")).isdigit() or not u.get("name"):
        raise AccountError("Roblox sent a reply Firetier couldn't read.")
    uid = str(u["id"])
    out = {"user_id": uid, "name": str(u["name"])[:40],
           "display_name": str(u.get("displayName") or u["name"])[:40],
           "verified_badge": bool(u.get("hasVerifiedBadge")), "avatar": None}
    url = None
    for attempt in range(3):
        try:
            t = get_json("GET", f"{THUMBS_API}/v1/users/avatar-headshot?userIds={uid}"
                         "&size=150x150&format=Png&isCircular=false")
        except AccountError:
            break
        item = (t.get("data") or [{}])[0] if isinstance(t, dict) else {}
        if item.get("state") == "Completed" and _trusted_image_url(item.get("imageUrl")):
            url = item["imageUrl"]
            break
        if item.get("state") != "Pending":
            break
        sleep(1.0 + attempt)
    if url:
        try:
            png = get_bytes(url)
            if png.startswith(PNG_SIG):
                out["avatar"] = png
        except AccountError:
            pass
    return out


class AccountStore:
    def __init__(self, home: Path):
        self.dir = Path(home) / "account"
        self.meta = self.dir / "account.json"
        self.avatar = self.dir / "avatar.png"

    def load(self) -> dict | None:
        try:
            a = json.loads(self.meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(a, dict) or not USERID_RE.match(str(a.get("user_id", ""))):
            return None
        a = {k: a.get(k) for k in ("user_id", "name", "display_name", "verified_badge", "connected_at")}
        try:
            png = self.avatar.read_bytes()
            a["avatar_data"] = "data:image/png;base64," + base64.b64encode(png).decode() if png.startswith(PNG_SIG) else None
        except OSError:
            a["avatar_data"] = None
        return a

    def save(self, info: dict) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        png = info.get("avatar")
        if png:
            tmp = self.avatar.with_suffix(".tmp")
            tmp.write_bytes(png)
            tmp.replace(self.avatar)
        else:
            self.avatar.unlink(missing_ok=True)
        meta = {k: info[k] for k in ("user_id", "name", "display_name", "verified_badge")}
        meta["connected_at"] = time.time()
        tmp = self.meta.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tmp.replace(self.meta)
        return self.load()

    def clear(self) -> None:
        for p in (self.meta, self.avatar):
            p.unlink(missing_ok=True)

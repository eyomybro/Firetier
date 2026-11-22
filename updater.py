"""Self-update from a GitHub repo's latest release.

A release is installable when it has a version tag (v1.2.3) and two assets, both written by
packaging/make_release.py:
  Firetier.exe          the new single-file build
  firetier-update.json  {"version": "1.2.3", "sha256": "<64 hex>", "size": <bytes>}
Requests are HTTPS with certificate verification (redirects must stay HTTPS), carry no cookies or
tokens, and identify themselves only as "Firetier-updater". The download must match the manifest's
size and SHA-256 and be a Windows executable before it replaces anything. The previous exe is kept
next to the new one as Firetier.old.exe.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
DEFAULT_REPO = "eyomybro/Firetier"  # where official builds are published; Settings can change or clear it
EXE_ASSET = "Firetier.exe"
MANIFEST_ASSET = "firetier-update.json"
USER_AGENT = "Firetier-updater"
TIMEOUT = 20
MAX_JSON = 1 << 20
MIN_EXE, MAX_EXE = 1 << 16, 256 << 20
CHUNK = 1 << 16
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
VERSION_RE = re.compile(r"^v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(Exception):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def parse_version(s) -> tuple[int, int, int] | None:
    m = VERSION_RE.match(s.strip()) if isinstance(s, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


def fmt_version(v: tuple[int, int, int]) -> str:
    return ".".join(map(str, v))


def valid_repo(s) -> bool:
    return isinstance(s, str) and bool(REPO_RE.match(s)) and s.split("/")[1] not in (".", "..")


def running_exe() -> Path | None:
    """The Firetier.exe this server was started from. The launcher sets FIRETIER_EXE; from source it's unset."""
    p = os.environ.get("FIRETIER_EXE")
    if p and p.lower().endswith(".exe") and Path(p).is_file():
        return Path(p)
    return None


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise UpdateError("GitHub redirected the request away from HTTPS, so Firetier refused it.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url: str, accept: str):
    """Open an HTTPS URL with verified TLS. Returns the response; the caller closes it."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise UpdateError("Firetier only downloads updates over HTTPS.")
    opener = urllib.request.build_opener(_HttpsOnlyRedirects(),
                                         urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        return opener.open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        e.close()
        if e.code in (403, 429):
            raise UpdateError("GitHub is rate-limiting update checks from this network. Try again in an hour.", e.code) from e
        raise UpdateError(f"GitHub answered {e.code} {e.reason}.", e.code) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError):
            raise UpdateError("Couldn't verify GitHub's certificate, so nothing was downloaded.") from e
        raise UpdateError(f"Couldn't reach GitHub ({e.reason}). Check your connection.") from e
    except ssl.SSLError as e:
        raise UpdateError("Couldn't verify GitHub's certificate, so nothing was downloaded.") from e
    except OSError as e:
        raise UpdateError(f"Couldn't reach GitHub ({e}). Check your connection.") from e


def read_json(url: str, accept: str = "application/json", opener=open_url):
    try:
        with opener(url, accept) as r:
            data = r.read(MAX_JSON + 1)
    except OSError as e:
        raise UpdateError(f"The connection to GitHub dropped ({e}).") from e
    if len(data) > MAX_JSON:
        raise UpdateError("GitHub's answer was too large to be an update manifest.")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise UpdateError("GitHub sent something that isn't JSON.") from e


def check(repo: str, current: str, get_json=read_json) -> dict:
    """Look up the latest release. Returns what the UI shows; exe_url/sha256/size only when an update is available."""
    if not valid_repo(repo):
        raise UpdateError("Set the GitHub repo as owner/name, for example yourname/Firetier.")
    cur = parse_version(current)
    if cur is None:
        raise UpdateError(f"This build's version {current!r} isn't comparable.")
    try:
        rel = get_json(f"{API}/repos/{repo}/releases/latest", "application/vnd.github+json")
    except UpdateError as e:
        if e.status == 404:
            raise UpdateError(f"{repo} has no published release yet, or the repo is private or doesn't exist.", 404) from e
        raise
    if not isinstance(rel, dict):
        raise UpdateError("GitHub's release info wasn't in the expected shape.")
    tag = rel.get("tag_name")
    ver = parse_version(tag)
    if ver is None:
        raise UpdateError(f"The latest release's tag {tag!r} isn't a version like v1.2.3.")
    page = str(rel.get("html_url") or "")
    if not page.lower().startswith(f"https://github.com/{repo.lower()}/releases/"):
        page = f"https://github.com/{repo}/releases/latest"
    info = {"repo": repo, "current": fmt_version(cur), "latest": fmt_version(ver), "available": ver > cur,
            "notes": str(rel.get("body") or "")[:4000], "published": str(rel.get("published_at") or ""), "page": page}
    if not info["available"]:
        return info

    assets = {a.get("name"): a for a in rel.get("assets") or [] if isinstance(a, dict)}
    exe, man = assets.get(EXE_ASSET), assets.get(MANIFEST_ASSET)
    if not exe or not man:
        raise UpdateError(f"Release {tag} has no {EXE_ASSET} and {MANIFEST_ASSET}, so Firetier can't verify it. "
                          "Get it from the release page instead.")
    prefix = f"https://github.com/{repo.lower()}/releases/download/"
    urls = [str(a.get("browser_download_url") or "") for a in (exe, man)]
    if not all(u.lower().startswith(prefix) for u in urls):
        raise UpdateError(f"Release {tag}'s files don't download from {repo}'s own release page; refusing them.")
    m = get_json(urls[1], "application/octet-stream")
    if not isinstance(m, dict):
        raise UpdateError(f"{MANIFEST_ASSET} in {tag} isn't a JSON object.")
    if parse_version(m.get("version")) != ver:
        raise UpdateError(f"{MANIFEST_ASSET} says version {m.get('version')!r} but the release is {tag}.")
    sha = str(m.get("sha256") or "").lower()
    size = m.get("size")
    if not SHA_RE.match(sha):
        raise UpdateError(f"{MANIFEST_ASSET} in {tag} has no valid SHA-256.")
    if type(size) is not int or not MIN_EXE <= size <= MAX_EXE:
        raise UpdateError(f"{MANIFEST_ASSET} in {tag} has an implausible size.")
    if isinstance(exe.get("size"), int) and exe["size"] != size:
        raise UpdateError(f"{EXE_ASSET} in {tag} is {exe['size']} bytes but the manifest says {size}.")
    info.update(exe_url=urls[0], sha256=sha, size=size)
    return info


def download(info: dict, dest: Path, opener=open_url, progress=None) -> Path:
    """Stream the release exe to dest, checking size, SHA-256 and the PE header. Nothing is left behind on failure."""
    part = dest.with_name(dest.name + ".part")
    size, h, n = info["size"], hashlib.sha256(), 0
    try:
        with opener(info["exe_url"], "application/octet-stream") as r, open(part, "wb") as f:
            while True:
                try:
                    chunk = r.read(CHUNK)
                except OSError as e:
                    raise UpdateError(f"The download stopped ({e}). Try again.") from e
                if not chunk:
                    break
                n += len(chunk)
                if n > size:
                    raise UpdateError("The download is bigger than the release says, so Firetier refused it.")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(n, size)
        if n != size:
            raise UpdateError(f"The download ended early ({n} of {size} bytes). Try again.")
        if h.hexdigest() != info["sha256"]:
            raise UpdateError("The download doesn't match the release's SHA-256, so it was thrown away.")
        with open(part, "rb") as f:
            if f.read(2) != b"MZ":
                raise UpdateError("The download isn't a Windows program, so it was thrown away.")
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return dest


def install(staged: Path, exe: Path) -> Path:
    """Swap the verified build in. The launcher has already exited, so exe isn't locked. Returns the kept old exe."""
    old = exe.with_name(exe.stem + ".old" + exe.suffix)
    old.unlink(missing_ok=True)
    os.replace(exe, old)
    try:
        os.replace(staged, exe)
    except OSError:
        os.replace(old, exe)
        raise
    return old


def relaunch(exe: Path, popen=subprocess.Popen):
    """Start the new exe. It waits for this process to exit before it takes Firetier's lock."""
    env = dict(os.environ, FIRETIER_WAIT_PID=str(os.getpid()))
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    popen([str(exe)], env=env, cwd=str(exe.parent), creationflags=flags, close_fds=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_exit(pid: int, timeout: float = 30.0) -> None:
    if sys.platform != "win32" or pid <= 0:
        return
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.OpenProcess.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not h:
        return  # already gone
    try:
        k.WaitForSingleObject(h, int(timeout * 1000))
    finally:
        k.CloseHandle(h)

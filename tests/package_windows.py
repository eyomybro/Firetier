"""Smoke-test the extracted Windows build from a different working directory.

Checks, in order:
1. The zip is intact and the bundled runtime imports everything both front ends need.
2. The bundled runtime serves the web UI headless: every file index.html, the CSS and the JS refer to
   loads, and the API answers with the token and refuses without it.
3. `Firetier.bat` opens the web UI in an Edge app window served by the bundled pythonw.exe.
4. `Firetier.bat classic` still opens the Tk window, and the portable Tk workflow still passes.
"""
import argparse
import ctypes
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import psutil
import win32con
import win32gui
import win32process
import win32ui
from PIL import Image


def _windows(match):
    found = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and match(win32gui.GetWindowText(hwnd)):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                found.append((hwnd, psutil.Process(pid)))
            except psutil.NoSuchProcess:
                pass
        return True
    win32gui.EnumWindows(visit, None)
    return found


def _print_window(hwnd):
    """Capture one window's own pixels, even when covered and without taking focus.
    Chromium composites on the GPU, so a plain BitBlt (ImageGrab window=) comes back black;
    PW_RENDERFULLCONTENT (2) asks the compositor for the real content."""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    wdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(wdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    try:
        assert ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2), "PrintWindow failed"
        return Image.frombuffer("RGB", (w, h), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem.DeleteDC()
        src.DeleteDC()
        win32gui.ReleaseDC(hwnd, wdc)


def _get(url, token=None):
    req = urllib.request.Request(url, headers={"X-Firetier-Token": token} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _headless(runtime, unpacked, env, root):
    proc = subprocess.Popen([str(runtime / "python.exe"), str(unpacked / "server.py"), "--no-browser", "--home", str(root / "home-web")],
                            env=env, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = proc.stdout.readline().strip()
        assert url.startswith("http://127.0.0.1:"), f"server printed {url!r}; stderr: {proc.stderr.read() if proc.poll() is not None else ''}"
        base, token = url.split("/#t=")
        status, html = _get(base + "/")
        assert status == 200 and b"<title>Firetier</title>" in html, status
        refs = set(re.findall(r'(?:src|href)="((?:css|js|assets)/[^"#]+)', html.decode()))
        for sub in ("css", "js"):
            for f in (unpacked / "web" / sub).iterdir():
                text = f.read_text(encoding="utf-8")
                refs |= {("css/" if sub == "css" and not r.startswith(("assets/", "../")) else "") + r.replace("../", "")
                         for r in re.findall(r"url\(['\"]?([^'\")]+\.(?:svg|png|jpg|ico|woff2))", text)}
                refs |= set(re.findall(r"(assets/[\w./-]+\.(?:svg|png|jpg|ico))", text))
        missing = [r for r in sorted(refs) if _get(f"{base}/{r}")[0] != 200]
        assert not missing, f"web files missing from the build: {missing}"
        assert _get(base + "/api/ping")[0] == 403, "API answered without the token"
        status, body = _get(base + "/api/state", token)
        assert status == 200, status
        state = json.loads(body)
        assert state["app"]["name"] == "Firetier" and state["presets"], state["app"]
        return {"web_files_loaded": len(refs), "api_state_presets": len(state["presets"]), "api_without_token": 403}
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def _web_window(unpacked, env, root, evidence):
    webview = str(root / "home" / "webview").casefold()
    pythonw = str(unpacked / "runtime" / "pythonw.exe").casefold()
    started = time.perf_counter()
    subprocess.run([env["COMSPEC"], "/d", "/c", "call", str(unpacked / "Firetier.bat")], env=env, cwd=root, check=True, timeout=5)

    def ours(p):
        try:
            return p.name().lower() == "msedge.exe" and any(webview in a.casefold() for a in p.cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    found = []
    while time.perf_counter() - started < 20 and not found:
        found = [(h, p) for h, p in _windows(lambda t: t.endswith("· Firetier")) if ours(p)]
        time.sleep(.1)
    servers = [p for p in psutil.process_iter(["exe", "cmdline"])
               if (p.info["exe"] or "").casefold() == pythonw and any(a.endswith("server.py") for a in p.info["cmdline"] or [])]
    try:
        assert found, "the Edge app window with the Firetier UI did not appear"
        assert servers, "no bundled pythonw.exe running server.py"
        hwnd, _ = found[0]
        ms = round((time.perf_counter() - started) * 1000)
        title = win32gui.GetWindowText(hwnd)
        time.sleep(2.5)
        shot = _print_window(hwnd)
        lo, hi = shot.convert("L").getextrema()
        assert hi - lo > 40, f"the web window rendered blank (luma {lo}..{hi})"
        shot.save(evidence / "packaged-web-window.png")
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return {"web_window_title": title, "launcher_to_web_window_ms": ms}
    finally:
        # Only what this launch started: Edge processes on this build's private profile, and its server.
        time.sleep(2)
        for p in [p for p in psutil.process_iter() if ours(p)] + servers:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(servers, timeout=5)


def _classic(unpacked, runtime, env, root, evidence):
    expected = str(runtime / "pythonw.exe").casefold()
    times = []
    for turn in range(3):
        started = time.perf_counter()
        subprocess.run([env["COMSPEC"], "/d", "/c", "call", str(unpacked / "Firetier.bat"), "classic"], env=env, cwd=root, check=True, timeout=5)
        found = []
        while time.perf_counter() - started < 8 and not found:
            found = [(h, p) for h, p in _windows(lambda t: t.startswith("Firetier ")) if os.path.samefile(p.exe(), expected)]
            time.sleep(.04)
        assert found, "the classic Tk window did not appear"
        hwnd, process = found[0]
        try:
            assert "FastFlag manager" in win32gui.GetWindowText(hwnd)
            times.append(round((time.perf_counter() - started) * 1000))
            if turn == 0:
                time.sleep(.35)
                _print_window(hwnd).save(evidence / "packaged-window.png")
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            assert process.wait(timeout=5) == 0
        finally:
            if process.is_running():
                process.kill()
                process.wait(timeout=3)
        settings = json.loads((root / "home/settings.json").read_text())
        assert settings["last_profile"] == "preset-rivals-notex"
    return times


def smoke(archive, evidence):
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # window rects in physical pixels, matching the screen grab
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        unpacked = root / "Firetier Portable"
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            names = set(z.namelist())
            z.extractall(unpacked)
        for need in ("server.py", "firetier.py", "engine.py", "Firetier.bat", "web/index.html", "web/js/app.js", "web/assets/icons.svg"):
            assert need in names, f"{need} missing from the zip"
        env = os.environ.copy()
        env.update(FIRETIER_HOME=str(root / "home"), FIRETIER_LOCALAPPDATA=str(root / "empty"),
                   PATH=str(Path(os.environ["SystemRoot"]) / "System32"))
        for key in ("PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"):
            env.pop(key, None)
        runtime = unpacked / "runtime"
        preflight = subprocess.run([str(runtime / "python.exe"), "-c",
                                    "import sys,tkinter,engine,ctypes,hashlib,server,http.server,secrets;print(sys.path);print(tkinter.TkVersion)"],
                                   env=env, cwd=root, check=True, capture_output=True, text=True)
        result = {"zip_crc": "passed", "bundled_python_paths": preflight.stdout.strip()}
        result.update(_headless(runtime, unpacked, env, root))
        result.update(_web_window(unpacked, env, root, evidence))
        result["classic_launcher_to_window_ms"] = _classic(unpacked, runtime, env, root, evidence)
        env["TCL_LIBRARY"] = str(runtime / "tcl/tcl8.6")
        env["TK_LIBRARY"] = str(runtime / "tcl/tk8.6")
        for stage in ("save", "restart"):
            subprocess.run([str(runtime / "python.exe"), str(Path(__file__).with_name("portable_workflow.py")), stage], env=env, cwd=root, check=True, timeout=15)
        result["portable_workflow"] = "saved edit, rendered preview, restarted, exported and reset preferences"
        return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("archive", type=Path)
    p.add_argument("evidence", type=Path)
    args = p.parse_args()
    # This test opens and closes real windows; don't do that on top of a game someone is playing.
    if any(proc.info["name"] == "RobloxPlayerBeta.exe" for proc in psutil.process_iter(["name"])):
        raise SystemExit("Roblox is running; close it before running the windowed package test.")
    args.evidence.mkdir(parents=True, exist_ok=True)
    result = smoke(args.archive.resolve(), args.evidence.resolve())
    (args.evidence / "package-test.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))

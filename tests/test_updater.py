"""Updater tests. The network and process launches are replaced with fakes; nothing leaves the machine."""
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import engine as E  # noqa: E402
import server as S  # noqa: E402
import updater as U  # noqa: E402
from test_engine import make_install  # noqa: E402

REPO = "someone/Firetier"
DL = f"https://github.com/{REPO}/releases/download/v9.0.0/"
EXE = b"MZ" + bytes(range(256)) * 400  # > MIN_EXE
SHA = hashlib.sha256(EXE).hexdigest()


def release(tag="v9.0.0", assets=True, exe_size=len(EXE), exe_url=DL + "Firetier.exe"):
    rel = {"tag_name": tag, "body": "Faster apply.", "published_at": "2026-11-22T10:00:00Z",
           "html_url": f"https://github.com/{REPO}/releases/tag/{tag}"}
    if assets:
        rel["assets"] = [{"name": "Firetier.exe", "size": exe_size, "browser_download_url": exe_url},
                         {"name": "firetier-update.json", "size": 90, "browser_download_url": DL + "firetier-update.json"}]
    return rel


def fake_json(rel, manifest=None):
    manifest = manifest if manifest is not None else {"version": "9.0.0", "sha256": SHA, "size": len(EXE)}
    calls = []

    def get(url, accept):
        calls.append(url)
        if url == f"{U.API}/repos/{REPO}/releases/latest":
            if isinstance(rel, Exception):
                raise rel
            return rel
        if url == DL + "firetier-update.json":
            return manifest
        raise AssertionError("unexpected URL " + url)
    get.calls = calls
    return get


def opener_for(data):
    return lambda url, accept: io.BytesIO(data)


def info(**kw):
    d = {"exe_url": DL + "Firetier.exe", "sha256": SHA, "size": len(EXE), "latest": "9.0.0", "current": E.APP_VERSION}
    d.update(kw)
    return d


class VersionTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(U.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(U.parse_version("0.10.0"), (0, 10, 0))
        for bad in ("1.2", "v1.2.3-beta", "latest", "", None, 3):
            self.assertIsNone(U.parse_version(bad), bad)
        self.assertGreater(U.parse_version("0.10.0"), U.parse_version("0.9.9"))

    def test_repo(self):
        self.assertTrue(U.valid_repo("eyomybro/Firetier"))
        self.assertTrue(U.valid_repo(U.DEFAULT_REPO))
        for bad in ("Firetier", "a/b/c", "/x", "a/..", "-a/b", "a b/c", "https://github.com/a/b", "", None):
            self.assertFalse(U.valid_repo(bad), bad)

    def test_app_version_is_comparable(self):
        self.assertIsNotNone(U.parse_version(E.APP_VERSION))


class CheckTest(unittest.TestCase):
    def test_available(self):
        r = U.check(REPO, "0.2.0", get_json=fake_json(release()))
        self.assertTrue(r["available"])
        self.assertEqual((r["latest"], r["current"], r["sha256"], r["size"]), ("9.0.0", "0.2.0", SHA, len(EXE)))
        self.assertEqual(r["exe_url"], DL + "Firetier.exe")
        self.assertEqual(r["notes"], "Faster apply.")

    def test_up_to_date_skips_manifest(self):
        g = fake_json(release(tag="v0.2.0"))
        r = U.check(REPO, "0.2.0", get_json=g)
        self.assertFalse(r["available"])
        self.assertNotIn("exe_url", r)
        self.assertEqual(len(g.calls), 1)

    def test_older_release_is_not_an_update(self):
        self.assertFalse(U.check(REPO, "1.0.0", get_json=fake_json(release(tag="v0.9.9")))["available"])

    def test_no_release(self):
        with self.assertRaisesRegex(U.UpdateError, "no published release"):
            U.check(REPO, "0.2.0", get_json=fake_json(U.UpdateError("404", 404)))

    def test_missing_assets(self):
        with self.assertRaisesRegex(U.UpdateError, "can't verify"):
            U.check(REPO, "0.2.0", get_json=fake_json(release(assets=False)))

    def test_download_from_elsewhere_refused(self):
        with self.assertRaisesRegex(U.UpdateError, "refusing"):
            U.check(REPO, "0.2.0", get_json=fake_json(release(exe_url="https://evil.example/Firetier.exe")))
        with self.assertRaisesRegex(U.UpdateError, "refusing"):
            U.check(REPO, "0.2.0", get_json=fake_json(release(exe_url="https://github.com/other/repo/releases/download/v9.0.0/Firetier.exe")))

    def test_bad_manifests(self):
        cases = [({"version": "9.0.1", "sha256": SHA, "size": len(EXE)}, "says version"),
                 ({"version": "9.0.0", "sha256": "abc", "size": len(EXE)}, "SHA-256"),
                 ({"version": "9.0.0", "sha256": SHA, "size": 10}, "implausible"),
                 ({"version": "9.0.0", "sha256": SHA, "size": "big"}, "implausible"),
                 (["not", "a", "dict"], "JSON object")]
        for man, msg in cases:
            with self.subTest(msg=msg), self.assertRaisesRegex(U.UpdateError, msg):
                U.check(REPO, "0.2.0", get_json=fake_json(release(), man))

    def test_asset_size_must_match_manifest(self):
        with self.assertRaisesRegex(U.UpdateError, "manifest says"):
            U.check(REPO, "0.2.0", get_json=fake_json(release(exe_size=len(EXE) + 1)))

    def test_bad_tag_and_page(self):
        with self.assertRaisesRegex(U.UpdateError, "isn't a version"):
            U.check(REPO, "0.2.0", get_json=fake_json(release(tag="nightly")))
        rel = release(tag="v0.1.0")
        rel["html_url"] = "https://evil.example/"
        self.assertEqual(U.check(REPO, "0.2.0", get_json=fake_json(rel))["page"], f"https://github.com/{REPO}/releases/latest")

    def test_only_https(self):
        with self.assertRaisesRegex(U.UpdateError, "HTTPS"):
            U.open_url("http://github.com/x", "*/*")

    def test_read_json_limits(self):
        with self.assertRaisesRegex(U.UpdateError, "too large"):
            U.read_json("https://x", opener=opener_for(b" " * (U.MAX_JSON + 1)))
        with self.assertRaisesRegex(U.UpdateError, "isn't JSON"):
            U.read_json("https://x", opener=opener_for(b"<html>"))
        self.assertEqual(U.read_json("https://x", opener=opener_for(b'{"a": 1}')), {"a": 1})


class DownloadInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.dest = self.d / "Firetier.update.exe"

    def tearDown(self):
        self.tmp.cleanup()

    def left(self):
        return sorted(p.name for p in self.d.iterdir())

    def test_ok_with_progress(self):
        seen = []
        U.download(info(), self.dest, opener=opener_for(EXE), progress=lambda a, b: seen.append((a, b)))
        self.assertEqual(self.dest.read_bytes(), EXE)
        self.assertEqual(seen[-1], (len(EXE), len(EXE)))
        self.assertEqual(self.left(), ["Firetier.update.exe"])

    def test_rejections_leave_nothing(self):
        bad_hash = bytearray(EXE)
        bad_hash[-1] ^= 1
        not_pe = b"ZM" + EXE[2:]
        cases = [(bytes(bad_hash), info(), "SHA-256"),
                 (EXE + b"x", info(), "bigger"),
                 (EXE[:-5], info(), "ended early"),
                 (not_pe, info(sha256=hashlib.sha256(not_pe).hexdigest()), "Windows program")]
        for data, inf, msg in cases:
            with self.subTest(msg=msg):
                with self.assertRaisesRegex(U.UpdateError, msg):
                    U.download(inf, self.dest, opener=opener_for(data))
                self.assertEqual(self.left(), [])

    def test_install_swaps_and_keeps_old(self):
        exe = self.d / "Firetier.exe"
        exe.write_bytes(b"old")
        self.dest.write_bytes(b"new")
        old = U.install(self.dest, exe)
        self.assertEqual((exe.read_bytes(), old.read_bytes(), old.name), (b"new", b"old", "Firetier.old.exe"))
        self.assertFalse(self.dest.exists())
        # A second update replaces the kept old build.
        self.dest.write_bytes(b"newer")
        U.install(self.dest, exe)
        self.assertEqual((exe.read_bytes(), old.read_bytes()), (b"newer", b"new"))

    def test_install_rolls_back(self):
        exe = self.d / "Firetier.exe"
        exe.write_bytes(b"old")
        missing = self.d / "nothing.exe"  # staged file vanished: the second replace fails
        with self.assertRaises(OSError):
            U.install(missing, exe)
        self.assertEqual(exe.read_bytes(), b"old")
        self.assertFalse((self.d / "Firetier.old.exe").exists())

    def test_relaunch(self):
        got = {}
        exe = self.d / "Firetier.exe"
        U.relaunch(exe, popen=lambda args, **kw: got.update(args=args, **kw))
        self.assertEqual(got["args"], [str(exe)])
        self.assertEqual(got["env"]["FIRETIER_WAIT_PID"], str(os.getpid()))
        self.assertEqual(got["cwd"], str(self.d))
        self.assertEqual(got["stdin"], subprocess.DEVNULL)
        if sys.platform == "win32":
            self.assertEqual(got["creationflags"], 0x208)

    def test_wait_for_exit_returns_for_finished_process(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        U.wait_for_exit(p.pid, timeout=2)  # must not hang

    def test_running_exe(self):
        exe = self.d / "Firetier.exe"
        exe.write_bytes(b"MZ")
        with mock.patch.dict(os.environ, {"FIRETIER_EXE": str(exe)}):
            self.assertEqual(U.running_exe(), exe)
        with mock.patch.dict(os.environ, {"FIRETIER_EXE": str(self.d / "gone.exe")}):
            self.assertIsNone(U.running_exe())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FIRETIER_EXE", None)
            self.assertIsNone(U.running_exe())


class ServerUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.d = d
        make_install(d / "lad")
        (d / "home").mkdir()
        self.api = S.Api(d / "home", d / "lad")
        self.api.update_check_fn = lambda repo, cur: U.check(repo, cur, get_json=fake_json(release()))
        self.exits = []
        self.api.exit_fn = lambda: self.exits.append(1)
        self.exe = d / "app" / "Firetier.exe"
        self.exe.parent.mkdir()
        self.exe.write_bytes(b"MZ old build")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_repo_and_prefs(self):
        self.assertEqual(self.api.update_get()["repo"], U.DEFAULT_REPO)
        self.assertTrue(self.api.update_get()["auto"])
        for bad in ({"update_repo": "not a repo"}, {"update_repo": 5}, {"update_auto": "yes"}):
            with self.assertRaises(S.ApiError):
                self.api.set_prefs(bad)
        self.api.set_prefs({"update_repo": "  " + REPO + " ", "update_auto": False})
        u = self.api.update_get()
        self.assertEqual((u["repo"], u["auto"]), (REPO, False))
        self.api.set_prefs({"update_repo": ""})
        with self.assertRaisesRegex(S.ApiError, "repo first"):
            self.api.update_check({})

    def test_check_records_result(self):
        self.api.set_prefs({"update_repo": REPO})
        u = self.api.update_check({})
        self.assertTrue(u["result"]["available"])
        self.assertNotIn("exe_url", u["result"])
        self.assertIsNotNone(u["checked"])
        # The state the page loads carries it too.
        self.assertTrue(self.api.state()["update"]["result"]["available"])

    def test_changing_repo_clears_result(self):
        self.api.set_prefs({"update_repo": REPO})
        self.api.update_check({})
        self.api.set_prefs({"update_repo": "other/Firetier"})
        self.assertIsNone(self.api.update_get()["result"])

    def test_check_failure_is_502(self):
        self.api.set_prefs({"update_repo": REPO})
        self.api.update_check_fn = lambda repo, cur: (_ for _ in ()).throw(U.UpdateError("rate-limited", 403))
        with self.assertRaises(S.ApiError) as cm:
            self.api.update_check({"quiet": True})
        self.assertEqual(cm.exception.status, 502)

    def test_install_needs_check_and_exe(self):
        with self.assertRaisesRegex(S.ApiError, "Check for updates first"):
            self.api.update_install({})
        self.api.set_prefs({"update_repo": REPO})
        self.api.update_check({})
        self.api.exe = None
        with self.assertRaisesRegex(S.ApiError, "source files"):
            self.api.update_install({})

    def ready(self):
        self.api.set_prefs({"update_repo": REPO})
        self.api.update_check({})
        self.api.exe = self.exe
        self.api.update_download_fn = lambda inf, dest, progress=None: U.download(inf, dest, opener=opener_for(EXE), progress=progress)
        self.launched = []
        self.api.update_relaunch_fn = lambda exe: self.launched.append(exe)

    def test_full_install(self):
        self.ready()
        with mock.patch.object(threading, "Timer") as timer:
            r = self.api.update_install({})
        self.assertEqual(r, {"ok": True, "restarting": True, "version": "9.0.0"})
        self.assertEqual(self.exe.read_bytes(), EXE)
        self.assertEqual((self.exe.parent / "Firetier.old.exe").read_bytes(), b"MZ old build")
        self.assertEqual(self.launched, [self.exe])
        timer.assert_called_once_with(1.5, self.api.exit_fn)
        timer.return_value.start.assert_called_once()
        u = self.api.update_get()
        self.assertFalse(u["busy"])
        self.assertIsNone(u["progress"])

    def test_bad_download_keeps_current_build(self):
        self.ready()
        self.api.update_download_fn = lambda inf, dest, progress=None: U.download(inf, dest, opener=opener_for(EXE[:-1]))
        with self.assertRaises(S.ApiError) as cm:
            self.api.update_install({})
        self.assertEqual(cm.exception.status, 502)
        self.assertEqual(self.exe.read_bytes(), b"MZ old build")
        self.assertEqual(sorted(p.name for p in self.exe.parent.iterdir()), ["Firetier.exe"])
        self.assertEqual(self.launched, [])
        self.assertFalse(self.api.update_get()["busy"])

    def test_relaunch_failure_puts_old_build_back(self):
        self.ready()

        def boom(exe):
            raise OSError("blocked")
        self.api.update_relaunch_fn = boom
        with mock.patch.object(threading, "Timer") as timer, self.assertRaisesRegex(S.ApiError, "put back"):
            self.api.update_install({})
        timer.assert_not_called()
        self.assertEqual(self.exe.read_bytes(), b"MZ old build")
        self.assertFalse((self.exe.parent / "Firetier.old.exe").exists())

    def test_second_install_while_busy_is_409(self):
        self.ready()
        self.api.update_lock.acquire()
        try:
            with self.assertRaises(S.ApiError) as cm:
                self.api.update_install({})
            self.assertEqual(cm.exception.status, 409)
        finally:
            self.api.update_lock.release()

    def test_release_page_opens_only_after_check(self):
        page = f"https://github.com/{REPO}/releases/tag/v9.0.0"
        with self.assertRaises(S.ApiError):
            self.api.open_url({"url": page})
        self.api.set_prefs({"update_repo": REPO})
        self.api.update_check({})
        with mock.patch.object(os, "startfile", create=True) as sf:
            self.api.open_url({"url": page})
            sf.assert_called_once_with(page)
            with self.assertRaises(S.ApiError):
                self.api.open_url({"url": "https://evil.example/"})


if __name__ == "__main__":
    unittest.main()

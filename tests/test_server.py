"""API smoke tests for server.py: a real ThreadingHTTPServer on 127.0.0.1 over a temp install."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import engine as E  # noqa: E402
import server as S  # noqa: E402
from test_engine import make_install  # noqa: E402

TOKEN = "test-token"


class BacklogTest(unittest.TestCase):
    def test_burst_of_connections_is_queued_not_refused(self):
        # Nothing accepts here, as when the accept loop lags under load. A first page load opens
        # several connections at once; with socketserver's default backlog of 5 Windows refuses the rest.
        srv = S.UIServer(("127.0.0.1", 0), S.make_handler(None, TOKEN, [0], [0.0]))
        socks = []
        try:
            for _ in range(24):
                s = socket.socket()
                s.settimeout(3)
                socks.append(s)
                s.connect(srv.server_address)
        finally:
            for s in socks:
                s.close()
            srv.server_close()


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.lad, self.home = d / "lad", d / "home"
        make_install(self.lad)
        self.home.mkdir()
        self.api = S.Api(self.home, self.lad)
        port_ref, beat = [0], [0.0]
        self.httpd = S.UIServer(("127.0.0.1", 0), S.make_handler(self.api, TOKEN, port_ref, beat))
        self.port = port_ref[0] = self.httpd.server_address[1]
        self.th = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.th.start()
        self.fish = self.lad / "Fishstrap" / "Modifications" / "ClientSettings" / "ClientAppSettings.json"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, method, path, body=None, token=TOKEN, host=None, origin=None, raw=False):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if token is not None:
            h["X-Firetier-Token"] = token
        if origin:
            h["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        payload = r.read()
        c.close()
        if raw:
            return r, payload
        return r.status, json.loads(payload) if payload[:1] in (b"{", b"[") else payload

    def ok(self, method, path, body=None):
        st, d = self.req(method, path, body)
        self.assertEqual(st, 200, d)
        return d

    # --- security -----------------------------------------------------------------
    def test_token_host_and_origin_checks(self):
        self.assertEqual(self.req("GET", "/api/state", token=None)[0], 403)
        self.assertEqual(self.req("GET", "/api/state", token="wrong")[0], 403)
        self.assertEqual(self.req("GET", "/api/state", host="evil.example:80")[0], 421)
        self.assertEqual(self.req("POST", "/api/prefs", {"density": "compact"}, origin="http://evil.example")[0], 403)
        self.assertEqual(self.req("GET", "/api/ping")[0], 200)

    def test_static_files_and_traversal(self):
        r, body = self.req("GET", "/css/tokens.css", raw=True)
        self.assertEqual(r.status, 200)
        self.assertIn("text/css", r.getheader("Content-Type"))
        self.assertIn(b"--ac:", body)
        for bad in ("/../engine.py", "/%2e%2e/engine.py", "/css/../../server.py", "/assets/../../tests/test_server.py"):
            self.assertEqual(self.req("GET", bad, raw=True)[0].status, 404, bad)

    def test_index_has_csp(self):
        r, body = self.req("GET", "/", raw=True)
        self.assertEqual(r.status, 200)
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertNotIn(b"<script>", body, "inline scripts are blocked by the CSP")

    # --- state + profiles ---------------------------------------------------------
    def test_state(self):
        s = self.ok("GET", "/api/state")
        self.assertEqual(s["target_id"], "fishstrap")
        self.assertEqual({t["id"] for t in s["targets"]}, {"fishstrap", "roblox-version-aaaa"})
        self.assertEqual(len(s["presets"]), len(E.builtin_presets()))
        self.assertEqual(len(s["allowlist"]), len(E.ALLOWLIST))
        self.assertIn("rivals", [g["id"] for g in s["games"]])
        self.assertEqual(s["app"]["version"], E.APP_VERSION)

    def test_profile_detail_has_preview(self):
        d = self.ok("GET", "/api/profile?id=preset-rivals-notex")
        self.assertTrue(d["builtin"])
        self.assertEqual(d["preview"]["texture_level"], 0)
        self.assertTrue(d["preview"]["sky_gray"])
        self.assertTrue(all("status" in r and "kind" in r for r in d["rules_list"]))
        self.assertEqual(self.req("GET", "/api/profile?id=nope")[0], 404)

    def test_builtin_is_read_only(self):
        d = self.ok("GET", "/api/profile?id=preset-rivals-notex")
        st, err = self.req("POST", "/api/profile/save", {"profile": {"id": d["id"], "name": "x", "rules": []}})
        self.assertEqual(st, 400)
        self.assertIn("read-only", err["error"])
        self.assertEqual(self.req("POST", "/api/profile/delete", {"id": d["id"]})[0], 400)

    def test_profile_lifecycle(self):
        p = self.ok("POST", "/api/profile/new", {"name": "Mine", "from": "preset-rivals-fps"})
        self.assertFalse(p["builtin"])
        src = E.Profile.from_dict(dict(self.api.store.get(p["id"]).to_dict()))
        body = src.to_dict()
        body["rules"] = [r for r in body["rules"]][:2]
        body["name"] = "Mine edited"
        saved = self.ok("POST", "/api/profile/save", {"profile": body})
        self.assertEqual(saved["name"], "Mine edited")
        self.assertEqual(saved["rules"], 2)
        r = self.ok("POST", "/api/profile/rename", {"id": p["id"], "name": "Renamed"})
        self.assertEqual(r["name"], "Renamed")
        self.assertIn(p["id"], [x["id"] for x in self.ok("GET", "/api/state")["profiles"]])
        self.assertTrue(self.ok("POST", "/api/profile/delete", {"id": p["id"]})["ok"])
        self.assertNotIn(p["id"], [x["id"] for x in self.ok("GET", "/api/state")["profiles"]])

    # --- apply / backups ----------------------------------------------------------
    def test_apply_writes_verifies_and_backs_up(self):
        self.fish.write_text(json.dumps({"FFlagUserCustom": "keep"}), encoding="utf-8")
        r = self.ok("POST", "/api/apply", {"id": "preset-rivals-notex", "mode": "merge"})
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["verified"])
        self.assertTrue(r["backup_id"])
        written = json.loads(self.fish.read_text(encoding="utf-8"))
        want = E.builtin_presets()[0].effective_flags()
        for k, v in want.items():
            self.assertEqual(str(written[k]).lower(), str(v).lower(), k)
        self.assertEqual(written["FFlagUserCustom"], "keep")
        s = self.ok("GET", "/api/state")
        self.assertEqual(s["backup_count"], 1)
        self.assertEqual(s["last_profile"], "preset-rivals-notex")
        # restore puts the original file back
        self.assertTrue(self.ok("POST", "/api/restore", {"id": r["backup_id"]})["ok"])
        self.assertEqual(json.loads(self.fish.read_text(encoding="utf-8")), {"FFlagUserCustom": "keep"})

    def test_merge_switches_exclusive_preset_settings(self):
        self.fish.write_text(json.dumps({"FFlagUnrelated": "keep"}))
        for pid in ("preset-rivals-notex", "preset-rivals-fps", "preset-balanced",
                    "preset-vulkan", "preset-opengl", "preset-d3d11", "preset-vulkan"):
            with self.subTest(preset=pid):
                result = self.api.apply({"id": pid, "mode": "merge"})
                self.assertTrue(result["verified"])
                flags = E.read_json(self.fish)
                self.assertEqual(flags["FFlagUnrelated"], "keep")
                profile = next(p for p in E.builtin_presets() if p.id == pid)
                self.assertTrue(all(flags[k] == v for k, v in profile.effective_flags().items()))
                if pid == "preset-rivals-fps":
                    self.assertIsNone(E.preview_params(flags)["texture_level"])
                if pid in ("preset-vulkan", "preset-opengl", "preset-d3d11"):
                    expected = {"preset-vulkan": "FFlagDebugGraphicsPreferVulkan",
                                "preset-opengl": "FFlagDebugGraphicsPreferOpenGL",
                                "preset-d3d11": "FFlagDebugGraphicsPreferD3D11"}[pid]
                    self.assertEqual([k for k in E.RENDERER_FLAGS if flags.get(k) == "True"], [expected])

    def test_apply_rejects_bad_mode_and_target(self):
        self.assertEqual(self.req("POST", "/api/apply", {"id": "preset-rivals-notex", "mode": "yolo"})[0], 400)
        st, err = self.req("POST", "/api/apply", {"id": "preset-rivals-notex", "target_id": "nope"})
        self.assertEqual(st, 400)
        self.assertFalse(self.fish.exists())

    # --- import / export ----------------------------------------------------------
    def test_import_flat_and_asset_profile(self):
        flat = self.ok("POST", "/api/import", {"text": json.dumps({"DFIntTextureQualityOverride": 0}), "name": "a.json"})
        self.assertTrue(flat["supported"])
        self.assertEqual(flat["profile"]["name"], "a")
        asset = self.ok("POST", "/api/import", {"text": json.dumps(
            {"replacements": [{"from": [1234567], "to": "rbxassetid://9999999"}]}), "name": "fleasion.json"})
        self.assertFalse(asset["supported"])
        self.assertTrue(asset["profile"]["unsupported"])
        self.assertGreaterEqual(asset["profile"]["source"]["asset_ids_counted"], 2)
        st, err = self.req("POST", "/api/apply", {"id": asset["profile"]["id"]})
        self.assertTrue(st != 200 or not err["ok"], "asset-replacement profiles must never be applied")
        self.assertFalse(self.fish.exists())
        bad = self.ok("POST", "/api/import", {"text": "{nope", "name": "x"})
        self.assertIsNone(bad["profile"])

    def test_export(self):
        e = self.ok("GET", "/api/export?id=preset-rivals-notex&kind=flat")
        self.assertTrue(e["filename"].endswith(".ClientAppSettings.json"))
        self.assertEqual(json.loads(e["content"]), E.builtin_presets()[0].effective_flags())

    # --- prefs / diagnostics ------------------------------------------------------
    def test_dropped_request_is_not_logged_as_failure(self):
        # The page reloading mid-request makes the response write raise ConnectionResetError.
        H = self.httpd.RequestHandlerClass
        real = H._send
        def drop(handler, *a, **k):
            raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
        H._send = drop
        try:
            with self.assertRaises((http.client.HTTPException, ConnectionError)):
                self.req("GET", "/api/storage")
        finally:
            H._send = real
        log = self.home / "firetier.log"
        text = log.read_text(encoding="utf-8") if log.exists() else ""
        self.assertNotIn("failed", text)
        self.assertEqual(self.req("GET", "/api/ping")[0], 200)  # still serving

    def test_prefs_validation(self):
        self.assertEqual(self.ok("POST", "/api/prefs", {"motion": "reduced", "density": "compact"})["changed"],
                         ["motion", "density"])
        self.assertEqual(self.ok("GET", "/api/state")["prefs"]["motion"], "reduced")
        for bad in ({"motion": "fast"}, {"nope": 1}, {"favorites": ["not-a-game"]}, {"custom_target": "rel.json"},
                    {"target_id": "missing"}):
            self.assertEqual(self.req("POST", "/api/prefs", bad)[0], 400, bad)
        self.assertTrue(self.ok("POST", "/api/prefs/reset", {})["ok"])
        self.assertEqual(self.ok("GET", "/api/state")["prefs"]["motion"], "full")

    def test_diagnostics_report_log_storage(self):
        d = self.ok("GET", "/api/diagnostics")
        self.assertTrue(any(c["name"] == "Roblox installed" for c in d["checks"]))
        rep = self.ok("GET", "/api/report")
        self.assertIn("In-game effect: not verified", rep["content"])
        log = self.ok("GET", "/api/log?n=50")
        self.assertTrue(any("Diagnostics" in e["msg"] for e in log["entries"]))
        st = self.ok("GET", "/api/storage")
        self.assertEqual(set(st), {"profiles", "backups", "trash", "log"})

    def test_open_url_is_allowlisted(self):
        self.assertEqual(self.req("POST", "/api/open-url", {"url": "https://example.com"})[0], 400)

    def test_wrong_content_type(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/prefs", b"{}", {"Host": f"127.0.0.1:{self.port}", "X-Firetier-Token": TOKEN,
                                                 "Content-Type": "text/plain"})
        self.assertEqual(c.getresponse().status, 415)
        c.close()


if __name__ == "__main__":
    unittest.main()

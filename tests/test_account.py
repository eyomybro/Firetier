"""Roblox account link: offline detection, lookup parsing (network mocked) and the server endpoints."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import account as A  # noqa: E402
import server as S  # noqa: E402
from test_engine import make_install  # noqa: E402

PNG = A.PNG_SIG + b"\x00" * 32
TOKEN = "acct-token"


class FakeRoblox:
    """Stands in for users.roblox.com and thumbnails.roblox.com; records every call."""

    def __init__(self, thumb_states=("Completed",), image_url="https://tr.rbxcdn.com/abc/150/150/AvatarHeadshot/Png"):
        self.calls, self.thumb_states, self.image_url = [], list(thumb_states), image_url

    def json(self, method, url, body=None):
        self.calls.append((method, url, body))
        if url.endswith("/v1/usernames/users"):
            name = body["usernames"][0]
            return {"data": [{"requestedUsername": name, "id": 1, "name": "Roblox", "displayName": "Roblox",
                              "hasVerifiedBadge": True}] if name.lower() == "roblox" else []}
        if url.startswith(A.USERS_API + "/v1/users/"):
            return {"id": 1, "name": "Roblox", "displayName": "Roblox", "hasVerifiedBadge": True}
        if "avatar-headshot" in url:
            state = self.thumb_states.pop(0) if self.thumb_states else "Completed"
            return {"data": [{"targetId": 1, "state": state, "imageUrl": self.image_url if state == "Completed" else None}]}
        raise AssertionError(url)

    def bytes(self, url):
        self.calls.append(("GET", url, None))
        return PNG


class Lookup(unittest.TestCase):
    def test_username_lookup_fetches_profile_and_headshot(self):
        f = FakeRoblox()
        out = A.lookup("@Roblox", f.json, f.bytes, sleep=lambda s: None)
        self.assertEqual((out["user_id"], out["name"], out["display_name"], out["verified_badge"]), ("1", "Roblox", "Roblox", True))
        self.assertEqual(out["avatar"], PNG)
        self.assertEqual(f.calls[0], ("POST", A.USERS_API + "/v1/usernames/users", {"usernames": ["Roblox"], "excludeBannedUsers": False}))
        self.assertTrue(all(u.startswith("https://") for _, u, _ in f.calls))

    def test_numeric_id_uses_users_endpoint(self):
        f = FakeRoblox()
        A.lookup("1", f.json, f.bytes, sleep=lambda s: None)
        self.assertEqual(f.calls[0][:2], ("GET", A.USERS_API + "/v1/users/1"))

    def test_rejects_bad_input_without_any_request(self):
        f = FakeRoblox()
        for q in ("", "ab", "x" * 21, "bad name", "0", "a/b"):
            with self.assertRaises(A.AccountError):
                A.lookup(q, f.json, f.bytes)
        self.assertEqual(f.calls, [])

    def test_unknown_username(self):
        f = FakeRoblox()
        with self.assertRaisesRegex(A.AccountError, "No Roblox account"):
            A.lookup("nobody_here", f.json, f.bytes)

    def test_pending_headshot_is_retried(self):
        f = FakeRoblox(thumb_states=("Pending", "Completed"))
        slept = []
        out = A.lookup("Roblox", f.json, f.bytes, sleep=slept.append)
        self.assertEqual(out["avatar"], PNG)
        self.assertEqual(len(slept), 1)

    def test_avatar_only_downloaded_from_roblox_cdn(self):
        for bad in ("http://tr.rbxcdn.com/x", "https://evil.example/x.png", "https://rbxcdn.com.evil.example/x"):
            f = FakeRoblox(image_url=bad)
            out = A.lookup("Roblox", f.json, f.bytes, sleep=lambda s: None)
            self.assertIsNone(out["avatar"], bad)
            self.assertFalse(any(u == bad for _, u, _ in f.calls), bad)

    def test_non_png_avatar_is_dropped(self):
        f = FakeRoblox()
        out = A.lookup("Roblox", f.json, lambda u: b"<html>", sleep=lambda s: None)
        self.assertIsNone(out["avatar"])

    def test_certificate_failure_is_reported_not_bypassed(self):
        import ssl
        import urllib.request
        orig = urllib.request.urlopen

        def boom(req, timeout=None, context=None):
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            raise ssl.SSLCertVerificationError("bad cert")
        urllib.request.urlopen = boom
        try:
            with self.assertRaisesRegex(A.AccountError, "certificate"):
                A.http_json("GET", A.USERS_API + "/v1/users/1")
        finally:
            urllib.request.urlopen = orig


class Detect(unittest.TestCase):
    def test_newest_log_with_a_join_wins(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            logs = Path(d)
            old = logs / "0.1_20260101T000000Z_Player_A_last.log"
            new = logs / "0.1_20260102T000000Z_Player_B_last.log"
            none = logs / "0.1_20260103T000000Z_Player_C_last.log"
            old.write_text("x clienttime:1, userid:111, y")
            new.write_text("a userid:0, b\n clienttime:2, userid:222, z")
            none.write_text("no join here")
            for i, p in enumerate((old, new, none)):
                os.utime(p, (1000 + i, 1000 + i))
            self.assertEqual(A.detect_user_id(logs), "222")
            self.assertIsNone(A.detect_user_id(logs / "missing"))


class Endpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        lad, self.home = d / "lad", d / "home"
        make_install(lad)
        self.home.mkdir()
        self.api = S.Api(self.home, lad)
        self.fake = FakeRoblox()
        self.api.lookup = lambda q: A.lookup(q, self.fake.json, self.fake.bytes, sleep=lambda s: None)
        port_ref = [0]
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.make_handler(self.api, TOKEN, port_ref, [0.0]))
        self.port = port_ref[0] = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", "X-Firetier-Token": TOKEN}
        data = json.dumps(body).encode() if body is not None else None
        if data:
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        out = r.status, json.loads(r.read())
        c.close()
        return out

    def test_connect_then_disconnect(self):
        st, body = self.req("GET", "/api/account")
        self.assertEqual(st, 200)
        self.assertIsNone(body["account"])
        st, body = self.req("POST", "/api/account/connect", {"query": "Roblox"})
        self.assertEqual(st, 200, body)
        self.assertEqual(body["account"]["name"], "Roblox")
        self.assertTrue(body["account"]["avatar_data"].startswith("data:image/png;base64,"))
        st, body = self.req("GET", "/api/account")
        self.assertEqual(body["account"]["user_id"], "1")
        saved = json.loads((self.home / "account" / "account.json").read_text())
        self.assertNotIn("avatar", saved)
        self.assertEqual(self.req("POST", "/api/account/disconnect", {})[0], 200)
        self.assertIsNone(self.req("GET", "/api/account")[1]["account"])
        self.assertFalse((self.home / "account" / "avatar.png").exists())

    def test_bad_query_is_a_400_with_a_message(self):
        st, body = self.req("POST", "/api/account/connect", {"query": "no spaces allowed"})
        self.assertEqual(st, 400)
        self.assertIn("username", body["error"])

    def test_account_routes_need_the_token(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", "/api/account", headers={"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(c.getresponse().status, 403)
        c.close()

    def test_slow_lookup_does_not_block_state(self):
        gate = threading.Event()
        self.api.lookup = lambda q: (gate.wait(5), A.lookup(q, self.fake.json, self.fake.bytes, sleep=lambda s: None))[1]
        t = threading.Thread(target=self.req, args=("POST", "/api/account/connect", {"query": "Roblox"}))
        t.start()
        try:
            st, _ = self.req("GET", "/api/state")
            self.assertEqual(st, 200)
        finally:
            gate.set()
            t.join(10)


if __name__ == "__main__":
    unittest.main()

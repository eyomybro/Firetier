import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine as E  # noqa: E402
import firetier as F  # noqa: E402


def make_install(lad: Path, fishstrap=True, roblox=True):
    if roblox:
        v = lad / "Roblox" / "Versions" / "version-aaaa"
        v.mkdir(parents=True)
        (v / "RobloxPlayerBeta.exe").write_bytes(b"")
    if fishstrap:
        v = lad / "Fishstrap" / "Versions" / "version-bbbb"
        v.mkdir(parents=True)
        (v / "RobloxPlayerBeta.exe").write_bytes(b"")
        (lad / "Fishstrap" / "Modifications" / "ClientSettings").mkdir(parents=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.lad = self.dir / "lad"
        self.home = self.dir / "home"
        self.store = E.ProfileStore(self.home)
        self.backups = E.BackupStore(self.home)

    def tearDown(self):
        self.tmp.cleanup()


class Validation(unittest.TestCase):
    def test_allowlist_has_18_flags(self):
        self.assertEqual(len(E.ALLOWLIST), 18)
        self.assertTrue(set(E.FLAG_HELP) >= set(E.ALLOWLIST))

    def test_statuses(self):
        self.assertEqual(E.Rule("DFIntTextureQualityOverride", "0").status()[0], E.ACTIVE)
        self.assertEqual(E.Rule("DFIntTaskSchedulerTargetFps", "240").status()[0], E.IGNORED)
        self.assertEqual(E.Rule("DFIntTextureQualityOverride", "low").status()[0], E.INVALID)
        self.assertEqual(E.Rule("FFlagDebugSkyGray", "yes").status()[0], E.INVALID)
        self.assertEqual(E.Rule("NotAFlag", "1").status()[0], E.INVALID)
        self.assertEqual(E.Rule("FFlagDebugSkyGray", "True", enabled=False).status()[0], E.DISABLED)

    def test_normalize(self):
        self.assertEqual(E.normalize_value("FFlagDebugSkyGray", True), "True")
        self.assertEqual(E.normalize_value("FFlagDebugSkyGray", "true"), "True")
        self.assertEqual(E.normalize_value("DFIntTextureQualityOverride", 0), "0")
        self.assertEqual(E.normalize_value("DFIntTextureQualityOverride", " +007 "), "7")

    def test_conflicts(self):
        rules = [E.Rule("FFlagDebugGraphicsPreferVulkan", "True"), E.Rule("FFlagDebugGraphicsPreferD3D11", "True"),
                 E.Rule("DFIntTextureQualityOverride", "0")]
        c = " ".join(E.find_conflicts(rules))
        self.assertIn("More than one graphics API", c)
        self.assertIn("DFFlagTextureQualityOverrideEnabled", c)
        self.assertEqual(E.find_conflicts(E.builtin_presets()[0].rules), [])

    def test_presets_are_fully_honored(self):
        for p in E.builtin_presets():
            self.assertEqual(len(p.effective_flags()), len(p.rules), p.name)
            self.assertEqual(E.find_conflicts(p.rules), [], p.name)

    def test_effective_flags_drop_ignored_invalid_disabled(self):
        p = E.Profile("x", [E.Rule("FFlagDebugSkyGray", "True"), E.Rule("FFlagDisablePostFx", "True"),
                            E.Rule("DFIntTextureQualityOverride", "abc"),
                            E.Rule("FIntFRMMaxGrassDistance", "0", enabled=False)])
        self.assertEqual(p.effective_flags(), {"FFlagDebugSkyGray": "True"})


class Imports(unittest.TestCase):
    def test_flat_json_keeps_original(self):
        data = {"DFIntTextureQualityOverride": 0, "FFlagDisablePostFx": True}
        res = E.import_profile_text(json.dumps(data), "mine")
        self.assertTrue(res.supported)
        self.assertEqual(res.profile.source["original"], data)
        self.assertEqual(len(res.profile.rules), 2)
        self.assertIn("1 honored by Roblox, 1 ignored", " ".join(res.messages))

    def test_firetier_roundtrip(self):
        p = E.builtin_presets()[0].clone("rt")
        res = E.import_profile_text(json.dumps(p.to_dict()))
        self.assertEqual(res.kind, "firetier")
        self.assertEqual(res.profile.effective_flags(), p.effective_flags())
        self.assertNotEqual(res.profile.id, p.id)

    def test_asset_replacement_is_stored_not_applied(self):
        data = {"replacements": [{"from": [1234567, 7654321], "to": "rbxassetid://9999999"}]}
        res = E.import_profile_text(json.dumps(data))
        self.assertFalse(res.supported)
        self.assertEqual(res.kind, "asset-replacement")
        self.assertTrue(res.profile.unsupported)
        self.assertEqual(res.profile.source["original"], data)
        self.assertEqual(res.profile.effective_flags(), {})

    def test_bad_json(self):
        res = E.import_profile_text("{not json")
        self.assertIsNone(res.profile)
        self.assertEqual(res.kind, "invalid-json")
        self.assertEqual(E.import_profile_text("[1, 2]").kind, "unknown")


class Targets(Base):
    def test_detects_fishstrap_and_roblox(self):
        make_install(self.lad)
        ts = E.detect_targets(self.lad)
        self.assertEqual([t.kind for t in ts], ["bootstrapper", "roblox"])
        self.assertEqual(ts[0].path, self.lad / "Fishstrap" / "Modifications" / "ClientSettings" / "ClientAppSettings.json")
        self.assertIn("Fishstrap is installed", ts[1].notes[0])

    def test_roblox_only(self):
        make_install(self.lad, fishstrap=False)
        ts = E.detect_targets(self.lad)
        self.assertEqual(len(ts), 1)
        self.assertEqual(ts[0].path.parent.name, "ClientSettings")
        self.assertEqual(ts[0].path.parent.parent.name, "version-aaaa")

    def test_nothing_installed(self):
        self.assertEqual(E.detect_targets(self.lad), [])


class Apply(Base):
    def target(self, content=None):
        make_install(self.lad)
        t = E.detect_targets(self.lad)[0]
        if content is not None:
            t.path.write_text(content, encoding="utf-8")
        return t

    def test_merge_keeps_other_flags_and_verifies(self):
        t = self.target(json.dumps({"FFlagSomethingElse": "True", "DFIntTextureQualityOverride": "3"}))
        p = E.builtin_presets()[0]
        res = E.apply_profile(p, t, self.backups, "merge")
        self.assertTrue(res.ok, res.message)
        self.assertTrue(res.verified)
        on_disk = json.loads(t.path.read_text())
        self.assertEqual(on_disk["FFlagSomethingElse"], "True")
        self.assertEqual(on_disk["DFIntTextureQualityOverride"], "0")
        self.assertEqual(E.profile_presence(p, E.read_target(t)), (len(p.rules), len(p.rules)))
        self.assertEqual(len(self.backups.list(t.id)), 1)

    def test_replace_writes_only_honored_flags(self):
        t = self.target(json.dumps({"FFlagDisablePostFx": "True", "DFIntTaskSchedulerTargetFps": "999"}))
        p = E.Profile("x", [E.Rule("FFlagDebugSkyGray", "True"), E.Rule("FFlagDisablePostFx", "True")])
        res = E.apply_profile(p, t, self.backups, "replace")
        self.assertTrue(res.ok)
        self.assertEqual(json.loads(t.path.read_text()), {"FFlagDebugSkyGray": "True"})
        self.assertEqual([f for f, _ in res.skipped], ["FFlagDisablePostFx"])

    def test_creates_file_when_missing_and_backup_restores_absence(self):
        t = self.target()
        self.assertFalse(t.path.exists())
        res = E.apply_profile(E.builtin_presets()[0], t, self.backups)
        self.assertTrue(res.ok)
        self.assertTrue(t.path.exists())
        msg = self.backups.restore(res.backup_id)
        self.assertIn("removed", msg)
        self.assertFalse(t.path.exists())

    def test_failed_write_rolls_back(self):
        original = '{"FFlagDebugSkyGray": "False", "Keep": 1}'
        t = self.target(original)

        def bad_writer(path, data):
            Path(path).write_text("{garbage", encoding="utf-8")

        res = E.apply_profile(E.builtin_presets()[0], t, self.backups, writer=bad_writer)
        self.assertFalse(res.ok)
        self.assertTrue(res.rolled_back)
        self.assertEqual(t.path.read_text(encoding="utf-8"), original)

    def test_writer_exception_rolls_back(self):
        original = '{"FFlagDebugSkyGray": "False"}'
        t = self.target(original)

        def boom(path, data):
            raise PermissionError("denied")

        res = E.apply_profile(E.builtin_presets()[0], t, self.backups, writer=boom)
        self.assertFalse(res.ok)
        self.assertIn("denied", res.message)
        self.assertEqual(t.path.read_text(encoding="utf-8"), original)

    def test_corrupt_target_merge_refused(self):
        t = self.target("{broken")
        res = E.apply_profile(E.builtin_presets()[0], t, self.backups, "merge")
        self.assertFalse(res.ok)
        self.assertEqual(t.path.read_text(), "{broken")
        self.assertEqual(self.backups.list(), [])
        res = E.apply_profile(E.builtin_presets()[0], t, self.backups, "replace")
        self.assertTrue(res.ok)
        self.assertEqual(self.backups.list()[0]["existed"], True)

    def test_restore_is_byte_exact_and_backs_up_first(self):
        original = '{\n  "FFlagDebugSkyGray": "False"\n}\n'
        t = self.target(original)
        res = E.apply_profile(E.builtin_presets()[0], t, self.backups)
        self.backups.restore(res.backup_id)
        self.assertEqual(t.path.read_text(encoding="utf-8"), original)
        self.assertEqual(len(self.backups.list(t.id)), 2)

    def test_clear_target(self):
        t = self.target('{"FFlagDebugSkyGray": "True"}')
        res = E.clear_target(t, self.backups)
        self.assertTrue(res.ok)
        self.assertEqual(json.loads(t.path.read_text()), {})

    def test_empty_merge_refused(self):
        t = self.target('{"A": 1}')
        res = E.apply_profile(E.Profile("x", [E.Rule("FFlagDisablePostFx", "True")]), t, self.backups)
        self.assertFalse(res.ok)
        self.assertEqual(t.path.read_text(), '{"A": 1}')


class Store(Base):
    def test_crud(self):
        p = E.Profile("One", [E.Rule("FFlagDebugSkyGray", "True")])
        self.store.save(p)
        self.assertEqual([x.name for x in self.store.list()], ["One"])
        self.store.rename(p.id, "Two")
        d = self.store.duplicate(self.store.get(p.id))
        self.assertEqual(sorted(x.name for x in self.store.list()), ["Two", "Two (copy)"])
        trash = self.store.delete(d.id)
        self.assertTrue(trash.exists())
        self.assertEqual([x.name for x in self.store.list()], ["Two"])

    def test_builtin_is_read_only(self):
        with self.assertRaises(ValueError):
            self.store.save(E.builtin_presets()[0])

    def test_broken_profile_reported(self):
        (self.store.dir / "bad.json").write_text("{nope")
        self.assertEqual(self.store.list(), [])
        self.assertEqual(len(self.store.load_errors), 1)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.store.get("../../evil")


class Diagnostics(Base):
    def test_player_evidence_distinguishes_config_denial_and_backend(self):
        logs = self.dir / "logs"
        logs.mkdir()
        (logs / "0.748_20261122T010000Z_Player_X_last.log").write_text("Starting Player")
        (logs / "0.748_20261121T220000Z_Player_Y_last.log").write_text(
            '[FLog::Output] LoadClientSettingsFromLocal: "{\n'
            '  "FFlagDebugGraphicsPreferVulkan": "True",\n'
            '  "FFlagDebugGraphicsPreferD3D11": "False",\n'
            '  "FFlagDebugGraphicsPreferOpenGL": "False"\n}"\n'
            '[FLog::FlagFetchingStarterModule] Denied local configuration for: FFlagDebugGraphicsPreferVulkan\n'
            '[FLog::Graphics] Loaded 4028 shaders from pack d3d11 variant default\n')
        checks = {c.name: c for c in E.player_session_checks(logs)}
        self.assertIn("220000Z", checks["Player session"].detail)
        self.assertIn("2/3", checks["Renderer: Vulkan"].detail)
        self.assertEqual(checks["Renderer: Vulkan"].status, "warn")
        self.assertEqual(checks["Player renderer"].detail, "d3d11")

    def test_warns_when_vulkan_gets_a_tiny_video_memory_budget(self):
        # Real lines from a GT 1030 (2 GB) session: Vulkan sized video memory to 64 MB, D3D11 to 2 GB.
        logs = self.dir / "logs"
        logs.mkdir()
        head = '[FLog::Output] LoadClientSettingsFromLocal: "{\n  "FFlagDebugGraphicsPreferVulkan": "True"\n}"\n'
        (logs / "0.748_20261122T142836Z_Player_V_last.log").write_text(
            head + "[FLog::Graphics] Video memory size: 67108864\n"
                   "[FLog::Graphics] Loaded 3543 shaders from pack vulkan_desktop variant default\n")
        checks = {c.name: c for c in E.player_session_checks(logs)}
        self.assertEqual(checks["Player video memory"].status, "warn")
        self.assertIn("64 MB", checks["Player video memory"].detail)
        self.assertIn("Direct3D 11", checks["Player video memory"].fix)
        (logs / "0.748_20261123T000000Z_Player_D_last.log").write_text(
            head + "[FLog::Graphics] Video memory size: 2147483648\n"
                   "[FLog::Graphics] Loaded 4028 shaders from pack d3d11 variant default\n")
        checks = {c.name: c for c in E.player_session_checks(logs)}
        self.assertEqual(checks["Player video memory"].status, "info")
        self.assertIn("2048 MB", checks["Player video memory"].detail)

    def test_no_textures_preset_forces_d3d11_and_live_lighting(self):
        flags = next(p for p in E.builtin_presets() if p.id == "preset-rivals-notex").effective_flags()
        self.assertEqual([k for k in E.RENDERER_FLAGS if flags.get(k) == "True"], ["FFlagDebugGraphicsPreferD3D11"])
        self.assertEqual(flags["FFlagDebugGraphicsPreferVulkan"], "False")
        self.assertEqual(flags["DFFlagDebugPauseVoxelizer"], "False")
        self.assertEqual(flags["DFIntTextureQualityOverride"], "0")

    def test_reports_ignored_flags(self):
        make_install(self.lad)
        t = E.detect_targets(self.lad)[0]
        t.path.write_text(json.dumps({"FFlagDebugSkyGray": "True", "DFIntTaskSchedulerTargetFps": "999"}))
        checks = E.run_diagnostics(self.home, self.store, self.lad)
        tc = [c for c in checks if c.name == "Target: Fishstrap FastFlags"][0]
        self.assertEqual(tc.status, "warn")
        self.assertIn("1 honored, 1 ignored", tc.detail)

    def test_no_roblox(self):
        checks = E.run_diagnostics(self.home, self.store, self.lad)
        self.assertEqual([c for c in checks if c.name == "Roblox installed"][0].status, "fail")


class Preview(unittest.TestCase):
    def test_params(self):
        p = E.preview_params(E.builtin_presets()[0].effective_flags())
        self.assertEqual(p["texture_level"], 0)
        self.assertEqual(p["texture_downscale"], 8)
        self.assertTrue(p["sky_gray"])
        self.assertFalse(p["grass"])
        d = E.preview_params({})
        self.assertEqual(d["texture_downscale"], 1)
        self.assertIsNone(d["texture_level"])
        # Override value without the enable flag does nothing
        self.assertIsNone(E.preview_params({"DFIntTextureQualityOverride": "0"})["texture_level"])

    def test_render_size_and_difference(self):
        a = F.render_rows(E.preview_params({}), 60, 40)
        b = F.render_rows(E.preview_params(E.builtin_presets()[0].effective_flags()), 60, 40)
        self.assertEqual((len(a), len(a[0])), (40, 60))
        self.assertNotEqual(a, b)
        self.assertEqual(b[0][0], "#969696")  # grey sky


if __name__ == "__main__":
    unittest.main()

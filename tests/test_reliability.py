import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as E


class Reliability(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = E.ProfileStore(self.root)
        self.backups = E.BackupStore(self.root)
        self.target = E.Target("custom", "Custom", self.root / "ClientAppSettings.json", "custom")
        self.target.path.write_bytes(b'{"existing":1}')

    def test_corrupt_backup_never_replaces_current_file(self):
        bid = self.backups.create(self.target, "test")
        (self.backups.dir / bid / "ClientAppSettings.json").write_bytes(b"damaged")
        with self.assertRaises((ValueError, OSError)):
            self.backups.restore(bid)
        self.assertEqual(self.target.path.read_bytes(), b'{"existing":1}')

    def test_backup_index_isolates_bad_metadata(self):
        bid = self.backups.create(self.target, "good")
        for label, data in (("array", []), ("bad-id", {"id":bid}), ("partial", None)):
            directory = self.backups.dir / label
            directory.mkdir()
            if data is not None:
                E.write_json_atomic(directory / "meta.json",data)
        self.assertEqual([b["id"] for b in self.backups.list()], [bid])
        self.assertEqual(len(self.backups.load_errors), 3)

    def test_unsupported_replace_cannot_clear_target(self):
        profile = E.import_profile_text('{"replacements":[1234567]}').profile
        self.assertFalse(E.apply_profile(profile, self.target, self.backups, "replace").ok)
        self.assertEqual(self.target.path.read_bytes(), b'{"existing":1}')

    def test_bad_profile_isolated_and_original_preserved(self):
        good = E.Profile("Good")
        self.store.save(good)
        bad = self.store.dir / "bad.json"
        E.write_json_atomic(bad, dict(good.to_dict(), game=[]))
        self.assertEqual([p.name for p in self.store.list()], ["Good"])
        self.assertEqual(len(self.store.load_errors), 1)
        self.assertTrue(bad.exists())

    def test_identity_comes_from_file(self):
        profile = E.Profile("First")
        self.store.save(profile)
        self.store.rename(profile.id, "Original")
        E.write_json_atomic(self.store.dir / "copy.json", profile.to_dict())
        self.store.rename("copy","Copy")
        self.assertEqual(self.store.get(profile.id).name,"Original")
        self.assertEqual(self.store.get("copy").name,"Copy")

    def test_import_validation(self):
        p = E.builtin_presets()[0].to_dict()
        for data in (dict(p, created=None),dict(p,game=[]),dict(p,version=99),
                     dict(p,rules=[{"flag":"FFlagDebugSkyGray","value":True,"enabled":"false"}])):
            with self.subTest(field=str(data)[:80]):
                self.assertIsNone(E.import_profile_text(json.dumps(data)).profile)
        for raw in ("["*2000+"]"*2000, '{"DFIntTextureQualityOverride":'+"9"*5000+"}", '{"x":NaN}'):
            self.assertEqual(E.import_profile_text(raw).kind,"invalid-json")

    def test_large_number_is_invalid_rule(self):
        self.assertEqual(E.Rule("DFIntTextureQualityOverride","9"*5000).status()[0],E.INVALID)

    def test_saved_profiles_roundtrip_with_size_limit(self):
        profile = E.Profile("a", description="x"*500)
        with patch.object(E,"MAX_JSON_BYTES",300):
            with self.assertRaises(ValueError):
                self.store.save(profile)
        self.assertEqual(self.store.list(),[])

    def test_repeated_delete_preserves_both_versions(self):
        p = E.Profile("first")
        with patch("engine.time.strftime",return_value="same"):
            self.store.save(p)
            a = self.store.delete(p.id)
            p.name = "second"
            self.store.save(p)
            b = self.store.delete(p.id)
        self.assertNotEqual(a,b)
        self.assertEqual(E.read_json(a)["name"],"first")

    def test_atomic_write_handles_memory_error(self):
        with patch("engine.json.dump",side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                E.write_json_atomic(self.target.path,{"new":1})
        self.assertEqual(self.target.path.read_bytes(), b'{"existing":1}')
        self.assertEqual(list(self.root.glob("*.tmp")),[])

    def test_asset_identifier_and_budget(self):
        self.assertEqual(E._count_asset_ids(["broken rbxassetid://text"],[10]),0)
        self.assertEqual(E._count_asset_ids(["rbxassetid://1234567"],[10]),1)
        self.assertLessEqual(E._count_asset_ids({str(1234567+i):0 for i in range(100)},[3]),3)


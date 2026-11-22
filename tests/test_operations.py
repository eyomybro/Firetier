import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as E


class Operations(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.target = E.Target("fixture","Fixture",self.home / "ClientAppSettings.json","custom")
        self.target.path.write_bytes(b'{"original": 1}')
        self.backups = E.BackupStore(self.home)

    @unittest.skipUnless(os.name == "nt", "Windows mutex")
    def test_concurrent_apply_and_restore_preserve_target(self):
        bid = self.backups.create(self.target, "fixture")
        proc = subprocess.Popen([sys.executable, "-c",
            "import engine,sys; from pathlib import Path\nwith engine.operation_lock(Path(sys.argv[1])):\n print('locked',flush=True);sys.stdin.readline()",
            str(self.target.path)], cwd=Path(E.__file__).parent, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            self.assertEqual(proc.stdout.readline().strip(), b"locked")
            self.assertFalse(E.apply_profile(E.builtin_presets()[0],self.target,self.backups).ok)
            with self.assertRaises(OSError):
                self.backups.restore(bid)
            self.assertEqual(self.target.path.read_bytes(),b'{"original": 1}')
            proc.kill()
            proc.wait(timeout=5)
            self.assertTrue(E.apply_profile(E.builtin_presets()[0],self.target,self.backups).ok)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=5)

    def test_process_killed_at_fsync_preserves_prior_configuration(self):
        proc = subprocess.run([sys.executable,"-c",
            "import engine,sys,os;from pathlib import Path;engine.os.fsync=lambda _:os._exit(73);engine.write_json_atomic(Path(sys.argv[1]),{'new':2})",
            str(self.target.path)],cwd=Path(E.__file__).parent,timeout=8)
        self.assertEqual(proc.returncode,73)
        self.assertEqual(self.target.path.read_bytes(),b'{"original": 1}')

    def test_concurrent_external_edit_during_backup(self):
        create = self.backups.create
        def changed(*args):
            bid = create(*args)
            self.target.path.write_text('{"external": true}')
            return bid
        with patch.object(self.backups,"create",side_effect=changed):
            result = E.apply_profile(E.builtin_presets()[0],self.target,self.backups)
        self.assertFalse(result.ok)
        self.assertEqual(E.read_json(self.target.path),{"external":True})

    def test_unavailable_process_check_reported(self):
        with patch("engine.running_processes",side_effect=OSError("fixture query failed")):
            checks = E.run_diagnostics(self.home,E.ProfileStore(self.home),self.home)
        self.assertTrue(any(c.status=="warn" and "fixture query failed" in c.detail for c in checks))

    def test_historical_compatibility_fixtures(self):
        profile = E.import_profile_text('{"DFFlagHttpUseEmbeddedCaCerts": false}').profile
        self.assertEqual(profile.rules[0].status()[0],E.IGNORED)
        self.assertFalse(E.apply_profile(profile,self.target,self.backups).ok)
        archived = E.import_profile_text('{"assets":[{"asset":{"assetId":1234567}}]}').profile
        self.assertTrue(archived.unsupported)
        self.assertFalse(E.import_profile_text(json.dumps(archived.to_dict())).supported)
        for mode in ("merge", "replace"):
            self.assertFalse(E.apply_profile(archived,self.target,self.backups,mode).ok)
        self.assertEqual(self.target.path.read_bytes(),b'{"original": 1}')


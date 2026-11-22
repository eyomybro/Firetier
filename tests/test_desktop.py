import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine as E
import firetier as F


class DesktopRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.geometry("1000x700")
        self.app = None

    def open(self):
        self.app = F.App(self.root, self.home, self.home / "no-install")
        self.root.update()
        return self.app

    def test_corrupt_settings_recover_previous_and_preserve_original(self):
        backup = self.home / "settings.previous.json"
        E.write_json_atomic(backup, {"mode": "replace", "last_profile": "preset-balanced"})
        (self.home / "settings.json").write_bytes(b"{truncated")
        app = self.open()
        self.assertEqual(app.mode.get(), "replace")
        self.assertEqual(app.current.id, "preset-balanced")
        self.assertEqual(next(self.home.glob("settings.damaged-*.json")).read_bytes(),b"{truncated")

    def test_invalid_settings_types_and_defaults(self):
        E.write_json_atomic(self.home / "settings.json", {"mode": [], "last_profile":{}, "custom_target":4})
        app = self.open()
        self.assertEqual(app.mode.get(),"merge")
        self.assertEqual(app.current.id,"preset-rivals-notex")
        self.assertTrue(list(self.home.glob("settings.damaged-*.json")))

    def test_preferences_write_failure_visible(self):
        app = self.open()
        with patch("engine.write_json_atomic", side_effect=PermissionError("read-only fixture")):
            app._save_setting("mode", "replace")
        self.assertIn("read-only fixture",app.statusbar.cget("text"))
        self.assertNotEqual(E.read_json(app.settings_path).get("mode"),"replace")

    def test_cancelled_navigation_preserves_dirty_flag(self):
        app = self.open()
        p = E.Profile("draft")
        app.store.save(p)
        app.refresh_profiles(p.id)
        app.select_profile(p.id)
        app.dirty = True
        with patch("firetier.messagebox.askyesnocancel",return_value=False), patch("firetier.simpledialog.askstring",return_value=None):
            app.new_profile()
        self.assertTrue(app.dirty)

    def test_editor_field_usable_at_minimum_width(self):
        app = self.open()
        self.root.geometry("1000x700")
        self.root.update()
        self.assertGreater(app.flag_cb.winfo_width(),140)

    def test_preview_reuses_identical_render(self):
        app = self.open()
        app.nb.select(2)
        self.root.update()
        with patch("firetier.render_rows",wraps=F.render_rows) as render:
            app.refresh_preview()
            self.assertEqual(render.call_count,0)


    def test_archived_assets_have_explicit_preview_state(self):
        app = self.open()
        app.nb.select(2)
        self.root.update()
        archived = E.import_profile_text('{"assets":[1234567]}').profile
        app.store.save(archived)
        app.refresh_profiles(archived.id)
        app.select_profile(archived.id)
        self.assertIn("Stored asset", app.prev_caps[1].cget("text"))
        self.assertFalse(app.prev_labels[1].cget("image"))
        app.select_profile("preset-rivals-notex")
        self.assertTrue(app.prev_labels[1].cget("image"))

    def test_diagnostic_selection_exposes_full_detail(self):
        app = self.open()
        app.diag_checks = [E.Check("warn","Test","Full result "*70,"A suggested action")]
        app._display_diagnostics()
        app.dtree.selection_set(app.dtree.get_children()[0])
        self.root.update()
        self.assertIn("A suggested action",app.diag_detail.cget("text"))

"""Drive Firetier's actual Tk controls in two separate application processes.
Native filename and confirmation dialogs receive deterministic answers.
QA dependencies: Pillow (window captures), psutil (optional in stress probe).
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine as E
import firetier as F


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def press(app, label):
    button = next(w for w in walk(app.root) if w.winfo_class() == "TButton" and w.cget("text").replace(chr(0x2026), "...") == label)
    button.invoke()
    app.root.update()


def capture(app, path):
    from PIL import ImageGrab
    app.root.update()
    img = ImageGrab.grab(window=app.root.winfo_id())
    assert img.getextrema()[0][0] < img.getextrema()[0][1]
    img.save(path)


def drive(app, stage, work, evidence):
    failures = []
    with ExitStack() as stack:
        for name in ("askyesno", "askokcancel", "showinfo", "showwarning"):
            stack.enter_context(patch.object(F.messagebox, name, return_value=True))
        stack.enter_context(patch.object(F.messagebox, "showerror", side_effect=lambda *a, **k: failures.append(str(a))))
        stack.enter_context(patch.object(F.simpledialog, "askstring", return_value="Audit draft"))
        stack.enter_context(patch.object(F.filedialog, "askopenfilename", return_value=str(work / "import.json")))
        stack.enter_context(patch.object(F.filedialog, "asksaveasfilename", return_value=str(work / "export.json")))
        def tab(name):
            index = next(i for i in range(len(app.nb.tabs())) if app.nb.tab(i, "text") == name)
            app.nb.select(index)
            app.root.update()
        def pick(pid):
            app.ptree.selection_set(pid)
            app.root.update()
            assert app.current.id == pid
        app.root.geometry("1200x790+10+10")
        app.root.update()
        if stage == "first":
            pick("preset-rivals-fps")
            pick("preset-rivals-notex")
            tab("Status")
            assert "present on disk" in app.stext.get("1.0","end")
            press(app,"New")
            assert app.current.name == "Audit draft"
            E.write_json_atomic(work / "import.json", E.builtin_presets()[0].effective_flags())
            press(app,"Import...")
            assert app.current.source["kind"] == "fastflag-json"
            tab("Flags")
            app.flag_var.set("FFlagDebugSkyGray")
            app.value_var.set("False")
            press(app,"Add / Update")
            tab("Preview")
            assert app.prev_labels[1].cget("image")
            assert "Sky: normal" in app.prev_caps[1].cget("text")
            tab("Flags")
            app.value_var.set("True")
            press(app,"Add / Update")
            tab("Preview")
            assert "Sky: grey" in app.prev_caps[1].cget("text")
            capture(app, evidence / "preview.png")
            tab("Flags")
            press(app,"Save")
            assert not app.dirty
            app.mode.set("replace")
            press(app,"Apply to target")
            assert E.read_json(app.target.path) == app.current.effective_flags()
            (work / "id.txt").write_text(app.current.id)
        else:
            assert app.current.id == (work / "id.txt").read_text()
            assert app.mode.get() == "replace"
            assert app.current.effective_flags()["FFlagDebugSkyGray"] == "True"
            press(app,"Export...")
            assert E.read_json(work / "export.json")["rules"] == app.current.to_dict()["rules"]
            tab("Backups")
            app.btree.selection_set(app.btree.get_children()[0])
            press(app,"Restore selected")
            assert app.target.path.read_bytes() == b'{"original": 42}\r\n'
            tab("Diagnostics")
            deadline = time.monotonic() + 10
            while app.diag_pending and time.monotonic() < deadline:
                app.root.update()
                time.sleep(.01)
            assert any(c.name.startswith("Target:") for c in app.diag_checks)
            capture(app, evidence / "diagnostics.png")
            press(app,"Restore preferences")
            assert app.mode.get() == "merge" and app.current.id == "preset-rivals-notex"
            pick((work / "id.txt").read_text())
            press(app,"Delete")
            assert app.current.builtin and len(app.store.list()) == 1
            assert len(list(app.store.trash.glob("*.json"))) == 1
        assert not failures, failures
        app.on_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--stage", choices=("first", "restart"))
    args = parser.parse_args()
    work, evidence = args.work.resolve(), args.evidence.resolve()
    work.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    os.environ["FIRETIER_HOME"] = str(work / "home")
    os.environ["FIRETIER_LOCALAPPDATA"] = str(work / "installation")
    if not args.stage:
        version = Path(os.environ["FIRETIER_LOCALAPPDATA"]) / "Roblox/Versions/version-fixture"
        version.mkdir(parents=True)
        (version / "RobloxPlayerBeta.exe").touch()
        target = version / "ClientSettings/ClientAppSettings.json"
        target.parent.mkdir()
        target.write_bytes(b'{"original": 42}\r\n')
        for stage in ("first", "restart"):
            subprocess.run([sys.executable, __file__, str(work), str(evidence), "--stage", stage],
                           check=True, timeout=45)
        return
    real_app = F.App
    problems = []
    def launch(root, *a, **kw):
        app = real_app(root, *a, **kw)
        def run():
            try:
                drive(app, args.stage, work, evidence)
            except BaseException as error:
                problems.append(error)
                root.destroy()
        root.after(150, run)
        return app
    with patch.object(F,"App",side_effect=launch):
        F.main()
    if problems:
        raise problems[0]
    print(args.stage, "passed")


if __name__ == "__main__":
    main()


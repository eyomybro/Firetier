import os
import sys
import tkinter as tk
from pathlib import Path
import firetier as F
import engine as E

real_app = F.App
errors = []


def launch(root, *args):
    app = real_app(root, *args)
    def action():
        try:
            if sys.argv[1] == "save":
                F.simpledialog.askstring = lambda *args, **kwargs: "Portable test profile"
                app.new_profile()
                app.flag_var.set("FFlagDebugSkyGray")
                app.value_var.set("True")
                app.add_rule()
                assert app.save_profile()
                app.nb.select(2)
                root.update()
                assert "Sky: grey" in app.prev_caps[1].cget("text")
            else:
                assert app.current.name == "Portable test profile"
                assert app.current.effective_flags() == {"FFlagDebugSkyGray":"True"}
                destination = E.home_dir() / "exported.json"
                F.filedialog.asksaveasfilename = lambda **kwargs: str(destination)
                app.export_profile()
                assert E.read_json(destination)["name"] == app.current.name
                F.messagebox.askyesno = lambda *args, **kwargs: True
                app.restore_preferences()
                assert app.current.id == "preset-rivals-notex"
        except BaseException as error:
            errors.append(error)
        finally:
            root.destroy()
    root.after(50, action)
    return app


F.App = launch
F.main()
if errors:
    raise errors[0]


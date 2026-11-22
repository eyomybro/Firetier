"""Capture an actual failure state and the minimum-size editor on Windows."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from desktop_workflow import E, F, capture


def main(out):
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    with tempfile.TemporaryDirectory() as tmp:
        root=F.tk.Tk()
        app=F.App(root,Path(tmp),Path(tmp)/"empty")
        root.geometry("1000x700+5+5")
        root.update()
        capture(app,out/"after-flags.png")
        target=E.Target("custom","Fixture",Path(tmp)/"ClientAppSettings.json","custom")
        target.path.write_bytes(b'{"fixture": true}')
        original=target.path.read_bytes()
        bid=app.backups.create(target,"Restore verification fixture")
        (app.backups.dir/bid/"ClientAppSettings.json").write_bytes(b"damaged")
        app.nb.select(3)
        root.update()
        app.btree.selection_set(bid)
        with patch.object(F.messagebox,"askyesno",return_value=True), patch.object(F.messagebox,"showerror") as error:
            app.restore_backup()
            assert "checksum" in error.call_args.args[1]
        assert target.path.read_bytes()==original
        capture(app,out/"restore-refused.png")
        root.destroy()
    from PIL import Image, ImageChops
    with Image.open(out/"before-flags.png") as before, Image.open(out/"after-flags.png") as after:
        ImageChops.difference(before,after).save(out/"flags-difference.png")


if __name__=="__main__":
    main(Path(sys.argv[1]))


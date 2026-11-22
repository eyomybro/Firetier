"""Build the Windows portable distribution using the local official CPython/Tk install."""
import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    if os.name != "nt":
        raise RuntimeError("Build on Windows with a standard CPython installation.")
    runtime = Path(sys.base_prefix)
    version = f"{sys.version_info.major}{sys.version_info.minor}"
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(".building")
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name in ("server.py", "firetier.py", "engine.py", "account.py", "updater.py", "README.md", "Firetier.bat"):
                archive.write(ROOT / name, name)
            # The web UI. assets/generated holds the raw image-generation sources, which the app never loads.
            for path in sorted((ROOT / "web").rglob("*")):
                rel = path.relative_to(ROOT)
                if path.is_file() and "__pycache__" not in rel.parts and rel.parts[:3] != ("web", "assets", "generated"):
                    archive.write(path, rel.as_posix())
            for name in ("pythonw.exe", "python.exe", f"python{version}.dll", "python3.dll",
                         "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
                archive.write(runtime / name, "runtime/" + name)
            extensions = ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "_ctypes.pyd", "libffi-8.dll",
                          "_hashlib.pyd", "libcrypto-3.dll", "zlib1.dll", "_uuid.pyd", "select.pyd",
                          "_socket.pyd", "unicodedata.pyd", "_ssl.pyd", "libssl-3.dll")
            for name in extensions:
                archive.write(runtime / "DLLs" / name, "runtime/DLLs/" + name)
            for folder in ("Lib", "tcl/tcl8", "tcl/tcl8.6", "tcl/tk8.6"):
                for path in (runtime / folder).rglob("*"):
                    rel = path.relative_to(runtime)
                    if path.is_file() and not {"site-packages", "__pycache__", "test", "tests",
                                                "idlelib", "ensurepip", "turtledemo"} & set(rel.parts):
                        if folder != "Lib" or path.suffix == ".py":
                            archive.write(path, "runtime/" + rel.as_posix())
            archive.writestr(f"runtime/python{version}._pth", "Lib\nDLLs\n..\n")
        staging.replace(output)
    finally:
        staging.unlink(missing_ok=True)


def build_exe(archive, output):
    """Wrap the portable zip in a single Firetier.exe, compiled with the C# compiler that ships with Windows."""
    csc = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    build_id = hashlib.sha256(archive.read_bytes()).hexdigest()[:16]
    with tempfile.TemporaryDirectory() as tmp:
        version = Path(tmp) / "version.txt"
        version.write_text(build_id, encoding="ascii")
        staging = output.with_suffix(".building.exe")
        result = subprocess.run([str(csc), "/nologo", "/target:winexe", "/optimize+", "/platform:anycpu",
                                 f"/out:{staging}", f"/win32icon:{ROOT / 'web/assets/firetier.ico'}",
                                 "/reference:System.IO.Compression.dll", "/reference:System.IO.Compression.FileSystem.dll",
                                 "/reference:System.Windows.Forms.dll",
                                 f"/resource:{archive},Firetier.zip", f"/resource:{version},version.txt",
                                 str(ROOT / "packaging/launcher.cs")], capture_output=True, text=True)
        if result.returncode:
            staging.unlink(missing_ok=True)
            raise RuntimeError(f"csc failed:\n{result.stdout}{result.stderr}")
        staging.replace(output)
    return build_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, help="the portable zip, e.g. dist/Firetier-Windows.zip")
    parser.add_argument("--exe", type=Path, help="also build this single-file launcher, e.g. dist/Firetier.exe")
    args = parser.parse_args()
    build(args.output)
    if args.exe:
        print("build", build_exe(args.output, args.exe))


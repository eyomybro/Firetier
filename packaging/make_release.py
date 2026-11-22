"""Build Firetier.exe and the update manifest for a GitHub release.

    python packaging/make_release.py            builds, then writes dist/release/v<version>/
    python packaging/make_release.py --no-build reuses dist/Firetier.exe (only if it was built from this source)

Upload the files in dist/release/v<version>/ to a new GitHub release whose tag is v<version>:
  Firetier.exe and firetier-update.json are what the in-app updater installs from;
  Firetier-v<version>-Windows.zip is the download for people: it unzips to just Firetier.exe,
  which carries its own Python runtime and web UI and needs nothing else installed.
Firetier's updater refuses a release that lacks either file or whose manifest doesn't match the exe.
Bump APP_VERSION in engine.py before each release: installs only move to a higher version.
"""
import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))
import engine as E  # noqa: E402
import updater as U  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-build", action="store_true", help="reuse dist/Firetier.exe instead of building it")
    a = ap.parse_args()
    dist = ROOT / "dist"
    exe = dist / "Firetier.exe"
    if not a.no_build:
        import build_windows as B
        B.build(dist / "Firetier-Windows.zip")
        print("build", B.build_exe(dist / "Firetier-Windows.zip", exe))
    if not exe.is_file():
        sys.exit(f"{exe} doesn't exist; run without --no-build.")
    version = E.APP_VERSION
    if U.parse_version(version) is None:
        sys.exit(f"APP_VERSION {version!r} must look like 1.2.3")
    data = exe.read_bytes()
    if not U.MIN_EXE <= len(data) <= U.MAX_EXE or data[:2] != b"MZ":
        sys.exit(f"{exe} doesn't look like a Firetier build.")
    out = dist / "release" / f"v{version}"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(exe, out / U.EXE_ASSET)
    manifest = {"version": version, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    (out / U.MANIFEST_ASSET).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    zname = f"Firetier-v{version}-Windows.zip"
    # The exe is already compressed inside, so it's stored rather than deflated again.
    with zipfile.ZipFile(out / zname, "w", zipfile.ZIP_STORED) as z:
        z.write(exe, U.EXE_ASSET)
    print(f"\nRelease files in {out}:")
    print(f"  {U.EXE_ASSET}  ({len(data):,} bytes)")
    print(f"  {U.MANIFEST_ASSET}  sha256 {manifest['sha256']}")
    print(f"  {zname}  (unzips to {U.EXE_ASSET} only)")
    print(f"\nOn GitHub: Releases > Draft a new release > tag v{version} > attach all three files > Publish.")


if __name__ == "__main__":
    main()

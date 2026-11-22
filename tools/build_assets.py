"""Derive app-ready images from the generated originals in web/assets/generated/.

logo-gen-2.png -> logo-{512,256,128,64}.png (rounded-square alpha) + firetier.ico
arena-gen.png  -> arena-1280.jpg, arena-640.jpg
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "web" / "assets" / "generated"
OUT = ROOT / "web" / "assets"


def rounded_logo():
    src = Image.open(GEN / "logo-gen-2.png").convert("RGB")
    w, h = src.size
    # The generated tile sits on a white canvas; trim to the dark tile's bbox.
    px = src.load()
    xs = [x for x in range(w) if sum(px[x, h // 2]) < 200]
    ys = [y for y in range(h) if sum(px[w // 2, y]) < 200]
    box = (xs[0], ys[0], xs[-1] + 1, ys[-1] + 1)
    tile = src.crop(box)
    side = min(tile.size)
    tile = tile.resize((side, side), Image.LANCZOS)
    big = side * 4
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.2), fill=255)
    mask = mask.resize((side, side), Image.LANCZOS)
    rgba = tile.convert("RGBA")
    rgba.putalpha(mask)
    for s in (512, 256, 128, 64):
        rgba.resize((s, s), Image.LANCZOS).save(OUT / f"logo-{s}.png", optimize=True)
    rgba.resize((256, 256), Image.LANCZOS).save(
        OUT / "firetier.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def arena():
    im = Image.open(GEN / "arena-gen.png").convert("RGB")
    for wdt in (1280, 640):
        r = im.resize((wdt, round(im.height * wdt / im.width)), Image.LANCZOS)
        r.save(OUT / f"arena-{wdt}.jpg", quality=86, optimize=True, progressive=True)


if __name__ == "__main__":
    rounded_logo()
    arena()
    for p in sorted(OUT.glob("*.*")):
        print(p.name, p.stat().st_size)

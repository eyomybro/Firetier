"""Writes Firetier's hand-made SVG art into web/assets/illus and web/assets/thumbs.

Nothing here is AI-generated. Palette is the Ember token set (web/css/tokens.css).
Run: python design/tools/make_illus.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "web" / "assets"
BG, S1, S2, S3, S4, LINE = "#0C0D10", "#131519", "#1A1D22", "#22262C", "#2A2F36", "#343941"
TX, TX2, TX3 = "#ECEDEF", "#A3A8B0", "#8A9099"
AC, AMBER, OK, WARN, ERR, INFO = "#FF6A3D", "#FFB547", "#3DD68C", "#F5B544", "#F2555A", "#5AA9FF"
FONT = "Segoe UI Variable Display, Segoe UI, sans-serif"


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">'
            f'<title>{title}</title>{body}</svg>\n')


# ---------- Empty / error state illustrations (160x120) ----------

def empty_profiles():
    b = f'''
<ellipse cx="80" cy="106" rx="54" ry="6" fill="{S1}"/>
<rect x="30" y="34" width="84" height="62" rx="8" fill="{S2}" stroke="{LINE}" transform="rotate(-6 72 65)"/>
<rect x="42" y="26" width="84" height="62" rx="8" fill="{S3}" stroke="{LINE}"/>
<rect x="54" y="40" width="40" height="5" rx="2.5" fill="{S4}"/>
<rect x="54" y="52" width="58" height="4" rx="2" fill="{S4}"/>
<rect x="54" y="62" width="48" height="4" rx="2" fill="{S4}"/>
<rect x="54" y="72" width="30" height="4" rx="2" fill="{S4}"/>
<circle cx="122" cy="30" r="15" fill="{AC}"/>
<path d="M122 23v14M115 30h14" stroke="#1A0C06" stroke-width="3" stroke-linecap="round"/>'''
    return svg(160, 120, b, "Empty profile list")


def empty_search():
    b = f'''
<ellipse cx="80" cy="106" rx="54" ry="6" fill="{S1}"/>
<rect x="24" y="30" width="96" height="16" rx="8" fill="{S2}" stroke="{LINE}"/>
<rect x="24" y="54" width="70" height="10" rx="5" fill="{S2}"/>
<rect x="24" y="70" width="84" height="10" rx="5" fill="{S2}"/>
<circle cx="104" cy="62" r="22" fill="{S3}" fill-opacity=".85" stroke="{TX3}" stroke-width="4"/>
<path d="M120 78l16 16" stroke="{TX3}" stroke-width="7" stroke-linecap="round"/>
<path d="M96 54l16 16M112 54l-16 16" stroke="{AC}" stroke-width="3.5" stroke-linecap="round"/>'''
    return svg(160, 120, b, "No search results")


def error_target():
    b = f'''
<ellipse cx="80" cy="106" rx="54" ry="6" fill="{S1}"/>
<path d="M44 18h50l22 22v58a6 6 0 0 1-6 6H44a6 6 0 0 1-6-6V24a6 6 0 0 1 6-6z" fill="{S3}" stroke="{LINE}"/>
<path d="M94 18v16a6 6 0 0 0 6 6h16" fill="{S4}" stroke="{LINE}"/>
<text x="50" y="58" font-family="Cascadia Mono, Consolas, monospace" font-size="13" fill="{TX3}">{{ "</text>
<rect x="50" y="66" width="44" height="4" rx="2" fill="{S4}"/>
<rect x="50" y="76" width="30" height="4" rx="2" fill="{ERR}" fill-opacity=".7"/>
<circle cx="112" cy="84" r="16" fill="{ERR}"/>
<path d="M112 76v10" stroke="#fff" stroke-width="3.2" stroke-linecap="round"/><circle cx="112" cy="92" r="2" fill="#fff"/>'''
    return svg(160, 120, b, "Unreadable settings file")


def empty_assets():
    b = f'''
<ellipse cx="80" cy="106" rx="54" ry="6" fill="{S1}"/>
<rect x="26" y="28" width="66" height="54" rx="7" fill="{S2}" stroke="{LINE}" transform="rotate(-8 59 55)"/>
<rect x="40" y="24" width="72" height="58" rx="7" fill="{S3}" stroke="{LINE}"/>
<circle cx="58" cy="42" r="7" fill="{AMBER}"/>
<path d="M44 78l20-22 14 14 10-9 20 17" fill="none" stroke="{TX3}" stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>
<rect x="98" y="50" width="40" height="40" rx="9" fill="{S4}" stroke="{LINE}"/>
<path d="M110 82V60l16-4v22" fill="none" stroke="{AC}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="107" cy="82" r="4" fill="{AC}"/><circle cx="123" cy="78" r="4" fill="{AC}"/>'''
    return svg(160, 120, b, "No local assets loaded")


def empty_log():
    b = f'''
<ellipse cx="80" cy="106" rx="54" ry="6" fill="{S1}"/>
<rect x="34" y="20" width="92" height="78" rx="8" fill="{S3}" stroke="{LINE}"/>
<rect x="34" y="20" width="92" height="16" rx="8" fill="{S4}"/>
<circle cx="44" cy="28" r="2.5" fill="{TX3}"/><circle cx="52" cy="28" r="2.5" fill="{TX3}"/>
<path d="M46 52l8 6-8 6" fill="none" stroke="{OK}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
<rect x="60" y="62" width="22" height="4" rx="2" fill="{TX3}"/>
<rect x="46" y="76" width="56" height="4" rx="2" fill="{S4}"/><rect x="46" y="85" width="40" height="4" rx="2" fill="{S4}"/>'''
    return svg(160, 120, b, "Log is empty")


def welcome():
    # Onboarding panel art (440x420): stacked flag cards feeding a settings file, with the honest ladder.
    rows = ""
    labels = [("FFlagDebugSkyGray", "true", OK), ("DFIntTextureQualityOverride", "0", OK),
              ("FIntDebugForceMSAASamples", "0", OK), ("FFlagFastGPULightCulling3", "true", WARN)]
    for i, (n, v, c) in enumerate(labels):
        y = 92 + i * 46
        rows += (f'<rect x="28" y="{y}" width="276" height="36" rx="7" fill="{S3}" stroke="{LINE}"/>'
                 f'<circle cx="44" cy="{y + 18}" r="4" fill="{c}"/>'
                 f'<text x="56" y="{y + 22}" font-family="Cascadia Mono, Consolas, monospace" font-size="10.5" fill="{TX2}">{n}</text>'
                 f'<text x="292" y="{y + 22}" text-anchor="end" font-family="Cascadia Mono, Consolas, monospace" font-size="10.5" fill="{TX}">{v}</text>')
    b = f'''
<rect width="440" height="420" fill="{S1}"/>
<g opacity=".55">{"".join(f'<path d="M0 {y}H440" stroke="{S2}"/>' for y in range(20, 420, 40))}</g>
<text x="40" y="66" font-family="{FONT}" font-size="12" font-weight="600" letter-spacing="1.2" fill="{TX3}">PROFILE · 4 FLAGS</text>
{rows}
<path d="M310 182H334" stroke="{AC}" stroke-width="2.5" stroke-dasharray="5 5" fill="none"/>
<path d="M330 175l9 7-9 7" fill="none" stroke="{AC}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M350 132h44l16 16v76a6 6 0 0 1-6 6h-54a6 6 0 0 1-6-6v-86a6 6 0 0 1 6-6z" fill="{S3}" stroke="{AC}" stroke-opacity=".6"/>
<rect x="358" y="160" width="40" height="4" rx="2" fill="{S4}"/><rect x="358" y="172" width="30" height="4" rx="2" fill="{S4}"/>
<rect x="358" y="184" width="36" height="4" rx="2" fill="{S4}"/><rect x="358" y="196" width="22" height="4" rx="2" fill="{S4}"/>
<text x="377" y="250" text-anchor="middle" font-family="{FONT}" font-size="11" fill="{TX3}">ClientAppSettings.json</text>
<g font-family="{FONT}" font-size="12" font-weight="600">
  <rect x="40" y="318" width="86" height="28" rx="14" fill="{OK}" fill-opacity=".13"/><text x="83" y="336.5" text-anchor="middle" fill="{OK}">Preview</text>
  <rect x="134" y="318" width="78" height="28" rx="14" fill="{OK}" fill-opacity=".13"/><text x="173" y="336.5" text-anchor="middle" fill="{OK}">Written</text>
  <rect x="220" y="318" width="92" height="28" rx="14" fill="{OK}" fill-opacity=".13"/><text x="266" y="336.5" text-anchor="middle" fill="{OK}">Read back</text>
  <rect x="40" y="354" width="168" height="28" rx="14" fill="none" stroke="{LINE}"/><text x="124" y="372.5" text-anchor="middle" fill="{TX3}">In-game: not verified</text>
</g>'''
    return svg(440, 420, b, "How Firetier applies a profile")


# ---------- Preset thumbnails (320x180) ----------

def scene(sky, wall, ground, block=0, sun=True, grass=True, shade=True):
    """Mini version of the offline preview scene: sky, brick wall, ground, shadow."""
    out = [f'<rect width="320" height="76" fill="{sky}"/>']
    if sun:
        out.append(f'<circle cx="34" cy="22" r="9" fill="#FFF0B9"/>')
    out.append(f'<rect y="76" width="320" height="104" fill="{ground}"/>')
    if grass:
        for i in range(26):
            x = (i * 53) % 312 + 4
            y = 84 + (i * 37) % 90
            out.append(f'<rect x="{x}" y="{y}" width="5" height="3" fill="#469A32" opacity=".8"/>')
    if shade:
        out.append(f'<rect x="62" y="126" width="210" height="10" fill="#000" opacity=".3"/>')
    out.append(f'<rect x="64" y="32" width="192" height="94" fill="{wall}"/>')
    if block:
        # bricks; larger block = more downscaled
        bh, bw = 8 * block, 22 * block
        for r, y in enumerate(range(32, 126, bh)):
            off = 0 if r % 2 == 0 else bw // 2
            for x in range(64 - off, 256, bw):
                x0, x1 = max(x, 64), min(x + bw - 2, 256)
                if x1 > x0:
                    out.append(f'<rect x="{x0}" y="{y}" width="{x1 - x0}" height="{min(bh - 2, 126 - y)}" fill="#000" opacity=".16"/>')
    if shade:
        out.append(f'<rect x="64" y="32" width="192" height="94" fill="url(#lit)"/>')
    return "".join(out)


LIT = ('<defs><linearGradient id="lit" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity=".08"/>'
       '<stop offset="1" stop-color="#000" stop-opacity=".32"/></linearGradient></defs>')


def chip(text, color, x=12, y=146):
    w = 30 + len(text) * 5.9  # 11px Segoe UI semibold averages ~5.9px per glyph
    return (f'<rect x="{x}" y="{y}" width="{w:.0f}" height="22" rx="11" fill="{BG}" fill-opacity=".82"/>'
            f'<circle cx="{x + 11}" cy="{y + 11}" r="3.5" fill="{color}"/>'
            f'<text x="{x + 20}" y="{y + 15}" font-family="{FONT}" font-size="11" font-weight="600" fill="{TX}">{text}</text>')


def thumb_notex():
    b = LIT + scene("#969696", "#8E7E70", "#6E6A63", block=0, sun=False, grass=False, shade=False) + chip("Textures off · grey sky", OK)
    return svg(320, 180, b, "No Textures preset")


def thumb_maxfps():
    sky = '<defs><linearGradient id="sk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#468CDC"/><stop offset="1" stop-color="#BEE1FF"/></linearGradient></defs>'
    b = LIT + sky + scene("url(#sk)", "#9A5A3C", "#4F7E3A", block=3, grass=False, shade=False) + chip("Low detail · textures kept", AMBER)
    return svg(320, 180, b, "Max FPS preset")


def thumb_balanced():
    sky = '<defs><linearGradient id="sk" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#468CDC"/><stop offset="1" stop-color="#BEE1FF"/></linearGradient></defs>'
    b = LIT + sky + scene("url(#sk)", "#A35F3E", "#4C8A3A", block=1) + chip("Balanced", INFO)
    return svg(320, 180, b, "Balanced preset")


def thumb_renderer(label, sub, color):
    tris = ""
    pts = [(160, 40), (110, 128), (210, 128), (135, 84), (185, 84), (160, 128)]
    for a, b_, c in [(0, 3, 4), (3, 1, 5), (4, 5, 2), (3, 5, 4)]:
        (x1, y1), (x2, y2), (x3, y3) = pts[a], pts[b_], pts[c]
        tris += f'<path d="M{x1} {y1}L{x2} {y2}L{x3} {y3}Z" fill="{color}" fill-opacity=".10" stroke="{color}" stroke-width="1.6" stroke-linejoin="round"/>'
    grid = "".join(f'<path d="M{x} 0V180" stroke="{S2}"/>' for x in range(0, 321, 32)) + \
           "".join(f'<path d="M0 {y}H320" stroke="{S2}"/>' for y in range(0, 181, 32))
    b = (f'<rect width="320" height="180" fill="{S1}"/>{grid}{tris}'
         f'<text x="160" y="160" text-anchor="middle" font-family="{FONT}" font-size="15" font-weight="700" fill="{TX}">{label}</text>'
         f'<text x="300" y="26" text-anchor="end" font-family="{FONT}" font-size="11" font-weight="600" fill="{TX3}">{sub}</text>')
    return svg(320, 180, b, f"Renderer preset: {label}")


def thumb_custom():
    rows = ""
    for i, (p, c) in enumerate([(0.72, AC), (0.35, TX3), (0.55, TX3)]):
        y = 50 + i * 34
        rows += (f'<rect x="56" y="{y}" width="208" height="4" rx="2" fill="{S4}"/>'
                 f'<rect x="56" y="{y}" width="{208 * p:.0f}" height="4" rx="2" fill="{c}"/>'
                 f'<circle cx="{56 + 208 * p:.0f}" cy="{y + 2}" r="8" fill="{TX}" stroke="{S1}" stroke-width="3"/>')
    b = f'<rect width="320" height="180" fill="{S2}"/>{rows}' + chip("Your profile", AC)
    return svg(320, 180, b, "User profile")


def thumb_imported():
    b = f'''<rect width="320" height="180" fill="{S2}"/>
<path d="M128 30h46l20 20v86a6 6 0 0 1-6 6h-60a6 6 0 0 1-6-6V36a6 6 0 0 1 6-6z" fill="{S3}" stroke="{LINE}"/>
<path d="M174 30v14a6 6 0 0 0 6 6h14" fill="{S4}" stroke="{LINE}"/>
<rect x="136" y="64" width="40" height="4" rx="2" fill="{S4}"/><rect x="136" y="76" width="30" height="4" rx="2" fill="{S4}"/>
<rect x="176" y="98" width="38" height="32" rx="6" fill="{S4}" stroke="{TX3}" stroke-width="1.5"/>
<path d="M184 98v-7a11 11 0 0 1 22 0v7" fill="none" stroke="{TX3}" stroke-width="3"/>
<circle cx="195" cy="113" r="3.5" fill="{TX2}"/>''' + chip("Stored only · not applied", TX3)
    return svg(320, 180, b, "Imported profile, stored only")


def game_all():
    tiles = ""
    cols = [S3, S4, S3, S4, S3, S3, S4, S3, S4, S3, S4, S3]
    for i in range(12):
        x, y = 22 + (i % 6) * 48, 30 + (i // 6) * 56
        tiles += f'<rect x="{x}" y="{y}" width="40" height="48" rx="6" fill="{cols[i]}" stroke="{LINE}"/>'
    b = (f'<rect width="320" height="180" fill="{S1}"/>{tiles}'
         f'<rect x="0" y="120" width="320" height="60" fill="url(#fd)"/>'
         f'<defs><linearGradient id="fd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{S1}" stop-opacity="0"/>'
         f'<stop offset="1" stop-color="{S1}"/></linearGradient></defs>'
         f'<text x="22" y="160" font-family="{FONT}" font-size="13" font-weight="600" fill="{TX2}">Applies to every Roblox game</text>')
    return svg(320, 180, b, "All Roblox games")


FILES = {
    "illus/empty-profiles.svg": empty_profiles, "illus/empty-search.svg": empty_search,
    "illus/error-target.svg": error_target, "illus/empty-assets.svg": empty_assets,
    "illus/empty-log.svg": empty_log, "illus/welcome.svg": welcome,
    "thumbs/preset-rivals-notex.svg": thumb_notex, "thumbs/preset-rivals-fps.svg": thumb_maxfps,
    "thumbs/preset-balanced.svg": thumb_balanced,
    "thumbs/preset-vulkan.svg": lambda: thumb_renderer("Vulkan", "RENDERER", AC),
    "thumbs/preset-d3d11.svg": lambda: thumb_renderer("Direct3D 11", "RENDERER", INFO),
    "thumbs/preset-opengl.svg": lambda: thumb_renderer("OpenGL", "RENDERER", AMBER),
    "thumbs/user.svg": thumb_custom, "thumbs/imported.svg": thumb_imported,
    "thumbs/game-all.svg": game_all,
}

if __name__ == "__main__":
    for rel, fn in FILES.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(fn(), encoding="utf-8")
        print(rel)

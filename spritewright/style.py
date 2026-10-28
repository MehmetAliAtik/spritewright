"""Game style guide: outputs/<Game>/{game-style.md, game-style.json, palette.hex, palette_preview.png}.

    sw.game_new("aurora quest", mood="cozy,retro", temperature="warm", palette="pico-8")
    st = sw.load_style("Aurora_Quest")          # dict (game-style.json)
    sw.game_palette_add("Aurora_Quest", "ff8800", role="lava")   # only after the user approved it

The palette (8-32 colours) is a subset of a base palette (palette name, .hex or .json) chosen by
farthest-point sampling in Lab (biased by temperature / saturation), always keeping the darkest and
the lightest colour. Every colour gets a unique USAGE role (outline, highlight, shadow_dark, skin,
skin_shadow, hair, hair_shadow, danger, background, accent, then usage families like foliage,
water_shadow, gold_light, wood_2 ...) assigned deterministically from luminance / hue / saturation;
override with roles={"3": "skin", "#ffec27": "gold"} (or a JSON file / "3=skin").
Hue-shifted ramps (palette.generate_ramp) are stored for the key roles, raw and snapped to the
game palette.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from .errors import PixelError
from .palette import Palette, generate_ramp, hsv, is_hex, luminance, parse_hex, rgb_to_lab, to_hex
from . import layout

SCHEMA = "spritewright.game-style/1"
OUTLINES = ("selective", "black", "none")
LIGHTS = {"top-left": (-1, -1), "top": (0, -1), "top-right": (1, -1), "left": (-1, 0), "right": (1, 0),
          "bottom-left": (-1, 1), "bottom": (0, 1), "bottom-right": (1, 1), "front": None}
DITHERS = ("none", "limited", "yes")
PROPORTIONS = ("chibi", "normal")
TEMPERATURES = ("warm", "cool", "neutral")
LEVELS = ("low", "medium", "high")
ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
KEY_ROLES = ("skin", "accent", "danger", "background", "light", "shadow", "highlight", "shadow_dark",
             "hair")
# role aliases: older guides use shadow/light, new ones shadow_dark/highlight
ROLE_ALIASES = {"shadow": ("shadow", "shadow_dark"), "light": ("light", "highlight")}
FILES = ("game-style.md", "game-style.json", "palette.hex", "palette_preview.png")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- palette subset + roles
def _hue_family(h, s, v):
    if s < 0.12:
        return "grey"
    if (h < 15 or h >= 345):
        return "red"
    if h < 45:
        return "brown" if v < 0.6 else "orange"
    if h < 70:
        return "yellow"
    if h < 160:
        return "green"
    if h < 200:
        return "teal"
    if h < 255:
        return "blue"
    if h < 290:
        return "purple"
    return "pink"


def pick_subset(colors, n, temperature="neutral", saturation="medium"):
    """Pick n of the hex colours (keeps base order): darkest + lightest, then farthest point in Lab,
    weighted toward warm/cool hues and low/high saturation."""
    rgbs = [parse_hex(c) for c in colors]
    if n >= len(rgbs):
        return [to_hex(c) for c in rgbs]
    import numpy as np
    lab = rgb_to_lab(np.array(rgbs, dtype=np.float64))
    lums = [luminance(c) for c in rgbs]
    hs = [hsv(c) for c in rgbs]

    def bias(i):
        h, s, _ = hs[i]
        b = 1.0
        if temperature == "warm" and s > 0.2 and (h < 70 or h >= 320):
            b += 0.25
        elif temperature == "cool" and s > 0.2 and 160 <= h < 280:
            b += 0.25
        if saturation == "high":
            b += 0.2 * s
        elif saturation == "low":
            b -= 0.2 * s
        return b

    chosen = [int(np.argmin(lums))]
    hi = int(np.argmax(lums))
    if hi not in chosen:
        chosen.append(hi)
    while len(chosen) < n:
        best, bi = -1.0, None
        for i in range(len(rgbs)):
            if i in chosen:
                continue
            d = min(float(np.linalg.norm(lab[i] - lab[j])) for j in chosen) * bias(i)
            if d > best:
                best, bi = d, i
        chosen.append(bi)
    return [to_hex(rgbs[i]) for i in sorted(chosen)]


# hue family -> usage role for the colours left after the key roles
USAGE_BY_FAMILY = {"green": "foliage", "teal": "water", "blue": "sky", "purple": "magic", "pink": "blossom",
                   "red": "cloth", "orange": "fire", "yellow": "gold", "brown": "wood", "grey": "stone"}


def auto_roles(colors):
    """Unique USAGE role per hex colour, deterministic, from luminance / hue / saturation:
    outline (darkest), highlight (lightest), shadow_dark, skin, skin_shadow, hair, hair_shadow,
    danger, background, accent, then usage families (foliage, water, sky, wood, gold, stone, ...)
    with _shadow (dark) / _light (bright) variants; repeats get _2, _3."""
    info = []
    for c in colors:
        rgb = parse_hex(c)
        h, s, v = hsv(rgb)
        info.append({"lum": luminance(rgb), "h": h, "s": s, "v": v})
    roles = [None] * len(colors)
    free = set(range(len(colors)))

    def take(role, cands, key):
        cands = [i for i in cands if i in free]
        if not cands:
            return None
        i = min(cands, key=key)
        roles[i] = role
        free.discard(i)
        return i

    take("outline", free, lambda i: info[i]["lum"])
    take("highlight", free, lambda i: -info[i]["lum"])
    cool_dark = [i for i in free if info[i]["lum"] < 0.12 and (200 <= info[i]["h"] < 300 or info[i]["s"] < 0.25)]
    take("shadow_dark", cool_dark or [i for i in free if info[i]["lum"] < 0.2] or free, lambda i: info[i]["lum"])
    skin = [i for i in free if 8 <= info[i]["h"] < 48 and 0.15 <= info[i]["s"] <= 0.7 and info[i]["v"] > 0.6]
    si = take("skin", skin, lambda i: abs(info[i]["h"] - 25) / 30 + abs(info[i]["s"] - 0.4) + abs(info[i]["v"] - 0.92))
    if si is not None:
        ss = [i for i in free if 0 <= info[i]["h"] < 45 and info[i]["lum"] < info[si]["lum"] - 0.05
              and info[i]["lum"] > 0.08 and info[i]["s"] > 0.2]
        take("skin_shadow", ss, lambda i: abs(info[i]["h"] - info[si]["h"]) / 30
             + abs(info[i]["lum"] - (info[si]["lum"] - 0.18)) * 3 + abs(info[i]["s"] - info[si]["s"]) * 1.5)
    red = [i for i in free if (info[i]["h"] < 18 or info[i]["h"] >= 335) and info[i]["s"] > 0.4 and info[i]["v"] > 0.35]
    take("danger", red, lambda i: -info[i]["s"] * info[i]["v"])
    hair = [i for i in free if 15 <= info[i]["h"] < 50 and info[i]["s"] > 0.45 and 0.15 < info[i]["lum"] < 0.6]
    hi = take("hair", hair, lambda i: abs(info[i]["lum"] - 0.35) + abs(info[i]["h"] - 30) / 60)
    if hi is not None:
        hs = [i for i in free if 0 <= info[i]["h"] < 50 and info[i]["lum"] < info[hi]["lum"] - 0.05
              and info[i]["s"] > 0.25]
        take("hair_shadow", hs, lambda i: abs(info[i]["h"] - info[hi]["h"]) / 30 + info[hi]["lum"] - info[i]["lum"])
    take("background", [i for i in free if info[i]["lum"] < 0.3],
         lambda i: info[i]["s"] + abs(info[i]["lum"] - 0.1) * 2)
    take("accent", free, lambda i: -(info[i]["s"] * info[i]["v"]))
    for i in sorted(free):
        fam = USAGE_BY_FAMILY[_hue_family(info[i]["h"], info[i]["s"], info[i]["v"])]
        fam += "_shadow" if info[i]["lum"] < 0.12 else "_light" if info[i]["lum"] > 0.55 else ""
        roles[i] = fam
    return _uniquify(roles)


def _uniquify(roles, fixed=()):
    seen, out = set(roles[i] for i in fixed), []
    for i, r in enumerate(roles):
        if i in fixed:
            out.append(r)
            continue
        base, k, cand = r, 2, r
        while cand in seen:
            cand = f"{base}_{k}"
            k += 1
        seen.add(cand)
        out.append(cand)
    return out


def _check_role(role):
    r = str(role).strip().lower().replace("-", "_").replace(" ", "_")
    if not ROLE_RE.match(r):
        raise PixelError(f"role {role!r} is invalid: use lowercase letters, digits and _ (e.g. skin, accent_2)")
    return r


def parse_roles(spec):
    """None | dict | JSON file path | inline '3=skin,#ffec27=gold' -> {key: role}."""
    if not spec:
        return {}
    if isinstance(spec, dict):
        return {str(k): v for k, v in spec.items()}
    p = Path(str(spec))
    if p.suffix.lower() == ".json" and p.is_file():
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, list):  # [{"hex"|"index": .., "role": ..}]
            return {str(e.get("hex", e.get("index"))): e["role"] for e in d}
        return {str(k): v for k, v in d.items()}
    out = {}
    for pair in str(spec).split(","):
        if "=" not in pair:
            raise PixelError(f"roles: expected key=role pairs (index or hex), got {pair!r}")
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def apply_roles(colors, roles, overrides):
    """overrides keys: palette index ('3') or hex ('#ffec27' / 'ffec27')."""
    roles = list(roles)
    fixed = set()
    for k, v in overrides.items():
        k = str(k).strip()
        if k.lstrip("-").isdigit():
            i = int(k)
            if not 0 <= i < len(colors):
                raise PixelError(f"roles: index {i} outside the palette (0..{len(colors) - 1})")
        elif is_hex(k.lstrip("#")):
            h = to_hex(parse_hex(k))
            if h not in colors:
                raise PixelError(f"roles: colour #{h} is not in the game palette")
            i = colors.index(h)
        else:
            raise PixelError(f"roles: key {k!r} must be a palette index or a hex colour")
        roles[i] = _check_role(v)
        fixed.add(i)
    vals = [roles[i] for i in fixed]
    if len(vals) != len(set(vals)):
        raise PixelError(f"roles: the same role was given to several colours: {sorted(vals)}")
    return _uniquify(roles, fixed)


# --------------------------------------------------------------------------- build / write
def _ramps(palette_entries, shading):
    hexes = [e["hex"] for e in palette_entries]
    pal = Palette(hexes, name="game")
    steps = max(3, min(7, 2 * int(shading) + 1))
    out = {}
    for e in palette_entries:
        if e["role"] in KEY_ROLES or e["role"].split("_")[0] in ("green", "blue", "red", "yellow", "orange") \
                or e["role"] in USAGE_BY_FAMILY.values():
            if e["role"] in ("outline",):
                continue
            raw = generate_ramp(e["hex"], steps)
            idx = generate_ramp(e["hex"], steps, palette=pal)
            out[e["role"]] = {"base": e["hex"], "ramp": raw, "in_palette": idx,
                              "in_palette_hex": [hexes[i] for i in idx]}
    return out


def _rules(st):
    W, H = st["cell"]
    out_role = next((e for e in st["palette"] if e["role"] == "outline"), st["palette"][0])
    light = st["light"]
    opp = {"top-left": "bottom-right", "top": "bottom", "top-right": "bottom-left", "left": "right",
           "right": "left", "bottom-left": "top-right", "bottom": "top", "bottom-right": "top-left"}.get(light)
    mood = ", ".join(st["mood"]) or "neutral"
    th = st["theme"]
    do = [
        f"Draw every sprite on the {W}x{H} cell; import with PPU {st['ppu']}, Filter Point, Compression None.",
        f"Use only the {len(st['palette'])} colours of palette.hex, at most {st['max_colors']} per sprite.",
        {"selective": "Selective outline: outline each area with a darker shade of its own ramp; use the "
                      f"outline colour #{out_role['hex']} only where the silhouette meets the background.",
         "black": f"Close every silhouette with a 1 px outline in #{out_role['hex']} (role outline).",
         "none": "No outlines: separate shapes by value / hue contrast."}[st["outline"]],
        (f"Light comes from the {light}: lit pixels on the {light} side, shadows toward the {opp}."
         if opp else "Light is frontal: shade toward the silhouette edges evenly."),
        f"Use {st['shading']} shade step(s) per material, taken from the ramps in game-style.json.",
        {"chibi": "Chibi proportions: big head (about 1/2 of the body height) - see `blueprint --style chibi`.",
         "normal": "Normal proportions (about 3-4 heads tall) - see `blueprint --style normal`."}[st["proportions"]],
        f"Keep the mood {mood}: {th['temperature']} colours, {th['saturation']} saturation, "
        f"{th['contrast']} contrast.",
    ]
    dont = [
        "Don't add colours outside palette.hex - ask first; after approval use game-palette-add.",
        "Don't use anti-aliasing or semi-transparent pixels (alpha only 0 or 255).",
        {"none": "Don't dither.",
         "limited": "Dither only on large gradients (sky, big surfaces), never on characters or small props.",
         "yes": "Don't dither details smaller than 3 px; keep dither patterns regular."}[st["dither"]],
        "Don't use pillow shading (light from every side)" + (f" or light from the {opp}." if opp else "."),
        "Don't mix pixel sizes: no scaled, rotated or sub-pixel-moved sprites; 1 sprite pixel = 1 texel.",
        "Don't change the cell size between animations of one character.",
        {"selective": "Don't use a pure dark outline all around every shape.",
         "black": "Don't leave silhouettes open or use coloured outlines.",
         "none": "Don't add outlines."}[st["outline"]],
    ]
    return {"do": do, "dont": dont}


def _theme_text(st):
    th = st["theme"]
    t = {"warm": "warm (reds, oranges, golden light; shadows lean purple)",
         "cool": "cool (blues, teals; highlights lean yellow, shadows lean blue)",
         "neutral": "neutral (balanced hues)"}[th["temperature"]]
    return (f"Colour temperature {t}; {th['saturation']} saturation; {th['contrast']} value contrast "
            f"between characters and backgrounds.")


def render_md(st):
    W, H = st["cell"]
    L = [f"# {st['name']} - game style guide", "",
         f"_Generated by spritewright; machine-readable twin: game-style.json. Last update: {st['updated']}._", "",
         "## Description", "", st["description"], "",
         "## Mood", "", ", ".join(st["mood"]) or "-", "",
         "## Theme & colour direction", "", _theme_text(st), "",
         f"## Palette ({len(st['palette'])} colours, base: {st.get('palette_source', '-')})", "",
         "| # | hex | role |", "|---|-----|------|"]
    for e in st["palette"]:
        L.append(f"| {e['index']} | `#{e['hex']}` | {e['role']} |")
    L += ["", "Files: `palette.hex` (one hex per line), `palette_preview.png` (index + role).", "",
          "## Ramps (hue-shifted, dark -> light)", ""]
    for role, r in st["ramps"].items():
        L.append(f"- **{role}** (#{r['base']}): " + " ".join(f"#{h}" for h in r["ramp"])
                 + "  -> in palette: " + " ".join(f"#{h}" for h in r["in_palette_hex"]))
    L += ["", "## Visual rules", "",
          f"- Cell size: {W}x{H} px (all animations of a character use the same cell)",
          f"- Pixels Per Unit: {st['ppu']}",
          f"- Outline: {st['outline']}",
          f"- Light direction: {st['light']}",
          f"- Shading layers: {st['shading']}",
          f"- Dithering: {st['dither']}",
          f"- Max colours per sprite: {st['max_colors']}",
          f"- Proportions: {st['proportions']}", "",
          "## Do", ""] + [f"- {x}" for x in st["rules"]["do"]] + ["", "## Don't", ""] + \
         [f"- {x}" for x in st["rules"]["dont"]] + ["", "## Change log", ""] + \
         [f"- {c['date']}: {c['text']}" for c in st.get("changelog", [])] + [""]
    return "\n".join(L)


def palette_preview(entries, path, cols=8):
    from .export import _font
    cell, lab = 76, 30
    n = len(entries)
    cols = min(cols, n)
    rows = (n + cols - 1) // cols
    gap = 8
    img = Image.new("RGBA", (cols * (cell + gap) + gap, rows * (cell + lab + gap) + gap), (28, 28, 36, 255))
    dr = ImageDraw.Draw(img)
    f = _font(11)
    for k, e in enumerate(entries):
        x = gap + (k % cols) * (cell + gap)
        y = gap + (k // cols) * (cell + lab + gap)
        dr.rectangle([x, y, x + cell - 1, y + cell - 1], fill=parse_hex(e["hex"]), outline=(90, 90, 100))
        dr.text((x + 1, y + cell + 2), f"{e['index']} #{e['hex']}", fill=(230, 230, 230), font=f)
        dr.text((x + 1, y + cell + 15), e["role"][:13], fill=(180, 200, 255), font=f)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p)
    return p


def write_style(st, gdir):
    """(Re)write all four style files from the style dict."""
    gdir = Path(gdir)
    gdir.mkdir(parents=True, exist_ok=True)
    for i, e in enumerate(st["palette"]):
        e["index"] = i
    st["rules"] = _rules(st)
    (gdir / "game-style.json").write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (gdir / "palette.hex").write_text("\n".join(e["hex"] for e in st["palette"]) + "\n", encoding="utf-8")
    (gdir / "game-style.md").write_text(render_md(st), encoding="utf-8")
    palette_preview(st["palette"], gdir / "palette_preview.png")
    return {f: gdir / f for f in FILES}


def _choice(v, choices, what):
    v = str(v).strip().lower()
    if v not in choices:
        raise PixelError(f"{what} must be one of {', '.join(choices)}; got {v!r}")
    return v


def game_new(name, mood="", temperature="neutral", saturation="medium", contrast="medium", cell="32x32",
             ppu=None, outline="selective", light="top-left", shading=2, dither="none", max_colors=16,
             proportions="chibi", palette="pico-8", colors=None, roles=None, description=None,
             root=None, force=False):
    """Create outputs/<Game>/ with the style guide files. Returns (style dict, paths)."""
    from .unity import _parse_cell, recommend_ppu
    gname = layout.normalize_name(name)
    gdir = layout.game_dir(gname, root)
    if (gdir / "game-style.json").exists() and not force:
        raise PixelError(f"{gdir / 'game-style.json'} already exists; the style guide is only changed on "
                         f"explicit request - pass --force to overwrite it")
    base = Palette.load(palette)
    all_hex = [to_hex(c) for c in base.colors]
    if len(set(all_hex)) != len(all_hex):
        all_hex = list(dict.fromkeys(all_hex))
    n = int(colors) if colors else min(len(all_hex), 32)
    if not 8 <= n <= 32:
        raise PixelError(f"game palette must have 8-32 colours; got {n}")
    if n > len(all_hex):
        raise PixelError(f"--colors {n} but base palette {base.name!r} has only {len(all_hex)} colours")
    temperature = _choice(temperature, TEMPERATURES, "temperature")
    saturation = _choice(saturation, LEVELS, "saturation")
    contrast = _choice(contrast, LEVELS, "contrast")
    hexes = pick_subset(all_hex, n, temperature, saturation)
    inv = {i: nm for nm, i in base.names.items()}
    named = [inv.get(all_hex.index(h)) for h in hexes]
    if all(named):  # palette json with names -> use them as roles
        rl = _uniquify([_check_role(x) for x in named])
    else:
        rl = auto_roles(hexes)
    rl = apply_roles(hexes, rl, parse_roles(roles))
    cw, ch = _parse_cell(cell)
    mc = int(max_colors)
    if not 2 <= mc <= 32:
        raise PixelError(f"max-colors must be 2..32, got {mc}")
    sh = int(shading)
    if not 1 <= sh <= 4:
        raise PixelError(f"shading must be 1..4 layers, got {sh}")
    moods = [m.strip().lower() for m in (mood.split(",") if isinstance(mood, str) else mood or []) if m.strip()]
    entries = [{"index": i, "hex": h, "role": r} for i, (h, r) in enumerate(zip(hexes, rl))]
    now = _now()
    st = {
        "schema": SCHEMA, "name": gname,
        "description": description or (f"{gname.replace('_', ' ')}: a {', '.join(moods) or 'neutral'} pixel-art game "
                                       f"with {temperature} colours, {proportions} characters on a {cw}x{ch} grid."),
        "mood": moods,
        "theme": {"temperature": temperature, "saturation": saturation, "contrast": contrast},
        "palette_source": _portable_source(base), "palette": entries,
        "cell": [cw, ch], "ppu": int(ppu) if ppu else recommend_ppu(ch),
        "outline": _choice(outline, OUTLINES, "outline"), "light": _choice(light, tuple(LIGHTS), "light"),
        "shading": sh, "dither": _choice(dither, DITHERS, "dither"), "max_colors": mc,
        "proportions": _choice(proportions, PROPORTIONS, "proportions"),
        "created": now, "updated": now,
        "changelog": [{"date": now, "text": f"style guide created ({n} colours from {base.name})"}],
    }
    st["ramps"] = _ramps(entries, sh)
    paths = write_style(st, gdir)
    layout.write_index(root)
    return st, paths


def _portable_source(pal):
    """Palette name, or the file name of a palette file (no absolute paths in game-style.json)."""
    s = str(pal.source or pal.name)
    return Path(s).name if ("/" in s or "\\" in s) else s


def load_style(game, root=None):
    gdir = layout.game_dir(layout.normalize_name(game), root)
    p = gdir / "game-style.json"
    if not p.is_file():
        raise PixelError(f"game {game!r} has no style guide ({p} missing); create it with game-new")
    return json.loads(p.read_text(encoding="utf-8"))


def style_palette(st):
    """Palette object of the game (names = roles)."""
    return Palette([e["hex"] for e in st["palette"]], names={e["role"]: i for i, e in enumerate(st["palette"])},
                   name=f"{st['name']}-palette")


def validate_style(st, gdir=None):
    """-> (errors, warnings)."""
    errs, warns = [], []
    pal = st.get("palette") or []
    if not 8 <= len(pal) <= 32:
        errs.append(f"palette has {len(pal)} colours (needs 8-32)")
    hexes, roles = [], []
    for e in pal:
        h, r = str(e.get("hex", "")), str(e.get("role", ""))
        if not is_hex(h):
            errs.append(f"palette entry {e}: hex invalid")
        if not ROLE_RE.match(r):
            errs.append(f"palette entry {e}: role invalid/missing")
        hexes.append(h.lower())
        roles.append(r)
    if len(set(hexes)) != len(hexes):
        errs.append("duplicate colours in the palette")
    if len(set(roles)) != len(roles):
        errs.append("duplicate roles in the palette")
    for need in ("outline", "shadow", "light"):
        if not set(ROLE_ALIASES.get(need, (need,))) & set(roles):
            warns.append(f"no colour with role '{need}'")
    c = st.get("cell") or []
    if not (len(c) == 2 and all(isinstance(v, int) and 1 <= v <= 256 for v in c)):
        errs.append(f"cell {c} invalid")
    if not isinstance(st.get("ppu"), int) or st["ppu"] < 1:
        errs.append(f"ppu {st.get('ppu')} invalid")
    for k, ch in (("outline", OUTLINES), ("light", tuple(LIGHTS)), ("dither", DITHERS), ("proportions", PROPORTIONS)):
        if st.get(k) not in ch:
            errs.append(f"{k} {st.get(k)!r} not in {ch}")
    if not (isinstance(st.get("shading"), int) and 1 <= st["shading"] <= 4):
        errs.append(f"shading {st.get('shading')} invalid (1..4)")
    mc = st.get("max_colors")
    if not (isinstance(mc, int) and 2 <= mc <= 32):
        errs.append(f"max_colors {mc} invalid (2..32)")
    elif mc > len(pal):
        warns.append(f"max_colors {mc} > palette size {len(pal)}")
    rules = st.get("rules") or {}
    for k in ("do", "dont"):
        if not 5 <= len(rules.get(k, [])) <= 8:
            warns.append(f"{k} list has {len(rules.get(k, []))} items (expected 5-8)")
    if gdir is not None:
        gdir = Path(gdir)
        for f in FILES:
            if not (gdir / f).is_file():
                errs.append(f"{f} missing")
        hp = gdir / "palette.hex"
        if hp.is_file():
            got = [ln.strip().lower() for ln in hp.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if got != hexes:
                errs.append("palette.hex does not match game-style.json")
    return errs, warns


def style_text(st, errs=(), warns=()):
    W, H = st["cell"]
    L = [f"=== {st['name']} ===", st["description"],
         f"mood: {', '.join(st['mood']) or '-'} | {st['theme']['temperature']}, {st['theme']['saturation']} "
         f"saturation, {st['theme']['contrast']} contrast",
         f"cell {W}x{H}, PPU {st['ppu']}, outline {st['outline']}, light {st['light']}, shading {st['shading']}, "
         f"dither {st['dither']}, max {st['max_colors']} colours, {st['proportions']}",
         f"palette ({len(st['palette'])}):"]
    for e in st["palette"]:
        L.append(f"  {e['index']:2d}  #{e['hex']}  {e['role']}")
    L.append("do:")
    L += [f"  + {x}" for x in st.get("rules", {}).get("do", [])]
    L.append("don't:")
    L += [f"  - {x}" for x in st.get("rules", {}).get("dont", [])]
    for w in warns:
        L.append(f"WARN  {w}")
    for e in errs:
        L.append(f"ERROR {e}")
    L.append("style: " + ("INVALID" if errs else "OK"))
    return "\n".join(L)


def game_palette_add(game, hex_color, role, root=None):
    """Append one approved colour (with a unique role) and rewrite all style files."""
    gname = layout.normalize_name(game)
    gdir = layout.game_dir(gname, root)
    st = load_style(gname, root)
    if not is_hex(str(hex_color).lstrip("#")):
        raise PixelError(f"{hex_color!r} is not a RRGGBB hex colour")
    h = to_hex(parse_hex(hex_color))
    role = _check_role(role)
    if any(e["hex"] == h for e in st["palette"]):
        raise PixelError(f"#{h} is already in the {gname} palette")
    if any(e["role"] == role for e in st["palette"]):
        raise PixelError(f"role {role!r} is already used in the {gname} palette")
    if len(st["palette"]) >= 32:
        raise PixelError("the game palette already has 32 colours (maximum)")
    st["palette"].append({"index": len(st["palette"]), "hex": h, "role": role})
    st["ramps"] = _ramps(st["palette"], st["shading"])
    st["updated"] = _now()
    st.setdefault("changelog", []).append({"date": st["updated"], "text": f"colour #{h} added as '{role}' "
                                                                         "(user approved)"})
    paths = write_style(st, gdir)
    layout.write_index(root)
    return st, paths

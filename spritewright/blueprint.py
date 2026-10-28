"""Character proportion blueprints (drawing guides) for 16/32/48 px sprites.

Template data lives in templates/blueprints.json (editable). get_blueprint() returns the landmark
coordinates for a size/style (other sizes are scaled from the nearest template -> approximate),
blueprint_text() a table, render_blueprint() a scaled PNG guide (pixel grid, coloured landmark
lines, labels, optional sprite underlay) and draw_blueprint()/add_blueprint_layer() put the guide
into a Canvas / a hidden LayerStack layer as an underlay for drawing.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from .canvas import Canvas
from .errors import PixelError

TEMPLATE_FILE = Path(__file__).resolve().parent / "templates" / "blueprints.json"

# key, label, kind, colour. kind: y (row line) | lr (row with left/right points) | pt (point) | box
LANDMARKS = [
    ("head_top", "head top", "y", (220, 50, 50)),
    ("head", "head box", "box", (220, 50, 50)),
    ("eye_line", "eye line", "y", (40, 110, 230)),
    ("eye_left", "eye L", "pt", (40, 110, 230)),
    ("eye_right", "eye R", "pt", (40, 110, 230)),
    ("mouth", "mouth", "pt", (210, 40, 170)),
    ("chin", "chin", "y", (235, 120, 30)),
    ("neck", "neck", "y", (200, 150, 30)),
    ("shoulders", "shoulders", "lr", (200, 170, 0)),
    ("elbows", "elbows", "lr", (0, 170, 190)),
    ("hands", "hands", "lr", (40, 170, 60)),
    ("waist", "waist / belt", "y", (150, 90, 40)),
    ("hips", "hips", "lr", (140, 70, 200)),
    ("knees", "knees", "lr", (0, 140, 120)),
    ("feet", "feet", "lr", (230, 90, 140)),
    ("ground", "ground line", "y", (150, 20, 20)),
    ("center_x", "center axis", "x", (110, 110, 110)),  # left edge of column
    ("pivot", "foot pivot", "pt", (255, 0, 0)),
]
REQUIRED = [k for k, *_ in LANDMARKS] + ["eye_size"]


def load_blueprints(path=None) -> dict:
    p = Path(path) if path else TEMPLATE_FILE
    if not p.is_file():
        raise PixelError(f"blueprint template file {p} not found")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PixelError(f"{p}: invalid JSON at line {e.lineno}: {e.msg}") from None
    for n, t in d.get("templates", {}).items():
        miss = [k for k in REQUIRED + ["size", "style"] if k not in t]
        if miss:
            raise PixelError(f"{p}: blueprint {n!r} misses keys: {', '.join(miss)}")
    return d


def _size(size):
    if isinstance(size, int):
        return size, size
    if isinstance(size, str):
        try:
            if "x" in size.lower():
                w, h = (int(t) for t in size.lower().split("x"))
            else:
                w = h = int(size)
            return w, h
        except ValueError:
            raise PixelError(f"blueprint size must be N or WxH, got {size!r}") from None
    w, h = size
    return int(w), int(h)


def styles(lib=None):
    lib = lib or load_blueprints()
    return sorted({t["style"] for t in lib["templates"].values()})


def get_blueprint(size=32, style="chibi", lib=None) -> dict:
    """Landmarks for a WxH character. Exact for a stored template size, else scaled from the
    template of that style whose height is nearest (marked approximate)."""
    lib = lib if isinstance(lib, dict) else load_blueprints(lib)
    w, h = _size(size)
    if not (8 <= w <= 256 and 8 <= h <= 256):
        raise PixelError(f"blueprint size {w}x{h} out of range 8..256")
    cands = {n: t for n, t in lib["templates"].items() if t["style"] == style}
    if not cands:
        raise PixelError(f"unknown blueprint style {style!r}; styles: {', '.join(styles(lib))}")
    name, t = min(cands.items(), key=lambda kv: (abs(kv[1]["size"][1] - h) + abs(kv[1]["size"][0] - w),
                                                  -kv[1]["size"][1]))
    tw, th = t["size"]
    exact = (tw, th) == (w, h)
    sx, sy = w / tw, h / th

    def X(v):
        return min(w - 1, max(0, int((v + 0.5) * sx))) if not exact else int(v)

    def Y(v):
        return min(h - 1, max(0, int((v + 0.5) * sy))) if not exact else int(v)

    bp = {"name": f"{style}_{w}x{h}", "size": [w, h], "style": style, "base_template": name,
          "approximate": not exact, "heads_tall": t.get("heads_tall"), "description": t.get("description", ""),
          "scale_from_template": [round(sx, 4), round(sy, 4)]}
    for k, _, kind, _ in LANDMARKS:
        v = t[k]
        if kind == "y":
            bp[k] = Y(v)
        elif kind == "x":
            bp[k] = X(v)
        elif kind == "pt":
            bp[k] = [X(v[0]), Y(v[1])]
        elif kind == "lr":
            bp[k] = {"y": Y(v["y"]), "left": X(v["left"]), "right": X(v["right"])}
        elif kind == "box":
            bp[k] = {"left": X(v["left"]), "right": X(v["right"]), "bottom": Y(v["bottom"])}
    es = t["eye_size"]
    bp["eye_size"] = [max(1, round(es[0] * sx)), max(1, round(es[1] * sy))] if not exact else list(es)
    if not exact:  # keep pairs that were mirror-symmetric in the template symmetric after scaling
        c, c2 = t["center_x"], bp["center_x"]
        for k, _, kind, _ in LANDMARKS:
            if kind == "lr" and t[k]["right"] == 2 * c - 1 - t[k]["left"]:
                bp[k]["right"] = min(w - 1, 2 * c2 - 1 - bp[k]["left"])
        ew0, ew = t["eye_size"][0], bp["eye_size"][0]
        if t["eye_right"][0] + ew0 - 1 == 2 * c - 1 - t["eye_left"][0]:
            bp["eye_right"][0] = min(w - ew, 2 * c2 - 1 - bp["eye_left"][0] - (ew - 1))
        bp["note"] = (f"approximate: scaled {sx:.3g}x{sy:.3g} from template {name} ({tw}x{th}); "
                      f"check eye/limb widths by eye")
    return bp


def points_inside(bp) -> list:
    """List of 'key=value' entries that fall outside the canvas (empty = all inside)."""
    w, h = bp["size"]
    bad = []
    for k, _, kind, _ in LANDMARKS:
        v = bp[k]
        xs, ys = [], []
        if kind == "y":
            ys = [v]
        elif kind == "x":
            xs = [v]
        elif kind == "pt":
            xs, ys = [v[0]], [v[1]]
        elif kind == "lr":
            xs, ys = [v["left"], v["right"]], [v["y"]]
        elif kind == "box":
            xs, ys = [v["left"], v["right"]], [v["bottom"]]
        if any(not 0 <= x < w for x in xs) or any(not 0 <= y < h for y in ys):
            bad.append(f"{k}={v}")
    return bad


def blueprint_text(bp) -> str:
    w, h = bp["size"]
    L = [f"blueprint {bp['style']} {w}x{h}" + (f"  (APPROXIMATE, scaled from {bp['base_template']})"
                                               if bp["approximate"] else f"  (template {bp['base_template']})"),
         f"{bp['description']}" + (f"; ~{bp['heads_tall']} heads tall" if bp.get("heads_tall") else ""),
         "coordinates: sprite pixels, x right / y down, 0-based; L/R = screen left/right",
         f"{'landmark':14s} {'y':>4s} {'x / left..right':>18s}"]
    for k, label, kind, _ in LANDMARKS:
        v = bp[k]
        if kind == "y":
            L.append(f"{label:14s} {v:4d}")
        elif kind == "x":
            L.append(f"{label:14s} {'':4s} {v:18d}")
        elif kind == "pt":
            extra = f"  size {bp['eye_size'][0]}x{bp['eye_size'][1]}" if k.startswith("eye") else ""
            L.append(f"{label:14s} {v[1]:4d} {v[0]:18d}{extra}")
        elif kind == "lr":
            L.append(f"{label:14s} {v['y']:4d} {str(v['left']) + '..' + str(v['right']):>18s}")
        elif kind == "box":
            L.append(f"{label:14s} {bp['head_top']:>2d}-{v['bottom']:<2d}"
                     f"{str(v['left']) + '..' + str(v['right']):>17s}")
    if bp.get("note"):
        L.append(f"note: {bp['note']}")
    return "\n".join(L)


# --------------------------------------------------------------------------- PNG guide
def _font(size):
    from .export import _font as f
    return f(size)


def render_blueprint(bp, path, scale=None, overlay=None, frame=None, grid=True, labels=True):
    """Scaled PNG guide: white board, pixel grid (major line every 8 px), coloured landmark rows,
    points as outlined cells, centre axis, labels in a legend column. overlay: sprite source /
    Canvas drawn faintly underneath (compare proportions with an existing character)."""
    w, h = bp["size"]
    s = int(scale or max(4, min(32, 512 // max(w, h))))
    legend = 190 if labels else 0
    top = 28 if labels else 0
    W, H = w * s + legend, h * s + top + 8
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    ox, oy = 0, top
    if overlay is not None:
        from .export import _canvas_of
        cv = _canvas_of(overlay, frame)
        if cv.size != (w, h):
            raise PixelError(f"overlay is {cv.w}x{cv.h}, blueprint is {w}x{h}")
        ov = cv.to_image(s)
        a = ov.getchannel("A").point(lambda v: v * 115 // 255)
        ov.putalpha(a)
        img.alpha_composite(ov, (ox, oy))
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(lay)
    if grid:
        for i in range(w + 1):
            c = (90, 90, 110, 120) if i % 8 == 0 else (150, 150, 170, 55)
            dr.line([(ox + i * s, oy), (ox + i * s, oy + h * s)], fill=c, width=1)
        for j in range(h + 1):
            c = (90, 90, 110, 120) if j % 8 == 0 else (150, 150, 170, 55)
            dr.line([(ox, oy + j * s), (ox + w * s, oy + j * s)], fill=c, width=1)

    def cell(x, y, col, width=2, fill_a=70):
        x0, y0 = ox + x * s, oy + y * s
        dr.rectangle([x0, y0, x0 + s - 1, y0 + s - 1], fill=col + (fill_a,), outline=col + (255,), width=width)

    def row(y, col):
        yc = oy + y * s + s // 2
        dr.rectangle([ox, oy + y * s, ox + w * s - 1, oy + y * s + s - 1], fill=col + (28,))
        dr.line([(ox, yc), (ox + w * s - 1, yc)], fill=col + (230,), width=max(1, s // 8))
        return yc

    marks = []  # (y_pixel_on_image, label, colour)
    for k, label, kind, col in LANDMARKS:
        v = bp[k]
        if kind == "y":
            marks.append((row(v, col), f"{label}  y={v}", col))
        elif kind == "x":  # axis on the left edge of column center_x (= Unity bottom-center pivot)
            xc = ox + v * s
            for yy in range(oy, oy + h * s, max(2, s // 2)):
                dr.line([(xc, yy), (xc, min(oy + h * s - 1, yy + max(1, s // 4)))], fill=col + (220,),
                        width=max(1, s // 8))
        elif kind == "lr":
            yc = oy + v["y"] * s + s // 2
            dr.line([(ox + v["left"] * s + s // 2, yc), (ox + v["right"] * s + s // 2, yc)], fill=col + (200,),
                    width=max(1, s // 8))
            cell(v["left"], v["y"], col)
            cell(v["right"], v["y"], col)
            marks.append((yc, f"{label}  y={v['y']} x={v['left']}/{v['right']}", col))
        elif kind == "pt":
            if k.startswith("eye"):
                ew, eh = bp["eye_size"]
                for dx in range(ew):
                    for dy in range(eh):
                        cell(v[0] + dx, v[1] + dy, col, width=1, fill_a=110)
            elif k == "pivot":
                xc, yc = ox + v[0] * s, oy + v[1] * s + s
                r = max(4, s // 2)
                dr.line([(xc - r, yc), (xc + r, yc)], fill=col + (255,), width=2)
                dr.line([(xc, yc - r), (xc, yc + r)], fill=col + (255,), width=2)
                dr.ellipse([xc - 3, yc - 3, xc + 3, yc + 3], outline=col + (255,), width=2)
                marks.append((yc, f"{label}  ({v[0]},{v[1]})", col))
                continue
            else:
                cell(v[0], v[1], col)
            if k != "eye_right":
                txt = f"{label}  ({v[0]},{v[1]})" if k != "eye_left" else \
                    f"eyes  ({bp['eye_left'][0]},{v[1]}) ({bp['eye_right'][0]},{bp['eye_right'][1]})"
                marks.append((oy + v[1] * s + s // 2, txt, col))
        elif kind == "box":
            dr.rectangle([ox + v["left"] * s, oy + bp["head_top"] * s, ox + (v["right"] + 1) * s - 1,
                          oy + (v["bottom"] + 1) * s - 1], outline=col + (160,), width=max(1, s // 10))
    img.alpha_composite(lay)
    if labels:
        dr = ImageDraw.Draw(img)
        f = _font(12)
        title = f"{bp['style']} {w}x{h}" + (" (approx.)" if bp["approximate"] else "") + \
            (f"  ~{bp['heads_tall']} heads" if bp.get("heads_tall") else "") + f"  x{s}"
        dr.text((4, 6), title, fill=(30, 30, 40), font=_font(14))
        # legend with simple collision avoidance (min 14 px apart, keep order)
        marks.sort(key=lambda m: m[0])
        placed, last = [], -1e9
        for y, txt, col in marks:
            ly = max(y, last + 14)
            placed.append((y, ly, txt, col))
            last = ly
        over = last - (H - 8)
        if over > 0:
            placed = [(y, ly - over, t, c) for y, ly, t, c in placed]
        lx = ox + w * s + 10
        for y, ly, txt, col in placed:
            dr.line([(ox + w * s, y), (lx - 2, ly)], fill=col + (255,), width=1)
            dr.text((lx, ly - 7), txt, fill=col, font=f)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p)
    return p


def save_blueprint(size=32, style="chibi", out_dir=None, scale=None, overlay=None, frame=None, lib=None):
    """Write <style>_<w>x<h>.png/.json/.txt into out_dir. Returns (bp, {png, json, txt})."""
    from .sprite import output_root
    bp = get_blueprint(size, style, lib)
    d = Path(out_dir) if out_dir else output_root() / "blueprints"
    d.mkdir(parents=True, exist_ok=True)
    base = d / bp["name"]
    paths = {"png": render_blueprint(bp, base.with_suffix(".png"), scale=scale, overlay=overlay, frame=frame)}
    base.with_suffix(".json").write_text(json.dumps(bp, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".txt").write_text(blueprint_text(bp) + "\n", encoding="utf-8")
    paths["json"], paths["txt"] = base.with_suffix(".json"), base.with_suffix(".txt")
    return bp, paths


# --------------------------------------------------------------------------- canvas / layer helpers
def draw_blueprint(canvas: Canvas, bp=None, style="chibi", dotted=True, colors=None) -> Canvas:
    """Draw the guide into a Canvas with palette colours nearest to the guide colours (rows dotted,
    landmark points solid). colors: optional {landmark_key: palette color} overrides."""
    bp = bp or get_blueprint(canvas.size, style)
    if tuple(bp["size"]) != canvas.size:
        raise PixelError(f"blueprint is {bp['size'][0]}x{bp['size'][1]}, canvas is {canvas.w}x{canvas.h}")
    w, h = canvas.size
    pal = canvas.palette
    colors = colors or {}

    def ci(k, rgb):
        return canvas.c(colors[k]) if k in colors else pal.nearest(rgb)

    for k, _, kind, rgb in LANDMARKS:
        v, c = bp[k], ci(k, rgb)
        if kind == "y":
            for x in range(0, w, 2 if dotted else 1):
                canvas.data[v, x] = c
        elif kind == "x":
            for y in range(0, h, 2 if dotted else 1):
                canvas.data[y, v] = c
        elif kind == "lr":
            canvas.data[v["y"], v["left"]] = c
            canvas.data[v["y"], v["right"]] = c
        elif kind == "pt":
            if k.startswith("eye"):
                ew, eh = bp["eye_size"]
                canvas.data[v[1]:v[1] + eh, v[0]:v[0] + ew] = c
            else:
                canvas.data[v[1], v[0]] = c
    return canvas


def add_blueprint_layer(stack, bp=None, style="chibi", name="blueprint", visible=False, index=0, **kw) -> Canvas:
    """Add the guide as a (hidden by default) bottom layer of a LayerStack; flatten() skips it
    while hidden. Returns the layer canvas."""
    cv = stack.add(name, visible=visible, index=index)
    draw_blueprint(cv, bp or get_blueprint((stack.w, stack.h), style), **kw)
    return cv

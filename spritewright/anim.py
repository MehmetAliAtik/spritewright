"""Animation helpers: easing, integer tweens, keyframes, oscillation and data-driven templates.

Everything produces INTEGER pixel offsets, so it plugs straight into the part rig (parts.py:
per-frame per-part dx/dy/flip/visible/swap) or moves a rectangular region in plain frame sprites.

Rounding rule: round half AWAY from zero (0.5 -> 1, -0.5 -> -1, 1.5 -> 2). The first and the
last keyframe of every segment are returned exactly (no float error), so a tween from A to B
always starts at A and ends at B.

Frame numbers in this module are 1-based (frame 1 = "<anim>1"), like rig frame names.

    import spritewright as ps
    from spritewright import anim
    anim.tween((0, 0), (0, -3), 5, "ease_out")            # [(0,0), (0,-1), (0,-2), (0,-3), (0,-3)]
    anim.keyframes([(1, 0), (4, -3), (6, 0)], 6)          # scalar track, holds outside keys
    anim.oscillate(8, amplitude=1, period=4)              # [0, 1, 0, -1, 0, 1, 0, -1]
    anim.rig_tween(rig, "jump", "body", (0, 0), (0, -4), start=1, end=4, easing="ease_out")
    anim.rig_oscillate(rig, "idle", "body", 1, period=4, axis="y", mode="abs")
    anim.apply_template(rig, "walk", frames=6, scale=1)  # -> report with notes (skipped parts)

Templates live in spritewright/templates/anim_templates.json (editable data, see that file's
"_doc"). fps/loop of a generated animation are stored with it (rig JSON: rig_animations[name]
.fps/.loop; Python rigs: rig.anim_meta, copied to sprite.extra["unity"] by build_sprite), and
unity-sheet / check read them from there.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from .canvas import GRID_CHARS
from .errors import PixelError
from .palette import Palette

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "anim_templates.json"


# --------------------------------------------------------------------------- rounding / easing
def round_half_away(v) -> int:
    """Round half away from zero: 0.5 -> 1, -0.5 -> -1, 2.4 -> 2 (never banker's rounding)."""
    return int(math.floor(abs(v) + 0.5)) * (1 if v >= 0 else -1)


def linear(t):
    return t


def ease_in(t):
    return t * t


def ease_out(t):
    return 1 - (1 - t) * (1 - t)


def ease_in_out(t):
    return 2 * t * t if t < 0.5 else 1 - 2 * (1 - t) * (1 - t)


def smoothstep(t):
    return t * t * (3 - 2 * t)


def ease_out_back(t, s=1.70158):
    """Overshoots past 1 (~10%) before settling: NOT monotonic (good for a strike / pop)."""
    if t <= 0 or t >= 1:
        return 0.0 if t <= 0 else 1.0
    u = t - 1
    return 1 + u * u * ((s + 1) * u + s)


def bounce(t):
    """Ease-out bounce (ball dropping onto the floor), stays within 0..1; NOT monotonic."""
    if t <= 0 or t >= 1:
        return 0.0 if t <= 0 else 1.0
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


EASINGS = {"linear": linear, "ease_in": ease_in, "ease_out": ease_out, "ease_in_out": ease_in_out,
           "smoothstep": smoothstep, "ease_out_back": ease_out_back, "bounce": bounce}


def easing_fn(e):
    if callable(e):
        return e
    key = str(e or "linear").lower().replace("-", "_")
    if key not in EASINGS:
        raise PixelError(f"unknown easing {e!r}; use one of: {', '.join(EASINGS)}")
    return EASINGS[key]


# --------------------------------------------------------------------------- tweens / keyframes
def _is_vec(v):
    return isinstance(v, (tuple, list))


def _lerp_int(a, b, e):
    return round_half_away(a + (b - a) * e)


def keyframes(keys, n_frames, easing="linear"):
    """Integer track over frames 1..n_frames from keys [(frame, value[, easing]), ...].
    value: int or (dx, dy). The optional per-key easing shapes the segment STARTING at that key
    (default: `easing`). Frames before the first / after the last key hold that key's value.
    Key frames are hit exactly. Returns a list of ints or (dx, dy) tuples."""
    if n_frames < 1:
        raise PixelError("keyframes: need at least 1 frame")
    if not keys:
        raise PixelError("keyframes: need at least one key")
    ks = []
    for k in keys:
        if len(k) not in (2, 3):
            raise PixelError(f"keyframe {k!r}: expected (frame, value) or (frame, value, easing)")
        f, v = int(k[0]), k[1]
        if not 1 <= f <= n_frames:
            raise PixelError(f"keyframe frame {f} outside 1..{n_frames}")
        if _is_vec(v):
            if len(v) != 2 or not all(isinstance(x, int) for x in v):
                raise PixelError(f"keyframe value {v!r}: expected integer (dx, dy)")
            v = (int(v[0]), int(v[1]))
        elif not isinstance(v, int):
            raise PixelError(f"keyframe value {v!r}: expected an integer pixel offset")
        ks.append((f, v, easing_fn(k[2] if len(k) == 3 else easing)))
    ks.sort(key=lambda k: k[0])
    vec = _is_vec(ks[0][1])
    if any(_is_vec(k[1]) != vec for k in ks):
        raise PixelError("keyframes: mix of scalar and (dx, dy) values")
    out = []
    for f in range(1, n_frames + 1):
        if f <= ks[0][0]:
            out.append(ks[0][1])
            continue
        if f >= ks[-1][0]:
            out.append(ks[-1][1])
            continue
        for (fa, va, ea), (fb, vb, _) in zip(ks, ks[1:]):
            if fa <= f <= fb:
                if f == fa:
                    out.append(va)
                elif f == fb:
                    out.append(vb)
                else:
                    e = ea((f - fa) / (fb - fa))
                    out.append((_lerp_int(va[0], vb[0], e), _lerp_int(va[1], vb[1], e)) if vec
                               else _lerp_int(va, vb, e))
                break
    return out


def tween(a, b, n_frames, easing="linear"):
    """n_frames integer values (or (dx,dy)) from a to b inclusive; first == a, last == b."""
    if n_frames == 1:
        return [b]
    return keyframes([(1, a), (n_frames, b)], n_frames, easing)


def oscillate(n_frames, amplitude, period, phase=0.0, mode="sine", offset=0):
    """Integer sine motion: value(i) = offset + amplitude * f(2*pi*(i/period + phase)), i = 0..n-1.
    mode: 'sine' (f = sin, -amp..amp), 'abs' (|sin|, 0..amp: bounce; use a negative amplitude for
    an upward hop on y), 'pos' (max(0, sin): rest half the time, e.g. breathing).
    phase is a fraction of the period (0.25 = quarter period = cosine)."""
    if period <= 0:
        raise PixelError(f"oscillate: period must be > 0, got {period}")
    fns = {"sine": math.sin, "abs": lambda x: abs(math.sin(x)), "pos": lambda x: max(0.0, math.sin(x))}
    if mode not in fns:
        raise PixelError(f"oscillate: mode must be one of {', '.join(fns)}, got {mode!r}")
    f = fns[mode]
    return [offset + round_half_away(amplitude * f(2 * math.pi * (i / period + phase)))
            for i in range(n_frames)]


def loop_warning(n_frames, period):
    """None if `period` divides n_frames (seamless loop), else a warning string."""
    k = n_frames / period
    if abs(k - round(k)) < 1e-9 and round(k) >= 1:
        return None
    return (f"oscillate: period {period:g} does not divide {n_frames} frames -> the loop will jump "
            f"at the seam (use period {', '.join(str(d) for d in range(1, n_frames + 1) if n_frames % d == 0)})")


# --------------------------------------------------------------------------- rig helpers
def _anim_frames(rig, anim, frames=None, duration=None):
    """Existing (copied) frame specs of a rig animation, created/extended to `frames` frames."""
    if anim in rig.animations:
        a = rig.animations[anim]
        specs = [copy.deepcopy(s) for s in a["frames"]]
        durs = list(a["durations"])
    else:
        specs, durs = [], []
    n = max(len(specs), frames or 0)
    if n == 0:
        raise PixelError(f"animation {anim!r} does not exist; give frames=N to create it")
    d = int(duration or (durs[-1] if durs else 150))
    while len(specs) < n:
        specs.append(copy.deepcopy(specs[-1]) if specs else {})
        durs.append(d)
    return specs, durs


def _commit(rig, anim, specs, durs):
    rig.animation(anim, specs, durs)  # re-validates (integer offsets, alts, part names)
    return rig.animations[anim]


def _put(specs, part, i, dx=None, dy=None, add=False):
    s = specs[i].setdefault(part, {})
    if isinstance(s, (tuple, list)):
        s = specs[i][part] = {"dx": s[0], "dy": s[1]}
    for k, v in (("dx", dx), ("dy", dy)):
        if v is None:
            continue
        s[k] = (s.get(k, 0) + int(v)) if add else int(v)


def rig_tween(rig, anim, part, a, b, start=1, end=None, easing="linear", frames=None, add=False,
              duration=None):
    """Move a rig part from offset a=(dx,dy) to b over frames start..end (1-based, inclusive).
    The animation is created (frames=N) or extended as needed. add=True adds to existing offsets."""
    rig.get(part)
    end = end or max(frames or 0, len(rig.animations.get(anim, {}).get("frames", [])), start)
    specs, durs = _anim_frames(rig, anim, max(frames or 0, end), duration)
    if not 1 <= start <= end <= len(specs):
        raise PixelError(f"tween frames {start}..{end} outside 1..{len(specs)}")
    for k, (dx, dy) in enumerate(tween(tuple(a), tuple(b), end - start + 1, easing)):
        _put(specs, part, start - 1 + k, dx, dy, add)
    return _commit(rig, anim, specs, durs)


def rig_keyframes(rig, anim, tracks, easing="linear", frames=None, add=False, duration=None):
    """Several parts at once: tracks = {part: [(frame, (dx, dy)[, easing]), ...]}.
    Each part is keyframed over all frames of the animation (holding outside its keys)."""
    for p in tracks:
        rig.get(p)
    need = max([frames or 0] + [int(k[0]) for ks in tracks.values() for k in ks])
    specs, durs = _anim_frames(rig, anim, need, duration)
    for p, ks in tracks.items():
        for i, (dx, dy) in enumerate(keyframes([(k[0], tuple(k[1]), *k[2:]) for k in ks], len(specs), easing)):
            _put(specs, p, i, dx, dy, add)
    return _commit(rig, anim, specs, durs)


def rig_oscillate(rig, anim, part, amplitude, period, phase=0.0, axis="y", mode="sine", frames=None,
                  add=True, loop=True, duration=None):
    """Sine motion of a part along x or y over the whole animation. Returns warnings (list of str):
    for a looping animation the period must divide the frame count, else the seam jumps."""
    rig.get(part)
    if axis not in ("x", "y"):
        raise PixelError(f"axis must be x or y, got {axis!r}")
    specs, durs = _anim_frames(rig, anim, frames, duration)
    vals = oscillate(len(specs), amplitude, period, phase, mode)
    for i, v in enumerate(vals):
        _put(specs, part, i, dx=v if axis == "x" else None, dy=v if axis == "y" else None, add=add)
    _commit(rig, anim, specs, durs)
    w = loop_warning(len(specs), period) if loop else None
    return [w] if w else []


# --------------------------------------------------------------------------- plain frame sprites
def move_region(cv, region, dx, dy):
    """Cut region (x,y,w,h) out of a canvas and paste it back offset by (dx,dy) (in place)."""
    x, y, w, h = region
    if dx == 0 and dy == 0:
        return cv
    chunk = cv.copy_region(x, y, w, h)
    cv.data[max(0, y):max(0, y + h), max(0, x):max(0, x + w)] = -1
    cv.stamp(chunk, x + dx, y + dy)
    return cv


def _frame_list(sprite, frames):
    if frames is None:
        return list(sprite.frames)
    if isinstance(frames, str):
        return sprite.frame_names(frames)
    return [sprite.frame(f).name for f in frames]


def region_offsets(sprite, region, offsets, frames=None):
    """Apply per-frame (dx,dy) offsets to a region of each listed frame (anim name / list / all)."""
    names = _frame_list(sprite, frames)
    if len(offsets) != len(names):
        raise PixelError(f"{len(offsets)} offsets for {len(names)} frames")
    for n, (dx, dy) in zip(names, offsets):
        move_region(sprite.frame(n), region, dx, dy)
    return names


def tween_region(sprite, region, a, b, frames=None, easing="linear", keys=None):
    """Move a rectangular region from offset a to b across frames (anim name, list or all).
    keys=[(frame, (dx,dy)[, easing]), ...] (1-based within those frames) replaces a/b."""
    names = _frame_list(sprite, frames)
    offs = keyframes(keys, len(names), easing) if keys else tween(tuple(a), tuple(b), len(names), easing)
    region_offsets(sprite, region, offs, names)
    return offs


def oscillate_region(sprite, region, amplitude, period, frames=None, phase=0.0, axis="y", mode="sine",
                     loop=True):
    """Sine motion of a region across frames. Returns (offsets, warnings)."""
    names = _frame_list(sprite, frames)
    vals = oscillate(len(names), amplitude, period, phase, mode)
    offs = [(v, 0) if axis == "x" else (0, v) for v in vals]
    region_offsets(sprite, region, offs, names)
    w = loop_warning(len(names), period) if loop else None
    return offs, ([w] if w else [])


# --------------------------------------------------------------------------- templates
def load_templates(path=None) -> dict:
    """The template library (dict with '_roles', '_hierarchy', 'templates')."""
    p = Path(path) if path else TEMPLATE_FILE
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        raise PixelError(f"template file not found: {p}") from None
    except json.JSONDecodeError as e:
        raise PixelError(f"{p}: invalid JSON at line {e.lineno} col {e.colno}: {e.msg}") from None
    if not isinstance(d.get("templates"), dict):
        raise PixelError(f"{p}: missing 'templates' object")
    return d


def get_template(name, lib=None) -> dict:
    lib = lib or load_templates()
    if name not in lib["templates"]:
        raise PixelError(f"no template {name!r}; templates: {', '.join(lib['templates'])}")
    return lib["templates"][name]


def resample(seq, n, loop=True):
    """Resample a per-frame list to n frames (phase sampling for loops, endpoint-exact otherwise)."""
    m = len(seq)
    if m == n:
        return list(seq)
    if m == 1 or n == 1:
        return [seq[0]] * n
    if loop:
        return [seq[int(math.floor(i * m / n + 1e-9)) % m] for i in range(n)]
    return [seq[round_half_away(i * (m - 1) / (n - 1))] for i in range(n)]


def _period(v, n):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(" ", "")
    if s == "N":
        return float(n)
    if s.startswith("N/"):
        return n / float(s[2:])
    raise PixelError(f"template wave period {v!r}: use a number, 'N' or 'N/k'")


def _track_values(spec, n, loop, scale, what, notes):
    """Template track spec -> n per-frame values. Numbers are scaled + rounded (dx/dy only)."""
    numeric = what in ("dx", "dy")
    if isinstance(spec, list):
        vals = resample(spec, n, loop)
        return [round_half_away(v * scale) if numeric and v is not None else v for v in vals]
    if isinstance(spec, dict) and "wave" in spec and numeric:
        w = spec["wave"]
        per = _period(w.get("period", "N"), n)
        if loop:
            msg = loop_warning(n, per)
            if msg:
                notes.append(msg)
        return oscillate(n, w.get("amp", 1) * scale, per, w.get("phase", 0.0), w.get("mode", "sine"))
    if isinstance(spec, dict) and "keys" in spec and numeric:
        ks = []
        for k in spec["keys"]:
            f = 1 + round_half_away(float(k[0]) * (n - 1))
            ks.append((f, round_half_away(k[1] * scale), *k[2:]))
        dedup = {}
        for k in ks:  # several normalized keys may land on the same frame for small n: last wins
            dedup[k[0]] = k
        return keyframes(list(dedup.values()), n, spec.get("ease", "linear"))
    raise PixelError(f"template track {what!r}: expected a list, {{'wave': ...}} or {{'keys': ...}}, got {spec!r}")


def _tracks_for(tpl, n):
    if "tables" in tpl:
        tabs = {int(k): v for k, v in tpl["tables"].items()}
        best = n if n in tabs else min(tabs, key=lambda m: (abs(m - n), -m))
        return tabs[best], best
    return tpl.get("tracks", {}), tpl.get("frames")


def role_map(rig, lib=None, roles=None):
    """{role: part name} for the rig, from the alias lists in the template library (+ overrides)."""
    lib = lib or load_templates()
    lower = {p.lower(): p for p in rig.parts}
    out = {}
    for role, aliases in lib.get("_roles", {}).items():
        for a in aliases:
            if a.lower() in lower:
                out[role] = lower[a.lower()]
                break
    for role, part in (roles or {}).items():
        rig.get(part)
        out[role] = part
    return out


def apply_template(rig, template, name=None, frames=None, scale=1.0, fps=None, loop=None, roles=None,
                   lib=None, duration=None, view=None):
    """Generate a starting animation on a rig from a template (data in anim_templates.json).

    template: template name (or a template dict). name: animation name (default = template name).
    frames: frame count (default: template's). scale: multiplies every pixel offset (rounded half
    away from zero). fps/loop override the template's. roles: {role: part} overrides of the
    alias-based part matching. Missing parts are skipped with a note. view: optional template view
    (e.g. 'front' for front-facing characters; replaces the tracks, keeps frames/fps/loop).
    Returns a report {name, frames, fps, loop, roles, notes}."""
    lib = lib or load_templates()
    tname = template if isinstance(template, str) else template.get("name", "custom")
    tpl = get_template(template, lib) if isinstance(template, str) else template
    if view:
        views = tpl.get("views", {})
        if view not in views:
            raise PixelError(f"template {tname!r} has no view {view!r}; views: {', '.join(views) or 'none'}")
        tpl = {**{k: v for k, v in tpl.items() if k not in ("tracks", "tables")}, **views[view]}
    name = name or tname
    n = int(frames or tpl.get("frames") or 4)
    if n < 1:
        raise PixelError("template frames must be >= 1")
    fps = float(fps or tpl.get("fps") or 8)
    loop = bool(tpl.get("loop", True) if loop is None else loop)
    tracks, base_n = _tracks_for(tpl, n)
    notes = []
    if base_n and base_n != n:
        notes.append(f"{tname}: template drawn for {base_n} frames, resampled to {n}")
    rmap = role_map(rig, lib, roles)
    hier = lib.get("_hierarchy", {})
    own = {}      # role -> {"dx": [...], "dy": [...]}
    props = {}    # role -> {prop: [...]}
    skipped = []
    for role, tr in tracks.items():
        if role not in ("root", "*") and role not in rmap:
            skipped.append(role)
            continue
        for prop, spec in tr.items():
            if prop not in ("dx", "dy", "flip_h", "flip_v", "visible", "swap"):
                raise PixelError(f"template {tname!r} role {role!r}: unknown property {prop!r}")
            vals = _track_values(spec, n, loop, scale, prop, notes)
            (own if prop in ("dx", "dy") else props).setdefault(role, {})[prop] = vals
    if skipped:
        al = lib.get("_roles", {})
        notes.append("skipped (no matching part): " + ", ".join(
            f"{r} [{'/'.join(al.get(r, [r]))}]" for r in skipped))

    def total(role, axis, i, depth=0):
        v = own.get(role, {}).get(axis, [0] * n)[i]
        par = hier.get(role)
        if par and depth < 16:
            v += total(par, axis, i, depth + 1)
        return v

    part_role = {p: r for r, p in rmap.items()}
    specs = []
    flash_missing = set()
    for i in range(n):
        fr = {}
        for p in rig.parts:
            role = part_role.get(p)
            s = {}
            dx = (total(role, "dx", i) if role else 0) + own.get("root", {}).get("dx", [0] * n)[i]
            dy = (total(role, "dy", i) if role else 0) + own.get("root", {}).get("dy", [0] * n)[i]
            if dx:
                s["dx"] = dx
            if dy:
                s["dy"] = dy
            for src in ("*", role):
                for prop, vals in props.get(src, {}).items() if src else ():
                    v = vals[i]
                    if prop == "swap":
                        if not v:
                            continue
                        cands = v if isinstance(v, list) else str(v).split("|")
                        alt = next((c for c in cands if c in rig.parts[p].alts), None)
                        if alt:
                            s["swap"] = alt
                        elif src != "*":
                            flash_missing.add(f"{p} has no alt {'/'.join(cands)}")
                        else:
                            flash_missing.add("*:" + "/".join(cands))
                    elif prop == "visible":
                        if v is not None and not v:
                            s["visible"] = False
                    elif v:
                        s[prop] = True
            if s:
                fr[p] = s
        specs.append(fr)
    for m in sorted(flash_missing):
        if m.startswith("*:"):
            alts = m[2:]
            if not any(c in pt.alts for pt in rig.parts.values() for c in alts.split("/")):
                notes.append(f"no part has alt {alts}: swap/flash skipped")
        else:
            notes.append(f"{m}: swap skipped")
    if name in rig.animations:
        notes.append(f"animation {name!r} replaced")
    dur = int(duration or round_half_away(1000 / fps))
    rig.animation(name, specs, [dur] * n)
    rig.__dict__.setdefault("anim_meta", {})[name] = {"fps": fps, "loop": loop}
    return {"name": name, "template": tname + (f"/{view}" if view else ""), "frames": n, "fps": fps, "loop": loop, "scale": scale,
            "roles": rmap, "notes": notes}


def build_sprite(rig, **kw):
    """rig.build(**kw) + fps/loop of template animations copied to sprite.extra['unity'] so that
    unity-sheet / check honour them for .py rigs too."""
    sp = rig.build(**kw)
    meta = getattr(rig, "anim_meta", None)
    if meta:
        u = sp.extra.setdefault("unity", {})
        u.setdefault("animations", {}).update({k: dict(v) for k, v in meta.items()})
    return sp


# --------------------------------------------------------------------------- rig JSON I/O
def load_rig_json(path):
    """Read a rig JSON (grid sprite file with 'parts'). Returns (dict, Rig) without baking frames."""
    from .parts import Rig
    from .sprite import _parse_chars, resolve_source
    p = resolve_source(path)
    if p.suffix.lower() != ".json":
        raise PixelError(f"{p}: rig editing needs a rig .json (for .py rigs use the Python API "
                         f"spritewright.anim.apply_template + build_sprite, or rig_to_dict to save one)")
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PixelError(f"{p}: invalid JSON at line {e.lineno} col {e.colno}: {e.msg}") from None
    if "parts" not in d:
        raise PixelError(f"{p.name}: not a part rig (no 'parts'); use --region for frame sprites")
    pal = Palette.load(d["palette"], base_dir=p.parent) if "palette" in d else None
    if pal is None:
        raise PixelError(f"{p.name}: rig JSON needs a 'palette'")
    lut = _parse_chars(d.get("chars", {}), pal, p.name)
    rig = Rig.from_dict(d, pal, lut, p.name)
    for an, ad in d.get("rig_animations", {}).items():
        meta = {k: ad[k] for k in ("fps", "loop") if k in ad}
        if meta:
            rig.__dict__.setdefault("anim_meta", {})[an] = meta
    return d, rig, p


def _spec_json(s):
    s = {k: v for k, v in s.items() if not (k in ("dx", "dy") and v == 0)}
    if set(s) <= {"dx", "dy"} and s:
        return [s.get("dx", 0), s.get("dy", 0)]
    return s


def anim_to_json(rig, name):
    a = rig.animations[name]
    out = {}
    durs = a["durations"]
    if len(set(durs)) == 1:
        out["duration"] = durs[0]
    else:
        out["durations"] = durs
    meta = getattr(rig, "anim_meta", {}).get(name, {})
    out.update({k: meta[k] for k in ("fps", "loop") if k in meta})
    out["frames"] = [{p: _spec_json(s) for p, s in fr.items() if _spec_json(s) != {}} for fr in a["frames"]]
    return out


def save_rig_json(d, rig, path, names=None):
    """Write rig animations (all, or `names`) into the rig JSON dict d and save it to path."""
    ra = d.setdefault("rig_animations", {})
    for n in (names or list(rig.animations)):
        ra[n] = anim_to_json(rig, n)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    return p


def rig_to_dict(rig, base_dir=None, crop=True, outline=None, connectivity=8):
    """Serialize a Python Rig as rig JSON (parts cropped to the union bbox of base + alts).
    outline: color (name/index) for 'rig_outline'. Note: flips happen inside the cropped box."""
    import numpy as np
    used = set()
    for p in rig.parts.values():
        for cv in [p.canvas, *p.alts.values()]:
            used |= {int(v) for v in np.unique(cv.data) if v >= 0}
    used = sorted(used)
    if len(used) > len(GRID_CHARS):
        raise PixelError(f"rig uses {len(used)} colors; grid format supports {len(GRID_CHARS)}")
    ch = {idx: GRID_CHARS[k] for k, idx in enumerate(used)}
    d = {"name": rig.name, "width": rig.w, "height": rig.h, "palette": rig.palette.spec(base_dir),
         "chars": {ch[i]: (rig.palette.name_of(i) or i) for i in used}, "parts": {}}
    for name, p in rig.parts.items():
        cvs = [p.canvas, *p.alts.values()]
        x0, y0, w, h = 0, 0, p.canvas.w, p.canvas.h
        if crop:
            boxes = [c.bbox() for c in cvs if c.bbox()]
            if boxes:
                x0 = min(b[0] for b in boxes)
                y0 = min(b[1] for b in boxes)
                w = max(b[0] + b[2] for b in boxes) - x0
                h = max(b[1] + b[3] for b in boxes) - y0

        def rows(cv):
            return ["".join("." if v < 0 else ch[int(v)] for v in r[x0:x0 + w]) for r in cv.data[y0:y0 + h]]
        pd = {"z": p.z, "x": p.x + x0, "y": p.y + y0, "rows": rows(p.canvas)}
        if p.alts:
            pd["alts"] = {an: rows(acv) for an, acv in p.alts.items()}
        d["parts"][name] = pd
    if rig.animations:
        d["rig_animations"] = {n: anim_to_json(rig, n) for n in rig.animations}
    if outline is not None:
        d["rig_outline"] = {"color": outline, "connectivity": connectivity}
    return d

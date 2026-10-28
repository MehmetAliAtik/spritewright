# Python API + make script skeleton

`import spritewright as ps`; `from spritewright import anim`.

## make_<char>.py skeleton (game layout: outputs/<Game>/characters/<Char>/source/)

```python
"""<Char> (<Game>): one line design note. Cell = card cell, pivot = feet."""
import json
from pathlib import Path
import spritewright as ps      # importable when installed; `build` / `run` add a checkout to sys.path
from spritewright import anim
HERE = Path(__file__).resolve().parent

C = {"o": "outline", "k": "skin", "K": "skin_shadow", "h": "hair", "g": "foliage"}   # roles from `context`
HEAD = ["..hhhh..", ".hhhhhh.", ...]               # every row exactly the same length

def build_rig():
    pal = ps.Palette.load(HERE / "<Char>_palette.json")   # written by char-new (game palette subset)
    rig = ps.Rig(32, 32, pal, name="<char>")
    rig.part("arm_l", z=0).draw_grid(12, 19, ARM, FAR)  # far limbs first (low z), darker colours
    rig.part("leg_l", z=1).draw_grid(11, 24, LEG["stand"], FAR)
    rig.part("leg_r", z=2).draw_grid(11, 24, LEG["stand"], C)
    rig.part("body", z=3).draw_grid(12, 18, BODY, C)
    rig.part("head", z=4).draw_grid(9, 5, HEAD, C)
    rig.part("arm_r", z=5).draw_grid(13, 19, ARM, C)
    for pose, g in LEG.items():                         # pose swaps: blank alt + redraw
        rig.alt("leg_r", pose, copy=False).draw_grid(11, 24, g, C)
    rig.alt("head", "blink").draw_grid(19, 12, ["k"], C)   # alt = copy of base; overdraw details
    return rig

def walk(rig):
    frames = [{"leg_r": {"swap": "fwd"}, "body": (0, 0), "head": (0, 0)}, ...]
    rig.animation("walk", frames, duration=100)

if __name__ == "__main__":
    rig = build_rig(); walk(rig)
    d = anim.rig_to_dict(rig, base_dir=HERE, outline="outline", connectivity=8)
    (HERE / "<char>.json").write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
```
`build` runs this script, then exports `<char>.json`. Keep animation edits in the script (re-running it
overwrites the json). Parent-chain note: parts never move together on their own — every part you want
to bob must get the same offset in the frame spec (body, head, arms ...), there is no parenting.
`rig.alt(part, name, copy=False)` starts blank (pose swaps); default `copy=True` starts as a copy of
the base drawing (small edits like blink). Declare fps with `rig.anim_meta[name] = {"fps": 8}` /
`rig_animations.<name>.fps` in json: with non-uniform `durations` the declared fps is reported and the
durations are kept.

## Palette
`ps.Palette.load(name|path|dict, base_dir=None)`, `.copy(name)`, `.set_name(name, idx)`, `.save(path)`,
`.index(color)`, `.nearest(rgb)`, `.darker(c, steps)`, `.lighter(c, steps)`, `.auto_ramp(c, down, up)`;
`ps.generate_ramp(base_hex, steps=5, hue_shift=14.0, palette=None)`.

## Canvas `ps.Canvas(w, h, palette, strict=True)` (colour = index, role name or in-palette hex; methods chain)
`pixel(x,y,c)`, `pixels(pts,c)`, `line(x0,y0,x1,y1,c)`, `polyline(pts,c)`, `rect(x,y,w,h,c,fill=True)`,
`ellipse(x,y,w,h,c,fill=True)`, `circle(cx,cy,r,c,fill=True)`, `polygon(pts,c,fill=True)`,
`flood_fill(x,y,c,connectivity=4)`, `draw_grid(x,y,rows,chars)`, `dither(region,c1,c2=None,pattern="bayer4",level=0.5)`,
`gradient(region,c_from,c_to=None,direction="v",ramp=None)`, `stamp(src,x,y,flip_h,flip_v,rotate)`,
`copy_region(x,y,w,h)`, `paste_region(sx,sy,w,h,dx,dy)`, `shift(dx,dy,wrap)`, `flip_h()`, `flip_v()`,
`rotate(deg)`, `mirror("lr")`, `recolor({a:b}, region)`, `outline(color=None, selective=False,
connectivity=8, steps=1, ramps=None, inside=False)`, `shade(region, ramp=[dark..light], light="top-left",
depth=1)`, `symmetry("x"|"y"|"xy"|None)`, `with cv.mirrored("x"):`, `mask(c)`, `shape_mask(...)`,
`opaque_mask()`, `bbox()`, `colors_used()`, `orphans()`, `clean(remove=True)`, `ascii()`, `save(path, scale)`.
region = None | (x,y,w,h) | bool mask | colour. 64x64+: shapes + `symmetry("x")`, not hand grids.

## Layers / Rig / anim
- `st = ps.LayerStack(w, h, pal)`; `st.add(name, opacity=1.0, blend="normal"|"multiply")` → Canvas; `st.flatten()`.
- `rig = ps.Rig(w, h, pal, name=)`; `rig.part(name, z=None, x=0, y=0)` → full-size Canvas (sprite coords);
  `rig.alt(part, alt, copy=True)`; `rig.animation(name, [{part: (dx,dy) | {"dx","dy","swap","visible",
  "flip_h","flip_v","z"}}, ...], duration=ms|[ms...])` (integers only); `rig.build(outline=None, ...)` → Sprite.
- `anim.apply_template(rig, "walk", name=None, frames=None, scale=1.0, fps=None, loop=None, roles={role: part},
  view=None)` → report (read notes); `anim.rig_tween(...)`, `anim.rig_keyframes(rig, anim, {part: [(f, (dx,dy))]})`,
  `anim.rig_oscillate(rig, anim, part, amp, period, phase=0, axis="y", mode="sine")`, `anim.build_sprite(rig)`,
  `anim.rig_to_dict(rig, base_dir, outline, connectivity)`, `anim.load_rig_json(path)`, `anim.save_rig_json(d, rig, path)`.

## Sprite / export / pipeline
- `ps.load_sprite(src)`, `ps.Sprite(w, h, pal, name=)`, `.new_frame`, `.add_frame`, `.frame(key)`, `.loop_check(anim)`, `.save(path)`.
- `ps.render`, `ps.sheet`, `ps.gif(src, path, anim, fps, scale)`, `ps.apng`, `ps.contact_sheet(src, path, scale=4,
  rows=None, max_width=1024)` (src may be an atlas/sheet json), `ps.inspect(src, path, region, frame, zoom)`,
  `ps.onion`, `ps.diff`, `ps.output_dir(project)`.
- `ps.build(game, char, "all", mode="final"|"draft")` → report {status, animations, summary, issues, paths};
  `ps.context(game, char)` → lines; `ps.check(src, atlas=None, game=None, write=True)`;
  `ps.char_export(...)`, `ps.char_new(...)`, `ps.game_new(...)`, `ps.load_style(game)`, `ps.unity_sheet(...)`;
  `ps.get_blueprint(32, "chibi")`, `ps.import_image(...)`, `ps.depixelize(...)`.

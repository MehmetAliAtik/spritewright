# Animation templates and motion helpers

Templates turn a part rig (see [sprite-grid-format.md](sprite-grid-format.md#rig-json)) into a ready
animation by moving its parts. They are a starting point: refine the result with alternate drawings,
`tween`, `oscillate` or hand-written frame specs. Practical tips for walk cycles, idles and attacks are in
[skill/reference/animation.md](../skill/reference/animation.md).

## Bundled templates

| Template | Frames | FPS | Loop | Motion |
|---|---|---|---|---|
| `idle` | 4 | 6 | on | breathing: body (with head/arms) dips 1 px; blink on the last frame if a `blink` alt exists |
| `walk` | 6 or 8 | 10 | on | legs alternate forward/back and lift on the pass, body dips after contact, arms counter-swing |
| `run` | 6 | 12 | on | bigger leg/arm swing (2 px), airborne pass frames lift the whole character |
| `jump` | 6 | 10 | off | crouch, launch (ease_out), apex, fall (ease_in), landing squash; legs tuck, arms rise |
| `attack` | 6 | 12 | off | anticipation (wind back), strike (weapon extends), recovery |
| `hurt` | 4 | 10 | off | knockback, head whips back, flash via a `hurt` / `flash` alt if present |
| `death` | 6 | 8 | off | recoil, collapse over the legs, flicker frame, ends lying still |

`walk` and `run` also have a `front` view for front-facing characters (legs lift alternately, no
forward/back movement): `--view front`.

```sh
spritewright templates                      # one-line list
spritewright templates --verbose            # descriptions, views, easings, role aliases
spritewright templates --show walk          # one template's data as JSON
```

## Applying a template

```sh
spritewright anim-apply rig.json walk                          # writes back into rig.json
spritewright anim-apply rig.json walk --frames 8 --fps 12 -o rig_walk.json
spritewright anim-apply rig.json attack --name slash --scale 2 --map weapon=staff   # rig has a "staff" part
spritewright anim-apply rig.json walk --view front
```

```python
from spritewright import anim
report = anim.apply_template(rig, "walk", frames=6, scale=1.0, view=None, roles={"weapon": "staff"})  # rig: a ps.Rig
print(report["notes"])      # e.g. parts that were skipped
```

- `--frames N` resamples the template (walk has dedicated 6- and 8-frame tables).
- `--scale` multiplies every pixel offset; results are rounded half away from zero.
- `--fps`, `--no-loop` override the template defaults; the values are stored in
  `rig_animations.<name>.fps` / `.loop` and used by `unity-sheet`, `check` and `build`.
- `--templates FILE` uses your own template file instead of the bundled one.

### Roles

Templates move *roles*; each role is matched to a rig part by name:

| Role | Part names accepted |
|---|---|
| `head` | `head` |
| `body` | `body`, `torso`, `chest` |
| `arm_l`, `arm_r` | `arm_l` / `arm_left` / `left_arm` / `hand_l` (and the right-hand equivalents) |
| `leg_l`, `leg_r` | `leg_l` / `leg_left` / `left_leg` / `foot_l` (and the right-hand equivalents) |
| `legs` | `legs`, `feet` |
| `weapon` | `weapon`, `accessory`, `sword`, `staff`, `item`, `tool` |

Roles without a matching part are skipped and reported in the notes ("skipped (no matching part)").
Rename the part or map it: `--map head=helmet,weapon=staff`. The exact alias list is printed by
`spritewright templates --verbose`.

## Template file format

The bundled templates live in `spritewright/templates/anim_templates.json`. A custom file uses the same
structure:

```json
{
  "_roles": {"body": ["body", "torso"], "head": ["head", "eyes"]},
  "_hierarchy": {"head": "body"},
  "templates": {
    "bob": {
      "description": "simple bob",
      "frames": 4, "fps": 6, "loop": true,
      "tracks": {
        "body": {"dy": [0, 1, 1, 0]},
        "head": {"dy": {"wave": {"amp": 1, "period": "N", "phase": 0.25, "mode": "sine"}},
                 "swap": [null, null, null, "blink"]}
      }
    }
  }
}
```

`spritewright anim-apply examples/sprites/blob_rig.json bob --templates my_templates.json -o blob_bob.json`
applies it to the example blob (its `eyes` part plays the `head` role).

- `templates` = `{name: template}`; each template has `description`, `frames`, `fps`, `loop` and either
  `tracks` or `tables`.
- `tracks` = `{role: {property: spec}}`; or `tables` = `{frame count: tracks}` for templates with
  dedicated tables per length.
- Properties: `dx`, `dy` (px, y down), `flip_h`, `flip_v`, `visible`, `swap` (alt name; `"a|b"` = the
  first existing alt; `null` = base drawing).
- Specs: a per-frame list (resampled when the frame count differs); `{"wave": {amp, period, phase, mode}}`
  with period `"N"`, `"N/2"` or a number and mode `sine`, `abs` or `pos`; or
  `{"keys": [[t, value, easing?], ...], "ease": "linear"}` with `t` from 0 to 1.
- Special roles: `root` (offset added to every part) and `*` (visible / swap / flip for every part).
- `_hierarchy`: child role -> parent role. Unlike hand-written rig frames, a child also moves by its
  parent's template offsets, so the head and arms ride the body and the weapon follows the right arm.
- `views`: `{view name: {description, tracks | tables}}` replaces the tracks for that view.

## Tween and oscillate

Both write integer offsets into a rig part (`--part`) or move a rectangular region of plain frame sprites
(`-r x,y,w,h`), and write back to the source unless `-o` is given. Frame numbers are 1-based.

```sh
spritewright tween rig.json --anim jump --part body --from=0,0 --to=0,-4 --ease ease_out --frames 6
spritewright tween rig.json --anim wave --part arm_r --keys "1:0,0;3:0,-3:ease_out;6:0,0"
spritewright oscillate rig.json --anim idle --part body --amp 1 --period 4 --mode abs
spritewright oscillate examples/sprites/slime.json --anim idle -r 2,4,12,10 --amp 1 --period 2 -o slime_bob.json
```

- Easings: `linear`, `ease_in`, `ease_out`, `ease_in_out`, `smoothstep`, `ease_out_back` (overshoots and
  settles), `bounce`.
- Rounding: halves round away from zero (0.5 -> 1, -0.5 -> -1); the first and last value of every key
  segment are kept exactly.
- `oscillate` modes: `sine`, `abs` (|sin|, a bounce) and `pos` (positive half-wave, breathing). In a
  looping animation the period should divide the frame count, otherwise the loop seam jumps (a warning is
  printed; `--no-loop` silences it).
- Values starting with `-` need `=`: `--to=0,-4`.

Python equivalents: `anim.tween`, `anim.keyframes`, `anim.oscillate`, `anim.rig_tween`,
`anim.rig_keyframes`, `anim.rig_oscillate`, `anim.tween_region`, `anim.oscillate_region`.

## Checking an animation

`spritewright check SRC` reports `anim.motion` (frames nearly identical), `anim.foot_drift` (the planted
foot moved), `anim.size_drift` (a part grew), `anim.loop_seam` (last -> first jump too big) and
`anim.orphans`. `spritewright frame SRC loopcheck --anim walk` prints the loop difference;
`gif`, `contact` and `preview` (onion skin) show the motion.

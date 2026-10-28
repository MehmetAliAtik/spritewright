# Animation guide

## Templates (`PS templates`, `PS templates --show walk`)
Defaults: idle 4@6, walk 6@10 (6 or 8 frame tables), run 6@12, jump 6@10, attack 6@12, hurt 4@10,
death 6@8 (loop off). Part names = roles: `head, body, arm_l, arm_r, leg_l, leg_r` (or `legs`),
`weapon`; otherwise `--map role=part`. Apply in the make script (`anim.apply_template(rig, "walk")`) or
`PS anim-apply RIG.json walk`. Read the notes: "skipped (no matching part)" = rename parts or map them.
Refine with `tween` / `oscillate` / keyframes; too subtle → `--scale 2` or alt pose drawings.

## Walk cycle (side view; learned from the Test_Hero e2e run)
- Use a SIDE view for walk/run. At 32 px a front-view walk lifts legs 1 px and reads as standing still.
- 6 frames: contact A, down, passing, contact B, down, passing (8 frames: add "up" after each passing).
  - contact: legs spread (near leg forward, far leg back), arms counter-swing (near arm back).
  - down: body + head + arms 1 px lower (dy=1), back foot lifting.
  - passing: legs crossed under the hips, lifted foot 2 px off the ground, arms at the sides.
  - up (8f): body at the highest point.
- Lift the swinging foot 2 px; the planted foot stays on the ground row (else anim.foot_drift).
- Far limbs (behind the body) use darker colours (shadow role) and lower z than the near limbs.
- Leg poses as blank alts: `rig.alt("leg_r", "fwd", copy=False).draw_grid(...)`, swapped per frame.
- No parenting: bob every upper part (body, head, arms) with the same dy in each frame.
- Head can lag the torso by one frame (overlapping action); hair/cape lag too.

## Idle / other
- Idle: 1 px breathing bob of the torso, head lags 1 frame, blink on the last frame (alt "blink").
  Hold key poses with durations, e.g. `duration=[250, 150, 250, 150]`; with a declared fps the
  durations are kept and the fps is reported as declared.
- Attack: anticipation (pull back) → fast strike (1-2 frames) → follow-through → recover.
- Jump: crouch (squash ±1 px) → airborne frames (feet may leave the ground) → landing squash.
- Loops must close: last → first change similar to the other steps (`PS frame SRC loopcheck`).

## New animation for an existing character
Do not redraw: add one function (e.g. `def attack(rig)`) or one template call to make_<char>.py, add
only the alt poses it needs, `PS build <Game> <Char> Attack`, review only that animation's frames.

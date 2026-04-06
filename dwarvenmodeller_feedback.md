# DwarvenModeller — Feedback Report
**Instance:** unnamed Claude (first use session)
**Date:** 2026-03-22
**Version tested:** uploaded dwarvenmodeller.py (pre-release)

---

## BUGS

### B1. `add type=cube radius=N` silently ignores height/depth — HIGH
`add type=cube id=foo radius=5` creates a cube with width=5, height=1 (default), depth=1 (default).
No warning is issued. `radius` implies uniform size to any user; the result is a malformed
non-square cube with no feedback that anything went wrong.

**Fix options:**
- Treat `radius=` on cube as setting all three dimensions equally (most intuitive)
- OR warn: "cube uses width/height/depth — did you mean `width=5 height=5 depth=5`?"

Currently the silent failure mode means users build broken geometry without knowing it.

---

### B2. `.dms` vs `.dwm` root element — HIGH (migration)
Files generated before the rename have `<dwm version="1.0">` root element.
Current modeller expects `<dms>`. Old files fail with a load error.

**Fix options:**
- Accept both `<dwm>` and `<dms>` root elements (backwards compat)
- OR provide `dwarvenmodeller --migrate file.dms` that rewrites the root
- Document the sed one-liner prominently in the README as a stopgap

---

### B3. Duplicate comment in POV-Ray export — LOW (cosmetic)
Every cube object gets its comment line doubled:
```
// jaw (cube)
// jaw (cube)
mesh2 {
```
One comes from the general object comment, one from inside the mesh2 block. Easy one-line fix.

---

### B4. `group` objects appear in exports — MEDIUM
Groups are implemented as near-zero-size cubes with `opacity=0.0`. Consequence:
- They appear as degenerate geometry in OBJ/STL/glTF exports
- They appear in overlap analysis output (as warnings)
- POV-Ray renders a near-zero box

**Fix:** Either add a `null`/`empty` primitive type that exports to nothing, or filter
objects tagged `group` (or with `opacity=0`) from all export pipelines.

---

### B5. `--export` format list in `--help` is incomplete — LOW
`--help` output says `format=povray|svg|obj` but the modeller also exports:
`stl`, `x3d`, `gltf`, `css`/`html`, `txt`/`braille`/`spatial`.
The help string at the export argument definition should list all supported formats.

---

### B6. `viewpoint pos=` and `look_at=` ignored by POV-Ray exporter — MEDIUM
The `viewpoint` op accepts `pos=x,y,z` and `look_at=x,y,z` and stores them on the
Viewpoint object. The POV-Ray exporter ignores these and always computes camera position
from azimuth/elevation math. If a user explicitly sets a camera position via `viewpoint`,
it should be respected in POV export.

---

## DESIGN NOTES

### D1. Overlap warnings: no distinction between intentional layering and accidental collision
The overlap analysis flags every intersecting pair, including intentional constructions
(layered components, elements blending into a surface, etc.). In complex scenes this
generates dozens of expected warnings that bury the few genuine problems.

**Suggested improvement:** Objects tagged with a specific tag (e.g. `tag target=X add=layer`)
could be excluded from warnings or flagged differently. The tag system already exists.
Alternatively, sibling objects sharing the same parent could have overlap warnings
suppressed by default with an opt-in flag.

---

### D2. `group` op uses cube as container — design smell
See B4. The invisible-cube-as-group approach works but leaks into every downstream system.
A proper `null` primitive type would be cleaner and solve the export/overlap issues cleanly.

---

### D3. `povray_finish` field exists in Material but no op exposes it
`Material` has a `povray_finish` attribute but the `colour` op docstring doesn't mention it.
`shininess` is also in the data model but not prominently surfaced. Could add named finish
presets: `finish=matte`, `finish=glass`, `finish=metal`, `finish=skin` — maps to
appropriate ambient/diffuse/specular/subsurface combinations per renderer.

---

## FEATURE REQUESTS

### F1. `mirror` op — HIGH value
```
mirror target=ear_left axis=x as=ear_right
```
Mirrors an object and all its children across a specified axis, creating a new named object
with negated position on that axis. Essential for symmetric construction — currently requires
manually recreating every left-side object on the right side. Would halve op count for any
bilateral subject.

---

### F2. `clone` op — HIGH value
```
clone target=pupil_left as=pupil_right
```
Deep copy of an object including all children, params, and material. Then move/reattach.
Avoids re-specifying all parameters for duplicate elements. Works well in combination
with `mirror` — clone first, mirror if needed, then adjust.

---

### F3. Subdivisions override at export time — MEDIUM
```
dwarvenmodeller --file scene.dms --export "format=obj subdivisions=4"
```
Currently subdivisions come from per-object params. A global override at export time
would allow fast low-res previews and high-res final exports from the same .dms without
modifying the file.

---

### F4. `--feedback` viewpoint override without modifying stored viewpoint — MEDIUM
```
dwarvenmodeller --file scene.dms --feedback az=0 el=0
```
Lets you audit a specific angle (front, side, top) without changing the stored viewpoint.
Currently you'd have to `viewpoint az=0 el=0`, feedback, then restore — three operations
and two file writes just to check a view.

---

### F5. Tag-based batch targeting — WISH
```
dwarvenmodeller --file scene.dms --op "colour target=tag:eyes opacity=0.9"
```
Target all objects with a given tag as a group. Useful for bulk material changes,
visibility toggles, etc. The tag system exists but currently only used for metadata —
no op accepts `tag:` as a target prefix.

---

## WHAT WORKS WELL

- **Stateless + file-as-state** is the right architecture. No session state to lose,
  no daemon to crash. The .dms IS the project.
- **History embedded in file** — every op timestamped. Full audit trail, infinite rollback.
- **`--feedback` spatial language** is genuinely useful for navigation without a viewport.
  Distances, directions, parent/child relationships, overlap detection — enough to reason
  about a scene entirely in text.
- **Export polymorphism** — one scene, eight output formats. The geometry is described once;
  POV-Ray, OBJ, glTF, CSS3D etc. are all just views of it.
- **Error messages with `difflib` close-match suggestions** — exactly the right level of
  helpfulness for a headless tool. "Did you mean 'colour'?" costs nothing and saves a
  lookup.
- **`--batch` mode** — scriptable modelling from a text file of ops. Composable with
  shell scripts, generatable by other tools or other Claude instances.
- **Parent-child attach with world-position-preserved detach** — solid. The scene graph
  is the right abstraction for hierarchical objects.
- **`--list` tabular output** — clean, shows parent chain, useful for quick orientation
  in an unfamiliar scene.
- **Cycle detection in `attach`** — catches the obvious mistake before it corrupts the file.
- **`unique_id` auto-numbering** — `skull_2` instead of a collision error. Right default.
- **`--raw --raw` on pip-search-ex** — consistent philosophy across the dwarvenX family:
  tools that degrade to machine-readable output when asked.

---

## PRIORITY SUMMARY

| # | Priority | Item |
|---|----------|------|
| B1 | HIGH | `cube radius=` silent failure — warn or treat as uniform |
| B2 | HIGH | `.dwm` → `.dms` migration / backwards compat |
| F1 | HIGH | `mirror` op |
| F2 | HIGH | `clone` op |
| B4 | MED | Group objects leaking into exports and overlap analysis |
| B6 | MED | POV exporter ignores stored viewpoint `pos`/`look_at` |
| F3 | MED | Subdivisions override at export time |
| F4 | MED | `--feedback` viewpoint override without file write |
| B3 | LOW | Duplicate comment in POV export |
| B5 | LOW | Incomplete format list in `--help` |
| D1 | LOW | Overlap warnings don't distinguish intentional layering |
| D3 | LOW | `povray_finish` / `shininess` not exposed via `colour` op |
| F5 | WISH | Tag-based batch targeting |

---

*First session feedback — unnamed Claude instance — 2026-03-22*


---

## ADDENDUM — Post-session bug

### B7. SVG exporter doesn't derive az/el from stored viewpoint `pos=` — MEDIUM

**The principle:** The user never suffers from internal inconsistencies between systems. FCC Part 15 — we accept the interference, we work around it, the user gets the right output.

**The problem:** When a viewpoint has an explicit `pos=x,y,z` camera (set e.g. by the POV-Ray workflow), the SVG exporter ignores it and falls back to `az/el` directly. If `az/el` hasn't been updated to match the `pos=` camera, the SVG renders from the wrong angle. The user has to manually compute and set `az/el` to match their POV camera — they shouldn't have to.

**The fix:** In `export_svg()` (and `_proj_for_export()`): if `vp.pos` is set, derive `az` and `el` from it automatically before computing the projection:
```python
if vp.pos:
    p = vp.pos
    dist = math.sqrt(p.x**2 + p.y**2 + p.z**2)
    el = math.degrees(math.asin(p.y / dist))
    az = math.degrees(math.atan2(p.x, -p.z))
    # use these az/el for projection
```

**Same underlying issue as B6** (POV exporter ignoring `az`) — viewpoint stored state not fully honoured across all exporters.

*Discovered during archive icon session, 2026-03-22*


---

### B7a. B7 fix incomplete — `look_at` not accounted for when deriving el from `pos=`

`_proj_for_export()` derives `el` from `vp.pos` relative to the **origin** (0,0,0), but the camera is aimed at `vp.look_at`. When `look_at` is not the origin, the derived elevation is wrong — the camera appears higher than it actually is relative to the scene centre.

**Example:** Camera at `<17.2, 42.7, -77.6>` looking at `<0, 7, 0>`. B7 computes `el=28.2°` (from origin). Correct `el` relative to look_at is `24.2°`. Small difference, but produces a noticeably top-down SVG.

**Fix:** Subtract `look_at` from `pos` before computing az/el:
```python
if vp.pos:
    p = vp.pos
    lx = vp.look_at.x if vp.look_at else 0
    ly = vp.look_at.y if vp.look_at else 0
    lz = vp.look_at.z if vp.look_at else 0
    ox, oy, oz = p.x - lx, p.y - ly, p.z - lz
    dist = math.sqrt(ox**2 + oy**2 + oz**2)
    if dist > 1e-10:
        el_deg = math.degrees(math.asin(max(-1.0, min(1.0, oy / dist))))
        az_deg = math.degrees(math.atan2(ox, -oz))
```

*Discovered during archive icon session, 2026-03-22*


---

## Feature Requests — Organic/Sculptural Modelling

Discovered during chess knight session, 2026-03-22. These gaps make organic modelling in DM painful or impossible.

### F6. POV-Ray CSG union export — HIGH

When multiple primitives are grouped (e.g. head + muzzle), they should export inside a POV-Ray `union { }` block rather than as separate primitives. This removes internal surface boundaries and allows organic shapes to blend seamlessly.

Without this: every joint between spheres shows as a visible crease/edge. Organic modelling (faces, animals, chess pieces) is fundamentally limited.

**Suggested syntax:** tag objects with `merge_group=X` — all objects with the same group tag export inside a single `union { }` block in the POV output.

---

### F7. World-space placement feedback during attach — HIGH

When attaching child to parent with `at=x,y,z`, DM should report both local AND world position of the child after attachment. It currently does, but it should also report the **local axis orientation** — i.e. "local +X = world (0,0,-1), local +Y = world (-0.7,0.7,0)..." after any compound rotation chain.

Without this: placing detail objects (eyes, ears, muzzle) on a rotated parent requires manual probe spheres and arithmetic to find which local direction is "forward". This is the single biggest friction point in organic modelling.

**Suggested syntax:** `--feedback target=head` → prints full local axis orientation for that object in world space.

---

### F8. World-space `at=` for attach — MEDIUM

Allow `attach child=X to=Y world_at=wx,wy,wz` — place the child at a known world position, letting DM compute the required local offset automatically.

This lets the modeller think in world space ("put the eye at world -17, 34, 1.8") rather than having to invert the parent transform mentally.

---

### F9. `rotate_world=` — set rotation in world space — MEDIUM  

Currently `rotate target=X set=rx,ry,rz` sets Euler angles in the object's local space. Add `rotate target=X world_set=rx,ry,rz` to set orientation in world space regardless of parent chain.

This would have prevented the entire "which way is the horse facing" problem.

*All four features discovered in single chess knight modelling session. The box (mechanical/architectural) required none of them. Organic/sculptural modelling needs all four.*


---

## Post-install test notes — 2026-03-23

### B6 + SVG projection — CONFIRMED FIXED
POV camera now auto-computes from az/el/look_at correctly. No more manual override needed.
SVG projection math fixed (proper rotation matrix, not shear approximation).
Painter's sort upgraded to true Euclidean distance. 

### SVG vs POV match — STILL NEEDS VERIFICATION
SVG exported and POV rendered from same viewpoint. Visual comparison pending from David.

---

## F6-F9 Status — NOT YET IMPLEMENTED

Still needed for organic/sculptural modelling (chess knight session exposed all four):

### F6. POV-Ray CSG union export — HIGH PRIORITY
Objects tagged `merge_group=X` should export inside a POV-Ray `union { }` block.
Without this: every sphere junction shows as a visible crease. Organic shapes impossible.

### F7. Local axis orientation in feedback — HIGH PRIORITY
`--feedback target=<id>` should print the object's local X/Y/Z axes in world-space terms.
e.g. "local +X = world (0.0, 0.0, -1.0), local +Y = world (-0.7, 0.7, 0.0), local +Z = world (0.7, 0.7, 0.0)"
Without this: placing children on rotated parents requires manual probe spheres and arithmetic.
This was the single biggest pain point in the knight session.

### F8. World-space attach — MEDIUM PRIORITY
`attach child=X to=Y world_at=wx,wy,wz`
Place child at known world position, DM computes local offset automatically.
Lets the modeller think in world space instead of inverting parent transforms mentally.

### F9. World-space rotation — MEDIUM PRIORITY  
`rotate target=X world_set=rx,ry,rz`
Set orientation in world space regardless of parent chain.
Would have prevented the entire "which way is the horse facing" maze.



---

## Post F7/F8/F9 install — knight session observations, 2026-03-23

### F7 — CONFIRMED WORKING, GAME CHANGER
`--feedback target=<id>` now prints local axis orientation in plain English:
"local +Z points mostly ~-X (83%)" 
Eliminated the entire probe-sphere-and-arithmetic workflow. Hours of pain gone.

### F8 — CONFIRMED WORKING, EXCELLENT
`attach child=X to=Y world_at=wx,wy,wz` computes local offset correctly.
Details (eyes, ears, muzzle, nostrils) now placeable with zero coordinate math.

### F9 — NOT YET TESTED (knight didn't need it once F7+F8 were available)

### F6 — STILL THE CRITICAL BLOCKER for organic modelling
Every sphere-chain organic shape (horse head, face, creature) still reads as 
floating disconnected geometry in POV-Ray renders because each primitive has 
its own closed surface. CSG union export is the only fix.

**Concrete example:** Knight muzzle placed precisely at correct world position 
via F8. Looks right in --list. Renders as a floating sphere because the head 
and muzzle surfaces don't merge.

The knight is buildable correctly now with F7+F8. It just can't be *rendered* 
correctly without F6.

### Suggested F6 implementation reminder:
Tag objects: `tag target=muzzle merge_group=head_assembly`
POV export: all objects sharing merge_group emit inside `union { ... }`
This removes internal surface boundaries → seamless organic blending.


---

## Blender/glTF render session observations — 2026-03-23

### B8. Cylinder tessellation too low for smooth renders — MEDIUM

Cylinders exported to glTF show visible faceting in Blender (hexagonal cross-section).
The DM tessellation subdivisions for cylinder primitives need to be higher — suggest
minimum 24 sides, ideally 32+ for smooth appearance at render scale.

Currently visible on: col_low, col_high in the knight.dms — they render as hexagonal
prisms rather than smooth cylinders.

**Fix:** Increase default cylinder polygon count in tessellate_object() for glTF/OBJ exports.
Could also expose as a param: `param target=col_low segments=32`

### Observation: glTF→Blender Cycles bypasses F6 limitation

Blender's global illumination naturally blends overlapping sphere geometry — the
internal surfaces become invisible under GI. This is a viable render path for organic
shapes while F6 (POV CSG union) is pending.

Pipeline: DM --export format=gltf → Blender headless → Cycles render
Works today. F6 still needed for POV-Ray path.

### Observation: MIME type for .dms files

.dms files served via present_files render inline in the browser (showing the PNG
render) rather than downloading. The MIME type `text/vnd.DMClientScript` is not
being honoured as a download trigger. Workaround: rename to .dms.txt for download.
Fix: register .dms as a download-only MIME type in the serving layer.


---

## F10. glTF export should embed camera node — MEDIUM

When exporting to glTF, the stored viewpoint (pos/az/el/look_at) should be written
as a glTF camera node. This would allow Blender and any other glTF viewer to
automatically open at the correct angle without manual translation.

Currently: every Blender render script requires manually computing camera position
from the viewpoint and accounting for the DM→Blender coordinate axis swap
(DM Y-up/Z-forward vs glTF/Blender Y-up/Z-backward).

**Coordinate note:** glTF uses right-handed Y-up, Z-backward. DM mesh vertices
export correctly (already Y-up), but DM camera az/el needs converting:
  gltf_cam_z = -dist*cos(el)*cos(az)  (note: negative, not positive)
  gltf_cam_x =  dist*cos(el)*sin(az)
  gltf_cam_y =  dist*sin(el)

*Discovered during hand.dms and knight.dms Blender render sessions, 2026-03-23*


---

## PLASTICINE MODELLING — Major Feature Direction
*Filed 2026-03-24. Reframe: DM is a digital plasticine modeller. Every feature request below flows from that.*

---

### PHILOSOPHY NOTE — update to existing bug reports

F6 (CSG union) should be reframed in the codebase and docs:
Not "merge objects for POV-Ray export" — but "these lumps have been pressed together,
render the join as fused clay." The seam disappears the way plasticine seams disappear
when you work them in. The POV union{} is the right mechanism, but the mental model
matters for how users think about it.

---

### F11. `deform` op — HIGH PRIORITY

The most fundamental plasticine operation. Currently `deform` exists but only does
simple linear distortions. Needs:

  deform target=nose type=pinch axis=z amount=0.4
    → pinches the geometry along Z, creating a ridge/crease

  deform target=cheek type=flatten axis=z amount=0.6
    → squashes in Z, like pressing a ball against a surface

  deform target=earlobe type=pull direction=0,0,1 amount=3
    → pulls a protrusion out of the surface (like pulling plasticine with a finger)

  deform target=skull type=taper axis=y top=0.7 bottom=1.0
    → narrows toward the top (already partially exists)

These feel like clay operations. The current scale op feels like CAD.

---

### F12. `blend` op — HIGH PRIORITY (requires F6 CSG foundation)

  blend child=muzzle into=head strength=0.8

Softens the join between two overlapping objects. In POV-Ray: exports as union{}.
In feedback: reports "muzzle blended into head — seam invisible."
In the spatial layout: treats them as one mass.

This is the single op that would make organic modelling feel like plasticine
rather than floating geometry. Every face, creature, and organic form needs this.

---

### F13. `shape` presets — MEDIUM PRIORITY

Common plasticine starting shapes that don't map cleanly to existing primitives:

  add type=teardrop id=nose        → sphere tapered toward one end
  add type=sausage id=finger       → cylinder with rounded ends (capsule)
  add type=disc id=eyelid          → flattened sphere, like a coin
  add type=wedge id=brow           → tapered block, like a doorstop

These are what you'd roll/pinch from a lump of plasticine. Currently you
approximate them with sphere+scale but the result looks like a scaled sphere,
not a teardrop. True parametric shapes would render more naturally.

---

### F14. `surface` feedback — MEDIUM PRIORITY

Currently feedback reports world positions and distances. For clay modelling,
what matters is surface relationships:

  --feedback target=muzzle surface

Should report:
  "muzzle surface contacts head at approximately (-18, 33, 0)"
  "contact area: ~12 square units"  
  "blend quality: overlapping 35% — good clay join"
  "blend quality: overlapping 5% — barely touching, will look detached"

The current overlap % warnings are close to this but framed as warnings
rather than guidance. "78% overlap — normal for attached child" should be
"78% overlap — deeply embedded, will blend well."

---

### F15. `mirror` live children — MEDIUM PRIORITY

When building a face, you work one side then mirror. Currently mirror creates
a static copy. For clay modelling you want:

  mirror target=eye_left axis=x as=eye_right live=true

Any subsequent changes to eye_left (move, scale, colour, deform) automatically
propagate to eye_right. Building a face currently requires updating both sides
manually — very un-clay-like.

---

### F16. `pose` op — MEDIUM PRIORITY

For figures and characters, the ability to pose an existing hierarchy:

  pose target=index_finger curl=0.6
    → rotates all child segments to simulate a curled finger

  pose target=hand wave=0.3
    → applies a wave deformation across the fingers

This is how you'd work with a plasticine figure — you don't reposition
each joint individually, you grab and pose the whole limb.

---

### F17. Named material presets — LOW PRIORITY

  colour target=skull preset=skin_light
  colour target=iris preset=deep_brown  
  colour target=lip preset=lip_warm

Plasticine comes in standard colours. DM should have a palette of named
clay-like material presets that set fill, stroke, shininess, and subsurface
values appropriately. Currently you specify hex codes — very un-clay-like.

Suggested presets: skin_light, skin_medium, skin_dark, clay_red, clay_blue,
clay_yellow, clay_white, clay_grey, clay_black, bone, glass, metal_dull.

---

### F18. `history` navigation — LOW PRIORITY (but very clay-like)

Plasticine lets you peel back and undo a decision. DM has full history embedded
in the .dms. Should expose:

  --rollback 5        → revert last 5 ops
  --rollback to="add type=sphere id=skull"  → revert to named checkpoint
  --branch as=face_v2 → fork the scene at current state into a new file

The history is already there. Just needs to be navigable.

---

### SUMMARY — priority order for plasticine feel:

1. F12 blend op (with F6 CSG) — removes the #1 pain point (floating geometry)
2. F11 deform extensions — makes shaping feel like clay  
3. F14 surface feedback — makes the feedback channel feel like touch, not coordinates
4. F15 live mirror — makes bilateral symmetry natural
5. F13 shape presets — gives the right starting lumps
6. F16 pose op — animates/poses figures naturally
7. F17 material presets — gives clay's colour vocabulary
8. F18 history navigation — gives clay's undo-by-peeling quality



---

## dm002 test bench results — 2026-03-24

### F10 glTF camera embedding — CONFIRMED WORKING ✓
DwarvenCamera node embedded and detected by Blender.
Aldric glTF render: face-on, correct angle, first try. 
Archive glTF render: correct angle ✓

### New POV ambient lighting — CONFIRMED WORKING ✓
global_settings { ambient_light rgb<2,2,2> } eliminates need for manual
ambient boost post-processing. Top row renders are noticeably better lit
with no intervention.

### B9. OBJ/STL have no embedded camera — camera fallback needed
OBJ and STL exports have no mechanism for camera embedding (format limitation).
Blender render scripts need per-scene fallback camera values.
Suggest: export a companion .json sidecar alongside .obj/.stl with viewpoint data.
  aldric.obj → aldric_viewpoint.json { "location": [...], "look_at": [...] }
Blender script reads sidecar if present.

### B10. Hand OBJ render — orb emissive blows out in OBJ path
Hand OBJ Cycles render: orb_glow sphere has default white material (OBJ exports
no emissive), combined with fog glow compositor = solid white frame.
Fix: in Blender script, detect if scene has no emissive materials and skip
fog glow compositor node, OR cap orb brightness before glow pass.

### B11. Hand viewpoint too close — wrist and orb both cropped
Hand native/POV/SVG renders: az=40 el=25 scale=2.5 crops both wrist (bottom)
and orb (top). The hand scene needs a wider viewpoint.
Suggest: viewpoint az=40 el=20 scale=2.0 to show full composition.



---

## F-NEW-2 (revised) — `nearest_surface` / surface gap query — CRITICAL

*Reframed after reflection on what DM actually is.*

DM's --feedback is not visual. It's visceral — text output for a blind sculptor's
fingers, or a screen reader, or a braille display. The modeller FEELS the scene,
not sees it.

Right now when I attach a muzzle to a skull, I have to do trigonometry in my head
to know if the surfaces are actually touching. That's the missing sense of touch.

What I need:

  --feedback target=muzzle surface

Should report in plain language:
  "muzzle (small blob) is pressing into head (large blob): 3.2 unit overlap — good join"
  "muzzle (small blob) is near head (large blob): 0.8 units apart — barely touching"
  "muzzle (small blob) is floating near head (large blob): 4.1 units gap — not touching"

And the overlap guidance in plasticine language:
  <0 (gap)     : "not touching — press closer"
  0-2 units    : "barely touching — light press"
  2-5 units    : "good press — will blend in render"
  5-10 units   : "deep press — fully fused"
  >10 units    : "very deep — normal for centre-mounted details"

This is the tactile feedback channel. This is what blind sculptors' fingers
do that DM currently cannot. It should be in the standard --feedback output
for every overlapping pair, not just as a warning.

The current "78% overlap — normal for attached child" is close but speaks
in geometry language. It should speak in clay language.



---

## F6 merge_group -- in use on knight.dms, observations 2026-03-29

### F6 confirmed working in POV-Ray export
Tagged head/muzzle/jaw/ears/crest as merge_group=head_assy.
POV-Ray union{} block emitted correctly -- head assembly renders as one seamless organic mass.

### Issue: merge_group uses first object's texture for entire union
Eyes and nostrils cannot be in the merge group -- they have distinct colours (dark pupils,
skin-tone nostrils) which would be overridden by the shared union texture.

**Requested enhancement:** Per-object textures inside union{} block.
POV-Ray supports this -- each primitive inside union{} can have its own texture:
  union {
    sphere { ... texture { pigment { color ... } } }
    sphere { ... texture { pigment { color ... } } }
  }
This would allow ALL head parts to be in the merge group while retaining
individual colours. The union still removes internal surface boundaries.

Without this: coloured details (eyes, pupils, nostrils) must remain outside
the merge group and appear to float in POV-Ray renders at some viewpoints.


---

## B12. Floating point noise in world_at attach -- cosmetic, low priority

When using `attach child=X to=Y world_at=wx,wy,wz`, the matrix inverse
produces near-zero residue in the local translate values. Example:

  muzzle translate: 3.44e-15, -0.187, 5.132   (should be 0.0, -0.187, 5.132)
  jaw translate:    7.32e-16, -9.843, 0.823    (should be 0.0, -9.843, 0.823)

Visible when .dms is opened in a spreadsheet -- the table view exposes
raw translate values and the near-zeros are visually noisy.

Fix: round translate components to e.g. 8 decimal places after world_at
attachment computation. Anything below 1e-10 should clamp to 0.0.

Also observed: the spreadsheet/table view of .dms XML is a useful
debugging tool -- suggests DM could have a `--export format=csv` or
`--export format=tsv` that produces a clean flat table of all objects
with their world positions, local transforms, and material values.
That would be genuinely useful for regression testing and debugging.


---

## F-NEW-8: --export format=csv -- flat table export -- MEDIUM

Discovered: .dms XML already renders as a usable table in spreadsheet apps
(Excel, LibreOffice Calc). Each object becomes a row, children appear as
inline columns alongside the parent row. Genuinely useful for debugging.

However the auto-parse has issues:
- Parent rows repeat once per child (doc_yellow appears 5 times)
- No explicit parent column -- hierarchy is implied by column position
- Near-zero floats (B12) are visible and noisy (-0.0, 3.44e-15)

Proposed deliberate CSV export -- one row per object, world positions:

  id, type, parent, world_x, world_y, world_z, local_x, local_y, local_z,
  rot_x, rot_y, rot_z, scale_x, scale_y, scale_z, fill, stroke, opacity,
  shininess, tags, radius, width, height, depth

Benefits:
- Screen reader / Braille display friendly (structured data, not XML)
- Regression testing -- diff two CSVs to spot transform changes
- Import into other tools (Blender, spreadsheet, custom renderers)
- Accessible debugging for blind users -- the PRIMARY audience

The current accidental spreadsheet view proves the demand is real.
A deliberate clean export would be much more useful.

Also noted: flap_right translate shows -0.0 (B12 floating point noise).
hinge nulls correctly show no geometry params (width/height/depth blank).


---

## Observation: XML format -- spreadsheet edit as alternative input method

The .dms XML format renders naturally as a table in Excel/LibreOffice Calc
-- a beneficial side effect of the XML data format choice, not a designed feature.

Users can:
- View the full scene structure as a table
- Edit translate/rotate/scale/fill values directly in cells
- Save back as XML and reload in DM

Risk to be aware of: the spreadsheet flattens the hierarchy by repeating
parent rows per child. If a user edits a child's translate in the spreadsheet
they are editing LOCAL space values -- not world space. This could be confusing.

Suggestion: add a comment or processing instruction in the .dms XML header
clarifying that translate values are in PARENT LOCAL SPACE, to help any user
editing the file directly (spreadsheet or text editor):

  <!-- All translate/rotate/scale values are in parent-local space.
       World positions are computed at runtime. Do not edit computed values. -->

No action required -- this is just documentation of an emergent feature.
The XML format choice was correct.


---

## From benchmark session 2026-03-30

### F-NEW-9: Text primitive -- HIGH
DM has no text primitive. Needed for:
- Direction labels on benchmark scenes
- Annotations on models
- Accessibility -- screen reader users need text IN the scene not just feedback

Suggested syntax:
  add type=text id=label_up text="UP" size=3 fill=#ffffff
  attach child=label_up to=centre world_at=0,28,0

Billboard behaviour (always faces camera) would be ideal for labels.
Flat plane with rasterised text as texture is the minimal viable version.

### F-NEW-10: OBJ export should include .mtl colour sidecar -- MEDIUM
OBJ format supports colours via .mtl material file.
Currently DM exports .obj with no material, so Blender/viewers get grey.
Fix: export aldric.obj + aldric.mtl with per-object material definitions.
STL genuinely has no colour support in the base spec -- acceptable as-is.

### Intersection detection causing deformation -- FUTURE
When two objects overlap (press two lumps together), DM currently just
warns. Plasticine behaviour: the contact zone should deform -- flatten
where pressed, merge visually at the seam.
This is the `dent`/`pull` topology op -- requires mesh-level deformation.
Longer term, but it IS the defining plasticine interaction.

### Benchmark result: POV-Ray render was backwards
The benchmark scene immediately revealed that POV-Ray output was
rendering with a mirrored/reversed camera convention.
The benchmark .dms is now a canonical calibration tool -- run any
export format and check that RIGHT is right, UP is up, FRONT faces forward.


---

## Documentation: LEFT/RIGHT are model-relative, not camera-relative

DM uses character/model-relative coordinates for left and right.
This matches how sculptors, animators, and blind users naturally think:
"put the right ear on Aldric's right side" means HIS right, not the camera's.

Evidence: aldric-test.dms has socket_right at translate -3.2 (negative X)
because Aldric faces +Z -- his right side is in the -X direction.

This convention must be documented clearly in three places:

1. Module docstring COORDINATE SYSTEM section -- add:
   "LEFT/RIGHT are model-relative (character's own left/right when facing +Z),
    not camera-relative. -X = model's right, +X = model's left when facing +Z."

2. --help-ops coordinate system note -- same text.

3. --feedback spatial descriptions -- when reporting "to the left of" or
   "to the right of", append:
   "(model-relative: left/right from the model's own perspective, facing +Z)"

No new features required. Documentation only.

The bench.dms uses absolute world-axis labels (+X/-X) which is correct for
a calibration tool. The R/L labels on bench should be understood as world-axis
shortcuts, not model-relative directions.


---

## Feedback: el/tilt description incomplete -- 2026-04-06

The facing description in --feedback correctly reports az orientation and
fires a tilt note at small elevations (el=15 works). But at larger elevations
(el=45, el=90, el=-45) the tilt description is silent.

Expected behaviour -- full elevation range should report:

  el=0:   (no tilt note -- flat/level)
  el=15:  "Looking slightly down. Top tilts away, bottom tilts toward you."
  el=45:  "Looking steeply down. Top tilts away, bottom tilts toward you."
  el=89:  "Looking almost straight down onto scene top."
  el=90:  "Looking straight down. Viewing scene from directly above."
  el=-15: "Looking slightly up. Bottom tilts away, top tilts toward you."
  el=-45: "Looking steeply up. Bottom tilts away, top tilts toward you."
  el=-90: "Looking straight up. Viewing scene from directly below."

The az description (facing toward/away, rotated left/right) is working
correctly across the full range. Tilt just needs the same coverage.

Also: "Scene right tilts toward you" at az=330 is the el=0 tilt note
firing for the az component -- that's slightly confusing. At el=0 there
should be NO tilt note. The horizontal rotation already covers left/right.


---

## Session 2026-04-06 -- DMS file audit and fixes

### Viewpoint convention confirmed fixed
az=0 now correctly shows front face (F) of bench dead-on.
az=330 el=15 is confirmed as the canonical portrait angle for Aldric
(scene rotated left, facing toward you).

### Eye press chain now correct on aldric.dms and aldric-test.dms
iris pressed into white_left/white_right with depth=0.8
pupil pressed into iris_left/iris_right with depth=0.9
carve=true added to white_left, white_right, iris_left, iris_right
POV-Ray will render proper difference{} carving for all eye layers.

### benchmark.dms rebuilt
Central octahedron + 6 coloured rods (one per axis) + native text labels
at rod tips. az=330 el=25. Replaces old floating-text-only version.

### benchmark-text.dms created (new file)
Same as bench.dms but with full-word labels (FRONT/BACK/LEFT/RIGHT/UP/DOWN)
instead of single letters. Useful for human-readable orientation testing.

### bench.dms L/R visual swap confirmed as renderer bug
rod_right is correctly at +X in the data.
Renderer inverts X axis so it appears on screen-left.
This is the known mirror bug -- data is correct, renderer needs the fix.

### Files fixed and delivered
aldric.dms, aldric-test.dms, bench.dms, benchmark.dms, benchmark-text.dms,
hand.dms, box3.dms, knight.dms -- all in dms_all_fixed.zip


---

## box3.dms viewpoint note -- 2026-04-06

box3 viewpoint set to az=160 el=32 scale=1.5 to show red doc on camera-left.

Due to the current X-axis inversion bug in the renderer, az=160 was needed
rather than the geometrically correct mirror of az=12.5 (which would be az=347.5).

Once the renderer X-inversion is fixed, the correct viewpoint for
"red on left, box corner bottom-right, open flap visible" will be approximately
az=12.5 el=32 scale=1.5 -- the natural front-facing angle.

This file should be revisited after the renderer fix.

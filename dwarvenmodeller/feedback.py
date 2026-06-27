"""DwarvenModeller -- feedback: generate_feedback, ansi_render, text_layout."""
from __future__ import annotations
import math
from .constants import *
from .math_utils import *
from .scene import *
from .primitives import *
from .ops import *
# ═════════════════════════════════════════════════════════════════════════════




__all__ = ['generate_feedback', 'text_layout_summary']

def generate_feedback(scene, tty=True, target_id=None, mode='full', view='top'):
    """
    Generate scene feedback.
    tty=True      - includes ANSI half-block render (for terminal)
    tty=False     - prose spatial layout (for screen readers / piped output)
    target_id     - if set, prints detailed local axis orientation for that object (F7)
    mode='full'   - full verbose output (default)
    mode='skeleton' - compact table: id | parent | world_pos | radius | dist_to_parent
    view='top'    - spatial layout projected top-down (default)
    view='side'   - spatial layout projected from the side (XY plane)
    view='front'  - spatial layout projected from the front (XZ plane)
    """
    lines = []
    sep   = '═' * 60
    lines.append(sep)
    lines.append('  DwarvenModeller - Scene Report')
    lines.append(sep)

    all_objs = scene.all_objects()

    if not all_objs:
        lines += ['', 'The scene is empty.',
                  '', 'To begin:', '  --op "add type=sphere id=myobject radius=10"', '']
        return '\n'.join(lines)

    vp = scene.active_viewpoint()

    # -- Skeleton mode: compact table -----------------------------------------
    if mode == 'skeleton':
        import math as _math
        lines += ['',
                  f'Scene: {len(all_objs)} objects. yaw={vp.az}° pitch={vp.el}° zoom={round(vp.scale,2)}',
                  '']
        col_w = [24, 16, 28, 8, 16]
        header = (f"{'id':<{col_w[0]}} {'parent':<{col_w[1]}} "
                  f"{'world_pos':<{col_w[2]}} {'radius':<{col_w[3]}} dist_to_parent")
        lines.append(header)
        lines.append('-' * (sum(col_w) + 4))
        for obj in all_objs:
            wp     = scene.world_pos(obj)
            wr     = scene.world_radius(obj)
            par    = scene.find_parent(obj.id)
            par_id = par.id if par else '-'
            if par:
                pp  = scene.world_pos(par)
                dx  = wp.x-pp.x; dy = wp.y-pp.y; dz = wp.z-pp.z
                dist = f"{_math.sqrt(dx*dx+dy*dy+dz*dz):.2f}"
            else:
                dist = '-'
            pos_str = f"({wp.x:.1f},{wp.y:.1f},{wp.z:.1f})"
            lines.append(f"{obj.id:<{col_w[0]}} {par_id:<{col_w[1]}} "
                         f"{pos_str:<{col_w[2]}} {wr:<{col_w[3]}.2f} {dist}")
        lines.append('')
        return '\n'.join(lines)

    import math as _math
    _az_r = _math.radians(vp.az)
    # THE COMPASS RULE: +Z is North. YOU are fixed. Sphere rotates.
    _facing  = _math.cos(_az_r)   # >0: faces away, <0: faces you
    _lateral = _math.sin(_az_r)   # >0: rotated right, <0: rotated left

    # Express viewpoint in sculptor/turntable vocabulary, not CAD camera terms.
    # turn = az (spin the sphere), tilt = el (tip the sphere), zoom = scale

    # LINE 1: Facing -- how directly is the scene facing you vs away?
    _face_deg = round(abs(_math.degrees(_math.acos(max(-1.0, min(1.0, _facing))))))
    if _facing > 0.98:
        _line_facing = 'Facing away (0°).'
    elif _facing < -0.98:
        _line_facing = 'Facing toward you (180°).'
    elif _facing > 0:
        _line_facing = f'Facing mostly away ({_face_deg}° from full away).'
    else:
        _line_facing = f'Facing mostly toward you ({180 - _face_deg}° from full toward).'

    # LINE 2: Rotation (yaw/az) -- how far rotated left or right?
    _az_norm = vp.az % 360
    if _az_norm > 180: _az_norm = _az_norm - 360   # signed: negative=left, positive=right
    if abs(_az_norm) < 2:
        _line_az = 'No yaw (not rotated left or right).'
    elif _az_norm > 0:
        _line_az = f'Yaw right {_az_norm:.0f}°.'
    else:
        _line_az = f'Yaw left {abs(_az_norm):.0f}°.'

    # LINE 3: Tilt (el) -- how far tilted forward (down) or back (up)?
    _el_raw = vp.el % 360
    _el = _el_raw if _el_raw <= 180 else _el_raw - 360   # signed: +ve=tilt down, -ve=tilt up
    if abs(_el) < 2:
        _line_el = 'Not pitched forward or back.'
    elif _el > 0:
        _line_el = f'Pitched forward (down) {_el:.0f}°.'
    else:
        _line_el = f'Pitched back (up) {abs(_el):.0f}°.'

    # LINE 4: Roll -- how far rolled clockwise or anticlockwise?
    _roll_r = vp.roll % 360
    if _roll_r > 180: _roll_r = _roll_r - 360   # signed: +ve=clockwise, -ve=anticlockwise
    if abs(_roll_r) < 2:
        _line_roll = None   # no roll, omit the line entirely
    elif _roll_r > 0:
        _line_roll = f'Rolled clockwise {_roll_r:.0f}°.'
    else:
        _line_roll = f'Rolled anticlockwise {abs(_roll_r):.0f}°.'

    _zoom_str   = f'{round(vp.scale, 4)}'
    _dist_str   = f'Scene is {round(vp.scale, 4)} units away.'
    _centre_str = (f', centred on ({vp.look_at.x:.1f}, {vp.look_at.y:.1f}, {vp.look_at.z:.1f})'
                   if vp.look_at else '')

    _desc_lines = [f'  {_dist_str}', f'  {_line_facing}', f'  {_line_az}', f'  {_line_el}']
    if _line_roll:
        _desc_lines.append(f'  {_line_roll}')

    lines += ['',
              f'Scene contains {len(all_objs)} object{"s" if len(all_objs)!=1 else ""}.',
              f'Scene: yaw={vp.az}°  pitch={vp.el}°  distance={_zoom_str}{_centre_str}{"  roll="+str(round(vp.roll,1))+"°" if vp.roll else ""}.',
              ] + _desc_lines + ['']

    # -- Object tree ----------------------------------------------------------─
    lines.append('-- Objects --')
    lines.append('  (Felt positions use the compass rule: see --help-ops for orientation guide)')
    lines.append('')

    def _felt_position(wp):
        """Describe world position in sculptor's felt space -- relative to current viewpoint.
        No camera language. Just: where would your hands find this in the clay?
        Projects world coords through az/el rotation and describes in near/far/left/right/up/down terms.
        Left/right depends on facing direction:
          - Scene faces away (back toward you): their left = your left (no mirror)
          - Scene faces toward you (face to face): their left = your right (mirror)
        """
        import math as _m
        _az = _m.radians(vp.az); _el = _m.radians(vp.el)
        rx  =  wp.x*_m.cos(_az) - wp.z*_m.sin(_az)
        rz  =  wp.x*_m.sin(_az) + wp.z*_m.cos(_az)
        ry2 =  wp.y*_m.cos(_el) - rz*_m.sin(_el)
        rz2 =  wp.y*_m.sin(_el) + rz*_m.cos(_el)

        # When scene faces toward you, left/right are mirrored vs when facing away.
        # BUT _view() already returns +rx which is consistent across all azimuths.
        # No additional mirror needed -- raw rx matches what the render shows.
        facing = _m.cos(_az)  # kept for near/far depth sign

        # Threshold scales with scene extent
        positions = [scene.world_pos(o) for o in all_objs]
        if positions:
            xs = [p.x for p in positions]; ys = [p.y for p in positions]; zs = [p.z for p in positions]
            scene_r = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs), 1.0) / 2
        else:
            scene_r = 10.0
        thr = scene_r * 0.15

        def _lr(v):
            if abs(v) < thr: return None
            return 'to your right' if v > 0 else 'to your left'
        def _ud(v):
            if abs(v) < thr: return None
            return 'above centre' if v > 0 else 'below centre'
        def _nd(v):
            if abs(v) < thr: return None
            return 'near side' if v > 0 else 'far side'

        parts = [p for p in [_ud(ry2), _lr(rx if _facing > 0 else -rx), _nd(rz2)] if p]
        if not parts:
            return 'at centre of scene'
        return ', '.join(parts)

    def describe(obj, depth=0, parent_M=None):
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M
        wp      = world_M * Vec3(0, 0, 0)
        sc      = obj.transform.scale
        rot     = obj.transform.rotate
        r       = obj.get_param('radius', obj.get_param('width', 1.0))
        eff_r   = scene.world_radius(obj)
        mat     = obj.material
        indent  = '  ' * depth
        tag_str = f" [{', '.join(obj.tags)}]" if obj.tags else ""

        lines.append(f"{indent}{obj.id}  ({obj.type}){tag_str}")
        if sc.x == sc.y == sc.z:
            lines.append(f"{indent}  Size: {_size_description(eff_r)}, radius {eff_r:.2f}.")
        else:
            lines.append(f"{indent}  Size: stretched (x={sc.x:.2f}, y={sc.y:.2f}, z={sc.z:.2f} × r={r:.2f}).")
        lines.append(f"{indent}  World position: {_format_pos(wp)}.")
        lines.append(f"{indent}  Felt position: {_felt_position(wp)}.")
        if rot.x or rot.y or rot.z:
            lines.append(f"{indent}  Rotated: x={Transform.display_angle(rot.x):.1f}°, y={Transform.display_angle(rot.y):.1f}°, z={Transform.display_angle(rot.z):.1f}°.")
        opacity_str = f", {int(mat.opacity*100)}% opaque" if mat.opacity < 1.0 else ""
        lines.append(f"{indent}  Color: fill {mat.fill}{opacity_str}.")
        if obj.attach_point:
            _ap = scene.find_parent(obj.id)
            _apn = f" to '{_ap.id}'" if _ap else ''
            lines.append(f"{indent}  Attached{_apn} at local {_format_pos(obj.attach_point)}.")
        lines.append('')
        for child in obj.children: describe(child, depth+1, world_M)

    for obj in scene.objects: describe(obj)

    # -- Spatial relationships ------------------------------------------------─
    lines.append('-- Spatial relationships --')
    lines.append('')

    positions = [scene.world_pos(o) for o in all_objs]
    radii     = [scene.world_radius(o) for o in all_objs]
    if positions:
        min_x=min(p.x-r for p,r in zip(positions,radii)); max_x=max(p.x+r for p,r in zip(positions,radii))
        min_y=min(p.y-r for p,r in zip(positions,radii)); max_y=max(p.y+r for p,r in zip(positions,radii))
        min_z=min(p.z-r for p,r in zip(positions,radii)); max_z=max(p.z+r for p,r in zip(positions,radii))
        lines.append(f"Scene spans {max_x-min_x:.1f}W × {max_y-min_y:.1f}H × {max_z-min_z:.1f}D.")

    top = scene.objects
    if len(top) > 1:
        for i, a in enumerate(top):
            for b in top[i+1:]:
                pa = scene.world_pos(a); pb = scene.world_pos(b)
                d  = _dist(pa, pb)
                off = Vec3(pb.x-pa.x, pb.y-pa.y, pb.z-pa.z)
                lines.append(f"'{b.id}' is {d:.1f} units from '{a.id}' ({_direction_name(off)} '{a.id}').")
    elif top:
        obj = top[0]
        lines.append(f"'{obj.id}' is the root object.")
        if obj.children:
            lines.append(f"It has {len(obj.children)} direct child{'ren' if len(obj.children)!=1 else ''}: "
                         f"{', '.join(c.id for c in obj.children)}.")

    # Overlap analysis
    lines.append('')
    # Build merge_group membership map for overlap note
    from collections import defaultdict as _dd
    _mg_map = _dd(set)  # obj_id -> set of group names
    for _obj in all_objs:
        for _tag in _obj.tags:
            if _tag.startswith('merge_group='):
                _mg_map[_obj.id].add(_tag.split('=',1)[1])

    overlaps = []
    for i, a in enumerate(all_objs):
        for b in all_objs[i+1:]:
            pa = scene.world_pos(a); pb = scene.world_pos(b)
            d  = _dist(pa, pb)
            ra = scene.world_radius(a); rb = scene.world_radius(b)
            if d < ra + rb:
                pct = (ra+rb-d)/(ra+rb)*100
                # Check for any hierarchical relationship (not just direct parent-child)
                def _anc(oid):
                    ids = set(); p = scene.find_parent(oid)
                    while p: ids.add(p.id); p = scene.find_parent(p.id)
                    return ids
                a_anc = _anc(a.id); b_anc = _anc(b.id)
                is_related = a.id in b_anc or b.id in a_anc or bool(a_anc & b_anc)
                shared_mg = _mg_map[a.id] & _mg_map[b.id]
                overlaps.append((a.id, b.id, ra+rb-d, pct, is_related, shared_mg))
    if overlaps:
        lines.append(f"Overlapping pairs ({len(overlaps)}):")
        for aid, bid, overlap, pct, is_related, shared_mg in overlaps:
            if is_related:
                note = "normal -- objects share a common ancestor (same subtree)"
            elif shared_mg:
                note = f"normal -- merge_group={','.join(sorted(shared_mg))} (will union in render)"
            else:
                # Check blob_group
                shared_bg = set()
                for _tag in a.tags:
                    if _tag.startswith('blob_group='):
                        gn = _tag.split('=',1)[1]
                        if any(t2 == f'blob_group={gn}' for t2 in b.tags):
                            shared_bg.add(gn)
                if shared_bg:
                    note = f"normal -- blob_group={','.join(sorted(shared_bg))} (will blob in render)"
                else:
                    # Check explicit intersect tag
                    a_obj = scene.find_object(aid); b_obj = scene.find_object(bid)
                    a_tags = a_obj.tags if a_obj else []; b_tags = b_obj.tags if b_obj else []
                    if any(t in ('intersect=true','intersect') for t in a_tags+b_tags):
                        note = "explicit intersection (intersect=true)"
                    else:
                        note = "clay contact -- use 'press' to deform, 'merge_group' to union, 'blob_group' to smoosh"
            lines.append(f"  '{aid}' ↔ '{bid}': penetration {overlap:.2f} units ({pct:.0f}%) - {note}.")
    else:
        lines.append("No overlaps detected.")
    lines.append('')

    # -- Render ----------------------------------------------------------------
    if tty:
        lines.append('-- ANSI render (truecolour terminal) --')
        lines.append('')
        lines.append(ansi_render(scene))
        lines.append('')
    else:
        lines.append('-- Spatial layout --')
        lines.append('')
        lines.append(text_layout_summary(scene, view=view))
        lines.append('')

    # -- History --------------------------------------------------------------─
    if scene.history:
        n = len(scene.history)
        lines.append(f'-- History ({n} op{"s" if n!=1 else ""}) --')
        lines.append('')
        show = scene.history[-8:]
        if n > 8: lines.append(f'  (last 8 of {n})')
        for entry in show:
            ts = entry.timestamp[:19].replace('T', ' ') if entry.timestamp else ''
            lines.append(f'  [{ts}]  {entry.op}')
        lines.append('')

    lines.append(sep)

    # -- F7: Local axis orientation for target object --------------------------
    if target_id:
        obj = scene.find_object(target_id)
        if obj is None:
            lines.append(f"\nTarget '{target_id}' not found.")
        else:
            world_M = scene.world_matrix_of(target_id)
            # Extract world-space local axes by transforming unit vectors
            origin = world_M * Vec3(0, 0, 0)
            ax_x   = world_M * Vec3(1, 0, 0)
            ax_y   = world_M * Vec3(0, 1, 0)
            ax_z   = world_M * Vec3(0, 0, 1)
            def ax_vec(tip, orig):
                v = Vec3(tip.x-orig.x, tip.y-orig.y, tip.z-orig.z)
                mag = math.sqrt(v.x**2+v.y**2+v.z**2)
                if mag > 1e-10: v = Vec3(v.x/mag, v.y/mag, v.z/mag)
                return v
            lx = ax_vec(ax_x, origin)
            ly = ax_vec(ax_y, origin)
            lz = ax_vec(ax_z, origin)
            lines.append(f"\n-- Local axes for '{target_id}' in world space --")
            lines.append(f"  local +X = world ({lx.x:+.3f}, {lx.y:+.3f}, {lx.z:+.3f})")
            lines.append(f"  local +Y = world ({ly.x:+.3f}, {ly.y:+.3f}, {ly.z:+.3f})")
            lines.append(f"  local +Z = world ({lz.x:+.3f}, {lz.y:+.3f}, {lz.z:+.3f})")
            lines.append(f"  world pos: ({origin.x:.2f}, {origin.y:.2f}, {origin.z:.2f})")
            # Human-readable: which world direction does each local axis point closest to?
            def closest_axis(v):
                axes = [(abs(v.x),'+X' if v.x>0 else '-X'),
                        (abs(v.y),'+Y' if v.y>0 else '-Y'),
                        (abs(v.z),'+Z' if v.z>0 else '-Z')]
                mag, name = max(axes, key=lambda a: a[0])
                return f"~{name} ({mag*100:.0f}%)"
            lines.append(f"  local +X points mostly {closest_axis(lx)}")
            lines.append(f"  local +Y points mostly {closest_axis(ly)}")
            lines.append(f"  local +Z points mostly {closest_axis(lz)}")
            lines.append('')
        lines.append(sep)

    return '\n'.join(lines)


def text_layout_summary(scene, view='top'):
    """ASCII-art spatial layout - screen-reader and Braille-display friendly.

    Uses the scene's active viewpoint (az/el/roll) via the same _view()
    projection as the ANSI and PNG renderers, so the layout matches what
    you actually see on screen.

    The 'view' parameter is kept for API compatibility but ignored -- the
    viewpoint az/el/roll determines the projection.
    """
    all_objs = scene.all_objects()
    if not all_objs: return '  (empty)'
    W, H = 60, 20

    vp   = scene.active_viewpoint()
    az_r = math.radians(vp.az)
    el_r = math.radians(-vp.el if PITCH_INVERSION else vp.el)
    _lx  = vp.look_at.x if vp.look_at else 0.0
    _ly  = vp.look_at.y if vp.look_at else 0.0
    _lz  = vp.look_at.z if vp.look_at else 0.0

    def _view(x, y, z):
        x -= _lx; y -= _ly; z -= _lz
        rx  =  x*math.cos(az_r) + z*math.sin(az_r)
        rz  = -x*math.sin(az_r) + z*math.cos(az_r)
        ry2 =  y*math.cos(el_r) - rz*math.sin(el_r)
        rz2 =  y*math.sin(el_r) + rz*math.cos(el_r)
        depth = rz2
        if vp.roll:
            _rr = math.radians(vp.roll)
            _cr, _sr = math.cos(_rr), math.sin(_rr)
            sx, sy = rx, -ry2
            return sx*_cr - sy*_sr, sx*_sr + sy*_cr, depth
        return rx, -ry2, depth

    positions = []
    for o in all_objs:
        p = scene.world_pos(o)
        sx, sy, depth = _view(p.x, p.y, p.z)
        positions.append((o, sx, sy, depth))

    xs = [p[1] for p in positions]; ys = [p[2] for p in positions]
    xr = max(xs)-min(xs) or 1;      yr = max(ys)-min(ys) or 1
    grid = [['·']*W for _ in range(H)]
    for obj, sx, sy, depth in positions:
        col = int((sx-min(xs))/xr*(W-1)); row = int((sy-min(ys))/yr*(H-1))
        col = max(0, min(W-1, col));      row = max(0, min(H-1, row))
        if obj.type == 'text':
            lbl = str(obj.params.get('content', obj.id))[:W]
        else:
            lbl = obj.id[:4].upper()
        for i, ch in enumerate(lbl):
            if col+i < W: grid[row][col+i] = ch

    header = f'  Viewpoint az={vp.az:.0f}° el={vp.el:.0f}°' + \
             (f' roll={vp.roll:.0f}°' if vp.roll else '')
    lines = [header]
    lines += ['  '+''.join(row) for row in grid]
    lines += ['', '  Key: object IDs at projected positions. · = empty space.']
    return '\n'.join(lines)



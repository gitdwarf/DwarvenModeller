"""DwarvenModeller -- operations: all op_ functions + dispatch table."""
from __future__ import annotations
import math, sys, copy
from .constants import *
from .math_utils import *
from .scene import *
from .primitives import *
# ═════════════════════════════════════════════════════════════════════════════



__all__ = ['parse_op', 'require', 'opt', 'resolve_target', '_FINISH_PRESETS', '_norm_colour', '_apply_material_kwargs', 'op_add', 'op_color', 'op_material', 'op_move', '_obb_from_object', '_obb_intersects', '_find_intersections', 'op_rotate', 'op_scale', 'op_deform', '_surface_point', 'op_attach', 'op_detach', 'op_delete', 'op_measure', 'op_comment', 'op_rename', 'op_tag', 'op_param', 'op_viewpoint', 'op_turn', 'op_tilt', 'op_zoom', 'op_nudge', 'op_roll', 'op_group', 'op_snap', '_vec3_op', 'dm_Vec3_add', 'dm_Vec3_scale', 'op_align', 'op_mirror', 'op_pose', 'op_clone', 'op_text', 'op_pull', 'op_press', 'op_unpress', 'OPERATIONS']

def parse_op(op_str):
    """
    Parse 'verb key=value key=value...' into (verb, {key: value}).
    Quoted values are supported: text="hello world" or text='hello world'.
    Positional args become '_0', '_1', etc.
    """
    import shlex as _shlex
    try:
        parts = _shlex.split(op_str.strip())
    except ValueError:
        parts = op_str.strip().split()  # fallback if shlex fails
    if not parts: return None, {}
    verb = parts[0].lower()
    kwargs = {}; positional = 0
    for part in parts[1:]:
        if '=' in part:
            k, _, v = part.partition('='); kwargs[k.lower()] = v
        else:
            kwargs[f'_{positional}'] = part; positional += 1
    return verb, kwargs


def require(kwargs, *keys):
    """Extract required keys from kwargs dict; raise ValueError if missing."""
    result = []
    for key in keys:
        if key not in kwargs:
            raise ValueError(f"Missing required parameter: {key}")
        result.append(kwargs[key])
    return result if len(result) > 1 else result[0]


def opt(kwargs, key, default=None):
    """Extract optional key from kwargs dict."""
    return kwargs.get(key, default)


def resolve_target(scene, target_id):
    """
    Find object by ID, or raise a helpful error with a close-match suggestion.
    """
    obj = scene.find_object(target_id)
    if obj: return obj
    suggestion = scene.suggest_id(target_id)
    msg = f"No object named '{target_id}'."
    if suggestion: msg += f" Did you mean '{suggestion}'?"
    existing = scene.all_ids()
    if existing: msg += f" Objects in scene: {', '.join(existing)}."
    else: msg += " The scene is empty."
    raise ValueError(msg)


def _FINISH_PRESETS():
    return {
        'matte':   'finish { ambient 0.2 diffuse 0.9 specular 0.0 }',
        'plastic': 'finish { ambient 0.1 diffuse 0.8 specular 0.4 roughness 0.05 }',
        'metal':   'finish { ambient 0.1 diffuse 0.6 specular 0.9 roughness 0.02 metallic }',
        'glass':   'finish { ambient 0.0 diffuse 0.1 specular 0.9 roughness 0.01 reflection 0.2 }',
        'skin':    'finish { ambient 0.3 diffuse 0.85 specular 0.15 roughness 0.15 }',
        'glow':    'finish { ambient 0.8 diffuse 0.4 specular 0.0 }',
    }

def _norm_colour(c):
    """Resolve colour name or hex string to canonical #rrggbb."""
    if not c: return c
    c = c.strip()
    if c[0] != '#': c = _COLOUR_NAMES.get(c.lower(), c)
    if c[0] != '#': return c
    r,g,b = _hex_to_rgb(c)
    return f'#{r:02x}{g:02x}{b:02x}'

def _apply_material_kwargs(obj, kwargs):
    """Apply colour/fill/stroke/opacity/shininess/finish kwargs to an object's material."""
    colour = kwargs.get('colour', kwargs.get('color', kwargs.get('fill')))
    if colour:             obj.material.fill      = _norm_colour(colour)
    if 'stroke'    in kwargs: obj.material.stroke     = kwargs['stroke']
    if 'opacity'   in kwargs: obj.material.opacity    = float(kwargs['opacity'])
    if 'shininess' in kwargs: obj.material.shininess  = float(kwargs['shininess'])
    if 'texture'   in kwargs: obj.material.texture    = kwargs['texture']
    if 'finish'    in kwargs:
        preset = kwargs['finish'].lower()
        presets = _FINISH_PRESETS()
        if preset in presets:
            obj.material.povray_finish = presets[preset]
        else:
            raise ValueError(f"Unknown finish '{preset}'. Use: {', '.join(presets.keys())}")


# ═════════════════════════════════════════════════════════════════════════════
# § OPERATIONS
# ═════════════════════════════════════════════════════════════════════════════

def op_add(scene, kwargs):
    """
    add type=<primitive> id=<id> [radius=N] [width=N height=N depth=N]
        [subdivisions=N] [at=x,y,z] [scale=x,y,z] [rotate=x,y,z]
        [fill=#hex] [stroke=#hex] [opacity=N] [shininess=N]

    Primitives: tetrahedron cube octahedron dodecahedron icosahedron
                sphere cylinder plane torus null cone capsule
                text (content=<str> size=N font=timrom.ttf|cyrvetic.ttf)
    """
    obj_type = opt(kwargs, 'type', '').lower()
    if not obj_type:
        raise ValueError(f"Specify type=<primitive>. Available: {', '.join(sorted(PRIMITIVES))}")
    if obj_type not in PRIMITIVES:
        close = difflib.get_close_matches(obj_type, PRIMITIVES, n=1, cutoff=0.4)
        msg = f"Unknown primitive type '{obj_type}'."
        if close: msg += f" Did you mean '{close[0]}'?"
        raise ValueError(msg + f" Valid: {', '.join(sorted(PRIMITIVES))}")

    raw_id = opt(kwargs, 'id', obj_type)
    obj    = SceneObject(scene.unique_id(raw_id), obj_type)

    # Set type defaults then override from kwargs
    for k, v in PARAM_DEFAULTS.get(obj_type, {}).items():
        obj.set_param(k, v)

    # B1: cube radius= treated as uniform width/height/depth
    if obj_type == 'cube' and 'radius' in kwargs and not any(
            k in kwargs for k in ('width', 'height', 'depth')):
        r = float(kwargs['radius'])
        kwargs['width'] = kwargs['height'] = kwargs['depth'] = str(r)
        print(f"Note: 'radius' on cube treated as width=height=depth={r}. "
              f"Use width/height/depth for non-uniform cubes.", file=sys.stderr)

    for param in ('radius', 'width', 'height', 'depth', 'subdivisions',
                  'inner_radius', 'outer_radius', 'segments',
                  'base_radius', 'top_radius',  # cone
                  'size',                        # text
                  ):
        if param in kwargs: obj.set_param(param, float(kwargs[param]))

    # Text-specific string params
    if obj_type == 'text':
        if 'content' in kwargs: obj.set_param('content', kwargs['content'])
        if 'font'    in kwargs: obj.set_param('font',    kwargs['font'])

    if 'at'     in kwargs: obj.transform.translate = Vec3.parse(kwargs['at'])
    if 'scale'  in kwargs: obj.transform.scale     = Vec3.parse(kwargs['scale'])
    if 'rotate' in kwargs: obj.transform.rotate    = Transform.norm_rot(Vec3.parse(kwargs['rotate']))

    _apply_material_kwargs(obj, kwargs)
    scene.objects.append(obj)

    pos = obj.transform.translate
    r   = obj.get_param('radius', obj.get_param('width', 1.0))
    return f"Added {obj_type} '{obj.id}', radius/size {r}, at ({pos.x}, {pos.y}, {pos.z})."


def op_color(scene, kwargs):
    """
    colour target=<id> fill=#hex [stroke=#hex] [opacity=N] [shininess=N]
                       [finish=matte|plastic|metal|glass|skin|glow]
                       [texture=path] [povray_finish=<string>]

    Sets the surface colour and appearance of an object.
    fill      - main body colour (hex)
    stroke    - outline/edge colour (hex)
    opacity   - 0.0 (invisible) to 1.0 (fully opaque)
    shininess - 0.0 (matte) to 1.0 (mirror)

    finish= named presets (D3) - maps to appropriate POV-Ray finish block:
      matte   - flat, no specular (clay, stone, fabric)
      plastic - medium shine, tight highlight (painted surfaces)
      metal   - high shininess, metallic look
      glass   - transparent, refractive-looking
      skin    - warm subsurface-style, soft highlight (faces, organic)
      glow    - high ambient, emissive-looking (lights, screens)

    Alias: colour (British spelling accepted)
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)

    # Apply named material preset first, then let explicit kwargs override
    if 'use' in kwargs:
        preset_name = kwargs['use']
        if preset_name not in scene.materials:
            known = ', '.join(sorted(scene.materials.keys())) or 'none'
            raise ValueError(f"No material preset '{preset_name}'. Known: {known}. "
                             f"Define with: material name={preset_name} fill=...")
        merged = dict(scene.materials[preset_name])
        merged.update({k: v for k, v in kwargs.items() if k not in ('target', 'use')})
        kwargs = merged

    changes = []
    colour = kwargs.get('colour', kwargs.get('color', kwargs.get('fill')))
    if colour:
        colour = _norm_colour(colour)
        obj.material.fill = colour; changes.append(f"fill={colour}")
    if 'stroke'        in kwargs:
        obj.material.stroke = kwargs['stroke']; changes.append(f"stroke={kwargs['stroke']}")
    if 'opacity'       in kwargs:
        obj.material.opacity = float(kwargs['opacity']); changes.append(f"opacity={kwargs['opacity']}")
    if 'shininess'     in kwargs:
        obj.material.shininess = float(kwargs['shininess']); changes.append(f"shininess={kwargs['shininess']}")
    if 'finish'        in kwargs:
        preset = kwargs['finish'].lower()
        presets = _FINISH_PRESETS()
        if preset in presets:
            obj.material.povray_finish = presets[preset]; changes.append(f"finish={preset}")
        else:
            raise ValueError(f"Unknown finish '{preset}'. Use: {', '.join(presets.keys())}")
    if 'texture'       in kwargs:
        obj.material.texture = kwargs['texture']; changes.append(f"texture={kwargs['texture']}")
    if 'povray_finish' in kwargs:
        obj.material.povray_finish = kwargs['povray_finish']; changes.append("povray_finish set")

    if not changes:
        raise ValueError(
            "No colour properties specified. "
            "Use fill=#rrggbb, stroke=#rrggbb, opacity=0..1, shininess=0..1, "
            "finish=matte|plastic|metal|glass|skin|glow")

    return f"'{target_id}' colour updated: {', '.join(changes)}."


def op_material(scene, kwargs):
    """
    material name=<id> [fill=#hex] [stroke=#hex] [opacity=N] [shininess=N]
                        [finish=matte|plastic|metal|glass|skin|glow]

    Defines a named material preset stored in the scene. Use 'use=<name>'
    in any colour op to apply a preset to an object.

    Examples:
      material name=chrome fill=#c0c0c0 finish=metal
      material name=skin fill=#f0c8a0 finish=skin opacity=1.0
      colour target=head use=skin
      colour target=@sphere use=chrome
    """
    name = require(kwargs, 'name')
    mdata = {k: v for k, v in kwargs.items() if k != 'name'}
    if not mdata:
        # Query mode: print existing preset
        if name in scene.materials:
            return f"Material '{name}': {scene.materials[name]}"
        known = ', '.join(sorted(scene.materials.keys())) or 'none'
        raise ValueError(f"No material named '{name}'. Known: {known}.")
    scene.materials[name] = mdata
    return f"Material '{name}' defined: {mdata}."
def op_move(scene, kwargs):
    """
    target=<id> to=x,y,z           -- absolute position in parent space
    target=<id> by=dx,dy,dz        -- relative move from current position
    target=<id> place=x,y,z        -- place at absolute position in scene space (alias: world_to=)
    target=<id> up/down/left/right=N   -- move relative to your view
    target=<id> away/towards=N         -- move away from or toward you

    Without target=: moves the viewpoint (zoom/pan):
    move up=N / down=N / left=N / right=N   - pan look_at point
    move away=N / towards=N                  - zoom out/in

    All variants check for intersections and refuse if any found,
    unless force=true is specified.
    """
    # Camera-relative direction vectors in world space
    # Derived from active viewpoint az/el (ignore roll for movement purposes)
    def _cam_vecs():
        import math
        vp   = scene.active_viewpoint()
        az_r = math.radians(vp.az)
        el_r = math.radians(-vp.el if PITCH_INVERSION else vp.el)
        # Camera forward (into scene = away from viewer = +Z axis rotated)
        fwd_x =  math.sin(az_r) * math.cos(el_r)
        fwd_y = -math.sin(el_r)
        fwd_z =  math.cos(az_r) * math.cos(el_r)
        # Camera right
        rgt_x =  math.cos(az_r)
        rgt_y =  0.0
        rgt_z = -math.sin(az_r)
        # Camera up
        up_x  = -math.sin(az_r) * math.sin(el_r)
        up_y  =  math.cos(el_r)
        up_z  = -math.cos(az_r) * math.sin(el_r)
        return (fwd_x,fwd_y,fwd_z), (rgt_x,rgt_y,rgt_z), (up_x,up_y,up_z)

    _cam_dirs = ('up','down','left','right','away','towards','toward')
    _is_cam   = any(k in kwargs for k in _cam_dirs)

    # No target = viewpoint pan/zoom
    if 'target' not in kwargs:
        vp = scene.active_viewpoint()
        if not vp.look_at:
            import dwarvenmodeller as _dm; vp.look_at = Vec3(0,0,0)
        fwd,rgt,up = _cam_vecs()
        changes = []
        for key, sign, axis in [
            ('up',1,up),('down',-1,up),
            ('right',1,rgt),('left',-1,rgt),
        ]:
            if key in kwargs:
                d = float(kwargs[key]) * sign
                vp.look_at.x += axis[0]*d
                vp.look_at.y += axis[1]*d
                vp.look_at.z += axis[2]*d
                changes.append(f"moved {key} {abs(d):.1f}")
        for key, sign in [('away',-1),('towards',1),('toward',1)]:
            if key in kwargs:
                d = float(kwargs[key]) * 0.1 * sign
                vp.scale = max(0.01, vp.scale + d)
                changes.append(f"{'zoomed out' if sign<0 else 'zoomed in'} → zoom={vp.scale:.2f}")
        return f"Viewpoint: {', '.join(changes)}." if changes else "No viewpoint change."

    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    force     = opt(kwargs, 'force', 'false').lower() in ('true', '1', 'yes')

    saved = Vec3(obj.transform.translate.x,
                 obj.transform.translate.y,
                 obj.transform.translate.z)

    if _is_cam:
        # Camera-relative move on object
        fwd,rgt,up = _cam_vecs()
        dx=dy=dz=0.0
        for key, sign, axis in [
            ('up',1,up),('down',-1,up),
            ('right',1,rgt),('left',-1,rgt),
            ('away',1,fwd),('towards',-1,fwd),('toward',-1,fwd),
        ]:
            if key in kwargs:
                d = float(kwargs[key]) * sign
                dx += axis[0]*d; dy += axis[1]*d; dz += axis[2]*d
        delta = Vec3(dx,dy,dz)
        obj.transform.translate = obj.transform.translate + delta
        pos = obj.transform.translate
        dirs = [f"{k}={kwargs[k]}" for k in _cam_dirs if k in kwargs]
        msg = f"Moved '{target_id}' {', '.join(dirs)} (from your perspective). Now at ({pos.x:.2f},{pos.y:.2f},{pos.z:.2f})."
    elif 'place' in kwargs or 'world_to' in kwargs:
        world_target = Vec3.parse(kwargs.get('place', kwargs.get('world_to')))
        parent = scene.find_parent(target_id)
        if parent:
            try:
                local_pos = scene._world_matrix(parent).inverse() * world_target
            except Exception:
                local_pos = world_target
        else:
            local_pos = world_target
        obj.transform.translate = local_pos
        wp = scene.world_pos(obj)
        msg = (f"Moved '{target_id}' to world ({world_target.x}, {world_target.y}, {world_target.z}). "
               f"Local: ({local_pos.x:.3f}, {local_pos.y:.3f}, {local_pos.z:.3f}). "
               f"Actual world: ({wp.x:.3f}, {wp.y:.3f}, {wp.z:.3f}).")
    elif 'to' in kwargs:
        obj.transform.translate = Vec3.parse(kwargs['to'])
        pos = obj.transform.translate
        msg = f"Moved '{target_id}' to ({pos.x}, {pos.y}, {pos.z}) in parent space."
    elif 'by' in kwargs:
        delta = Vec3.parse(kwargs['by'])
        obj.transform.translate = obj.transform.translate + delta
        pos = obj.transform.translate
        msg = f"Moved '{target_id}' by ({delta.x}, {delta.y}, {delta.z}). Now at ({pos.x}, {pos.y}, {pos.z})."
    else:
        raise ValueError("Specify: up/down/left/right/away/towards=N, to=x,y,z, place=x,y,z, or by=dx,dy,dz.")

    collisions = _find_intersections(scene, target_id)
    if collisions and not force:
        obj.transform.translate = saved
        raise ValueError(
            f"Move refused: '{target_id}' would intersect "
            f"{', '.join(collisions)}. Use force=true to override.")
    if collisions:
        msg += f" WARNING: intersects {', '.join(collisions)} (forced)."
    return msg


# -- Intersection detection - Separating Axis Theorem for OBBs --------------

def _obb_from_object(obj, world_matrix):
    """Return (centre, half_extents, axes) OBB in world space."""
    p  = obj.params
    hx = float(p.get('width',  p.get('radius', 1.0))) / 2
    hy = float(p.get('height', p.get('radius', 1.0))) / 2
    hz = float(p.get('depth',  p.get('radius', 1.0))) / 2
    centre = world_matrix * Vec3(0, 0, 0)
    o  = centre
    ax = world_matrix * Vec3(1,0,0); ax = Vec3(ax.x-o.x, ax.y-o.y, ax.z-o.z)
    ay = world_matrix * Vec3(0,1,0); ay = Vec3(ay.x-o.x, ay.y-o.y, ay.z-o.z)
    az = world_matrix * Vec3(0,0,1); az = Vec3(az.x-o.x, az.y-o.y, az.z-o.z)
    return centre, (hx, hy, hz), (ax, ay, az)


def _obb_intersects(obb_a, obb_b):
    """SAT test for two OBBs. Returns True if intersecting."""
    ca, (hxa,hya,hza), (aax,aay,aaz) = obb_a
    cb, (hxb,hyb,hzb), (abx,aby,abz) = obb_b

    def dot(a, b): return a.x*b.x + a.y*b.y + a.z*b.z
    def cross(a, b): return Vec3(a.y*b.z-a.z*b.y, a.z*b.x-a.x*b.z, a.x*b.y-a.y*b.x)
    def proj_a(ax): return abs(dot(aax,ax))*hxa + abs(dot(aay,ax))*hya + abs(dot(aaz,ax))*hza
    def proj_b(ax): return abs(dot(abx,ax))*hxb + abs(dot(aby,ax))*hyb + abs(dot(abz,ax))*hzb

    t = Vec3(cb.x-ca.x, cb.y-ca.y, cb.z-ca.z)
    for axis in [aax,aay,aaz, abx,aby,abz]:
        l = axis.length()
        if l < 1e-10: continue
        axis = Vec3(axis.x/l, axis.y/l, axis.z/l)
        if abs(dot(t,axis)) > proj_a(axis) + proj_b(axis): return False
    for a in [aax,aay,aaz]:
        for b in [abx,aby,abz]:
            axis = cross(a, b); l = axis.length()
            if l < 1e-10: continue
            axis = Vec3(axis.x/l, axis.y/l, axis.z/l)
            if abs(dot(t,axis)) > proj_a(axis) + proj_b(axis): return False
    return True


def _find_intersections(scene, moved_id):
    """
    Return list of object IDs that moved_id now intersects.
    Skips parent/child pairs and null/group objects.
    """
    obj = scene.find_object(moved_id)
    if not obj or _should_skip(obj): return []
    moved_M = scene.world_matrix_of(moved_id)
    obb_a   = _obb_from_object(obj, moved_M)
    parent  = scene.find_parent(moved_id)
    collisions = []
    for other in scene.all_objects():
        if other.id == moved_id: continue
        if _should_skip(other): continue
        if parent and parent.id == other.id: continue
        other_parent = scene.find_parent(other.id)
        if other_parent and other_parent.id == moved_id: continue
        obb_b = _obb_from_object(other, scene.world_matrix_of(other.id))
        if _obb_intersects(obb_a, obb_b):
            collisions.append(other.id)
    return collisions


def op_rotate(scene, kwargs):
    """
    rotate target=<id> x=deg              - rotate around object's local X axis
    rotate target=<id> y=deg              - rotate around object's local Y axis
    rotate target=<id> z=deg              - rotate around object's local Z axis
    rotate target=<id> x=deg y=deg z=deg  - compose all three in X→Y→Z order
    rotate target=<id> set=x,y,z         - set absolute Euler angles directly
    rotate target=<id> world_set=x,y,z   - set absolute orientation in scene space

    Rotations are always relative to the object's own local axes - parent
    chain rotations are transparent. x=30 always means "30° around this
    object's own X axis", regardless of how the parent is oriented.

    world_set= sets the final world-space orientation regardless of parent chain.
    Use set= only when you need to force specific local Euler values (rare).
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    force     = opt(kwargs, 'force', 'false').lower() in ('true', '1', 'yes')

    # Save rotation so we can restore if intersection check fails
    saved = Vec3(obj.transform.rotate.x, obj.transform.rotate.y, obj.transform.rotate.z)

    if 'world_set' in kwargs:
        # set world-space orientation by computing the local rotation needed
        # to achieve the desired world rotation given the parent chain.
        desired_world = Vec3.parse(kwargs['world_set'])
        desired_M = Mat4.from_trs(Vec3(0,0,0), desired_world, Vec3(1,1,1))
        # Get parent world rotation matrix
        parent = scene.find_parent(target_id)
        if parent:
            parent_M = scene._world_matrix(parent)
            # Extract rotation part of parent matrix (ignore translation/scale)
            parent_rot_M = Mat4.identity()
            m = parent_M.m
            # Normalise columns to get pure rotation
            for ci in range(3):
                col = [m[ri][ci] for ri in range(3)]
                mag = math.sqrt(sum(v*v for v in col))
                if mag > 1e-10:
                    for ri in range(3):
                        parent_rot_M.m[ri][ci] = m[ri][ci] / mag
            # local_rot = inv(parent_rot) * desired_rot
            # For rotation matrices, inverse = transpose
            parent_inv = Mat4.identity()
            for ri in range(3):
                for ci in range(3):
                    parent_inv.m[ri][ci] = parent_rot_M.m[ci][ri]
            local_M = parent_inv * desired_M
        else:
            local_M = desired_M
        m = local_M.m
        sy = math.sqrt(m[0][0]**2 + m[1][0]**2)
        if sy > 1e-6:
            rx = math.degrees(math.atan2( m[2][1], m[2][2]))
            ry = math.degrees(math.atan2(-m[2][0], sy))
            rz = math.degrees(math.atan2( m[1][0], m[0][0]))
        else:
            rx = math.degrees(math.atan2(-m[1][2], m[1][1]))
            ry = math.degrees(math.atan2(-m[2][0], sy))
            rz = 0.0
        obj.transform.rotate = Transform.norm_rot(Vec3(rx, ry, rz))
    elif 'set' in kwargs:
        v = Vec3.parse(kwargs['set'])
        obj.transform.rotate = Transform.norm_rot(v)
    else:
        compose = Mat4.identity()
        if 'x' in kwargs: compose = compose * Mat4.rotate_x(float(kwargs['x']))
        if 'y' in kwargs: compose = compose * Mat4.rotate_y(float(kwargs['y']))
        if 'z' in kwargs: compose = compose * Mat4.rotate_z(float(kwargs['z']))
        rot_only  = Mat4.from_trs(Vec3(0,0,0), obj.transform.rotate, Vec3(1,1,1))
        new_rot_M = rot_only * compose
        m  = new_rot_M.m
        sy = math.sqrt(m[0][0]**2 + m[1][0]**2)
        if sy > 1e-6:
            rx = math.degrees(math.atan2( m[2][1], m[2][2]))
            ry = math.degrees(math.atan2(-m[2][0], sy))
            rz = math.degrees(math.atan2( m[1][0], m[0][0]))
        else:
            rx = math.degrees(math.atan2(-m[1][2], m[1][1]))
            ry = math.degrees(math.atan2(-m[2][0], sy))
            rz = 0.0
        obj.transform.rotate = Transform.norm_rot(Vec3(rx, ry, rz))

    collisions = _find_intersections(scene, target_id)
    if collisions and not force:
        obj.transform.rotate = Transform.norm_rot(saved)
        raise ValueError(
            f"Rotation refused: '{target_id}' would intersect "
            f"{', '.join(collisions)}. Use force=true to override.")

    r   = obj.transform.rotate
    msg = (f"'{target_id}' rotation: "
           f"({Transform.display_angle(r.x):.1f}\u00b0, "
           f"{Transform.display_angle(r.y):.1f}\u00b0, "
           f"{Transform.display_angle(r.z):.1f}\u00b0).")
    if collisions:
        msg += f" WARNING: intersects {', '.join(collisions)} (forced)."
    return msg



def op_scale(scene, kwargs):
    """
    scale target=<id> x=N y=N z=N   - set scale per axis
    scale target=<id> uniform=N     - uniform scale on all axes
    scale target=<id> by=sx,sy,sz   - multiply current scale

    Scale 2.0 = double. Scale 0.5 = half. Non-uniform scale stretches.
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    if 'uniform' in kwargs:
        u = float(kwargs['uniform']); obj.transform.scale = Vec3(u, u, u)
    elif 'by' in kwargs:
        s = Vec3.parse(kwargs['by']); sc = obj.transform.scale
        obj.transform.scale = Vec3(sc.x*s.x, sc.y*s.y, sc.z*s.z)
    else:
        if 'x' in kwargs: obj.transform.scale.x = float(kwargs['x'])
        if 'y' in kwargs: obj.transform.scale.y = float(kwargs['y'])
        if 'z' in kwargs: obj.transform.scale.z = float(kwargs['z'])
    s = obj.transform.scale
    return f"'{target_id}' scale: ({s.x:.3f}, {s.y:.3f}, {s.z:.3f})."


def op_deform(scene, kwargs):
    """
    deform target=<id> axis=x|y|z scale=N   - stretch along axis (immediate)
    deform target=<id> taper=N axis=y       - store taper for renderer
    deform target=<id> twist=N axis=y       - store twist for renderer
    deform target=<id> bend=N  axis=x       - store bend for renderer
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    if 'axis' in kwargs and 'scale' in kwargs:
        axis = kwargs['axis'].lower(); s = float(kwargs['scale'])
        if   axis == 'x': obj.transform.scale.x *= s
        elif axis == 'y': obj.transform.scale.y *= s
        elif axis == 'z': obj.transform.scale.z *= s
        else: raise ValueError(f"Unknown axis '{axis}'. Use x, y, or z.")
        sc = obj.transform.scale
        return f"'{target_id}' stretched along {axis} by {s}. Scale: ({sc.x:.3f}, {sc.y:.3f}, {sc.z:.3f})."
    changes = []
    for dtype in ('taper', 'twist', 'bend', 'shear'):
        if dtype in kwargs:
            obj.set_param(f'deform_{dtype}', float(kwargs[dtype]))
            changes.append(f"{dtype}={kwargs[dtype]}")
    if 'axis' in kwargs:
        obj.set_param('deform_axis', kwargs['axis']); changes.append(f"axis={kwargs['axis']}")
    if not changes:
        raise ValueError("Specify axis=+scale= for stretch, or taper= / twist= / bend=.")
    return f"'{target_id}' deform stored: {', '.join(changes)}."


def _surface_point(scene, parent, query_world):
    """Return (surface_point, outward_normal) in world space on parent's surface
    closest to query_world (a Vec3 in world space).

    Supports: sphere/icosahedron/octahedron, cube, cylinder.
    Falls back to sphere approximation for unknown primitives.
    """
    import math as _math

    def _vec3_sub(a, b): return Vec3(a.x-b.x, a.y-b.y, a.z-b.z)
    def _vec3_len(v):    return _math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
    def _vec3_norm(v):
        l = _vec3_len(v)
        return Vec3(v.x/l, v.y/l, v.z/l) if l > 1e-10 else Vec3(0, 1, 0)
    def _vec3_scale(v, s): return Vec3(v.x*s, v.y*s, v.z*s)
    def _vec3_add(a, b):   return Vec3(a.x+b.x, a.y+b.y, a.z+b.z)
    def _clamp(v, lo, hi): return max(lo, min(hi, v))

    t = parent.type
    world_M   = scene._world_matrix(parent)
    centre    = scene.world_pos(parent)
    p         = parent.params

    # Transform query into parent LOCAL space for cube/cylinder maths
    try:
        inv_M  = world_M.inverse()
        q_local = inv_M * query_world
    except Exception:
        q_local = query_world

    if t in ('sphere', 'icosahedron', 'octahedron', 'tetrahedron', 'dodecahedron'):
        r = scene.world_radius(parent)
        d = _vec3_sub(query_world, centre)
        n = _vec3_norm(d)
        sp = _vec3_add(centre, _vec3_scale(n, r))
        return sp, n

    elif t == 'cube':
        hx = float(p.get('width',  p.get('radius', 1.0))) * 0.5
        hy = float(p.get('height', p.get('radius', 1.0))) * 0.5
        hz = float(p.get('depth',  p.get('radius', 1.0))) * 0.5
        # Scale by object scale
        sx = parent.transform.scale.x
        sy = parent.transform.scale.y
        sz = parent.transform.scale.z
        hx *= sx; hy *= sy; hz *= sz
        # Closest point on box surface in local space
        cx = _clamp(q_local.x, -hx, hx)
        cy = _clamp(q_local.y, -hy, hy)
        cz = _clamp(q_local.z, -hz, hz)
        # Find which face is closest by checking penetration depths
        dx = hx - abs(q_local.x)
        dy = hy - abs(q_local.y)
        dz = hz - abs(q_local.z)
        if dx <= dy and dx <= dz:
            nx = 1.0 if q_local.x >= 0 else -1.0
            sp_local = Vec3(nx * hx, cy, cz)
            n_local  = Vec3(nx, 0, 0)
        elif dy <= dx and dy <= dz:
            ny = 1.0 if q_local.y >= 0 else -1.0
            sp_local = Vec3(cx, ny * hy, cz)
            n_local  = Vec3(0, ny, 0)
        else:
            nz = 1.0 if q_local.z >= 0 else -1.0
            sp_local = Vec3(cx, cy, nz * hz)
            n_local  = Vec3(0, 0, nz)
        # Transform back to world space
        sp = world_M * sp_local
        # Normal: rotate only (no translation/scale) -- use 3x3 of world_M
        # Approximate: apply world_M to (centre + normal) and subtract centre
        n_world_pt = world_M * Vec3(n_local.x, n_local.y, n_local.z)
        n_world = _vec3_sub(n_world_pt, centre)
        return sp, _vec3_norm(n_world)

    elif t == 'cylinder':
        r  = float(p.get('radius', 1.0)) * max(parent.transform.scale.x,
                                                parent.transform.scale.z)
        h  = float(p.get('height', 2.0)) * parent.transform.scale.y
        half_h = h * 0.5
        # In local space, cylinder axis = Y, caps at y=+/-half_h
        qy = q_local.y
        qr = _math.sqrt(q_local.x**2 + q_local.z**2)
        # Determine closest region: barrel vs top cap vs bottom cap
        on_barrel = abs(qy) <= half_h
        dist_barrel = abs(qr - r) if on_barrel else float('inf')
        dist_top    = abs(qy - half_h)  if qr <= r else float('inf')
        dist_bot    = abs(qy + half_h)  if qr <= r else float('inf')
        min_dist    = min(dist_barrel, dist_top, dist_bot)
        if min_dist == dist_barrel or (not on_barrel and qr > r):
            # Barrel: project to cylinder side
            angle_r = _vec3_norm(Vec3(q_local.x, 0, q_local.z))
            sp_local = Vec3(angle_r.x * r, _clamp(qy, -half_h, half_h), angle_r.z * r)
            n_local  = angle_r
        elif min_dist == dist_top:
            sp_local = Vec3(q_local.x, half_h, q_local.z)
            n_local  = Vec3(0, 1, 0)
        else:
            sp_local = Vec3(q_local.x, -half_h, q_local.z)
            n_local  = Vec3(0, -1, 0)
        sp = world_M * sp_local
        n_world_pt = world_M * Vec3(n_local.x, n_local.y, n_local.z)
        n_world = _vec3_sub(n_world_pt, centre)
        return sp, _vec3_norm(n_world)

    elif t == 'cone':
        # Approximate cone as cylinder with base_radius for surface queries
        rb   = float(p.get('base_radius', 1.0)) * max(parent.transform.scale.x,
                                                       parent.transform.scale.z)
        h    = float(p.get('height', 2.0)) * parent.transform.scale.y
        half_h = h * 0.5
        qy = q_local.y
        qr = _math.sqrt(q_local.x**2 + q_local.z**2)
        # Interpolate radius at query height
        rt  = float(p.get('top_radius', 0.0)) * max(parent.transform.scale.x,
                                                     parent.transform.scale.z)
        t_frac = (qy + half_h) / h if h > 0 else 0.5
        r_at_y = rb + (rt - rb) * _clamp(t_frac, 0, 1)
        angle_r = _vec3_norm(Vec3(q_local.x, 0, q_local.z))
        sp_local = Vec3(angle_r.x * r_at_y, _clamp(qy, -half_h, half_h), angle_r.z * r_at_y)
        n_local  = angle_r
        sp = world_M * sp_local
        n_world_pt = world_M * Vec3(n_local.x, n_local.y, n_local.z)
        return sp, _vec3_norm(_vec3_sub(n_world_pt, centre))

    elif t == 'capsule':
        # Capsule: hemisphere surface at ends, cylinder barrel in middle
        r    = float(p.get('radius', 1.0)) * max(parent.transform.scale.x,
                                                  parent.transform.scale.z)
        h    = float(p.get('height', 2.0)) * parent.transform.scale.y
        half_h = h * 0.5
        qy = q_local.y
        if qy > half_h:
            # Top hemisphere
            cap_centre = Vec3(0, half_h, 0)
            d = _vec3_sub(q_local, cap_centre)
            n_local = _vec3_norm(d)
            sp_local = _vec3_add(cap_centre, _vec3_scale(n_local, r))
        elif qy < -half_h:
            # Bottom hemisphere
            cap_centre = Vec3(0, -half_h, 0)
            d = _vec3_sub(q_local, cap_centre)
            n_local = _vec3_norm(d)
            sp_local = _vec3_add(cap_centre, _vec3_scale(n_local, r))
        else:
            # Barrel
            angle_r = _vec3_norm(Vec3(q_local.x, 0, q_local.z))
            sp_local = Vec3(angle_r.x * r, qy, angle_r.z * r)
            n_local  = angle_r
        sp = world_M * sp_local
        n_world_pt = world_M * Vec3(n_local.x, n_local.y, n_local.z)
        return sp, _vec3_norm(_vec3_sub(n_world_pt, centre))

    else:
        # Fallback: treat as sphere
        r = scene.world_radius(parent)
        d = _vec3_sub(query_world, centre)
        n = _vec3_norm(d)
        return _vec3_add(centre, _vec3_scale(n, r)), n


def op_attach(scene, kwargs):
    """
    attach child=<id> to=<parent_id> [at=x,y,z] [world_at=x,y,z] [surface=true] [normal=x,y,z]

    Makes <child> a child of <parent>.
    at=          - position in parent local space.
    world_at=    - position in world space; DM converts to local.
    surface=true - auto-place child flush on parent surface, outward along normal.
                   Uses child's current world position to find closest surface point.
    """
    child_id  = require(kwargs, 'child')
    parent_id = require(kwargs, 'to')
    child     = resolve_target(scene, child_id)
    parent    = resolve_target(scene, parent_id)
    if child_id == parent_id:
        raise ValueError("Cannot attach an object to itself.")
    chain = scene._parent_chain(parent_id)
    if any(o.id == child_id for o in chain):
        raise ValueError(
            f"Cannot attach '{child_id}' to '{parent_id}': cycle detected. "
            f"'{parent_id}' is already a descendant of '{child_id}'.")
    current_parent = scene.find_parent(child_id)
    if current_parent:  current_parent.children.remove(child)
    elif child in scene.objects: scene.objects.remove(child)

    surface_mode = str(kwargs.get('surface', 'false')).lower() in ('true', '1', 'yes')

    if surface_mode:
        child_world = scene.world_pos(child)
        sp, normal = _surface_point(scene, parent, child_world)
        try:
            local_pos = scene._world_matrix(parent).inverse() * sp
        except Exception:
            local_pos = sp
        child.attach_point  = local_pos
        child.transform.translate = local_pos
        child.attach_normal = normal
    elif 'world_at' in kwargs:
        world_target = Vec3.parse(kwargs['world_at'])
        try:
            local_pos = scene._world_matrix(parent).inverse() * world_target
        except Exception:
            local_pos = world_target
        child.attach_point  = local_pos
        child.transform.translate = local_pos
    elif 'at' in kwargs:
        child.attach_point  = Vec3.parse(kwargs['at'])
        child.transform.translate = Vec3.parse(kwargs['at'])

    if 'normal' in kwargs:
        child.attach_normal = Vec3.parse(kwargs['normal'])

    parent.children.append(child)
    wp = scene.world_pos(child)
    lp = child.transform.translate
    extra = f" Placed on {parent_id} surface." if surface_mode else ""
    return (f"'{child_id}' attached to '{parent_id}'.{extra} "
            f"Local: ({lp.x:.2f}, {lp.y:.2f}, {lp.z:.2f}). "
            f"World: ({wp.x:.2f}, {wp.y:.2f}, {wp.z:.2f}).")


def op_detach(scene, kwargs):
    """
    detach target=<id>

    Detaches from parent, becomes top-level. World position is preserved.
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    parent    = scene.find_parent(target_id)
    if parent is None:
        return f"'{target_id}' is already top-level."
    world_p = scene.world_pos(obj)
    parent.children.remove(obj)
    obj.transform.translate = world_p
    obj.attach_point = obj.attach_normal = None
    scene.objects.append(obj)
    return (f"'{target_id}' detached from '{parent.id}'. "
            f"World position preserved: ({world_p.x:.2f}, {world_p.y:.2f}, {world_p.z:.2f}).")


def op_delete(scene, kwargs):
    """
    delete target=<id> [children=keep|delete]

    Removes object. Default: deletes children too.
    children=keep re-homes children to same level as deleted object.
    """
    target_id     = require(kwargs, 'target')
    obj           = resolve_target(scene, target_id)
    keep_children = opt(kwargs, 'children', 'delete').lower() == 'keep'
    parent        = scene.find_parent(target_id)
    container     = parent.children if parent else scene.objects
    if keep_children and obj.children:
        idx = container.index(obj)
        for child in obj.children:
            child.attach_point = None
            container.insert(idx, child); idx += 1
    container.remove(obj)
    msg = f"Deleted '{target_id}'."
    if keep_children and obj.children:
        msg += f" {len(obj.children)} children promoted."
    return msg


def op_measure(scene, kwargs):
    """
    measure from=<id> to=<id>

    Returns world-space distance between the centres of two objects.
    Also reports combined radii and gap/penetration depth.
    Feeds directly into 'DON'T GUESS, MEASURE'.
    """
    from_id = require(kwargs, 'from')
    to_id   = require(kwargs, 'to')
    a = resolve_target(scene, from_id)
    b = resolve_target(scene, to_id)
    pa = scene.world_pos(a); pb = scene.world_pos(b)
    import math as _math
    dx = pb.x-pa.x; dy = pb.y-pa.y; dz = pb.z-pa.z
    dist = _math.sqrt(dx*dx + dy*dy + dz*dz)
    ra = scene.world_radius(a); rb = scene.world_radius(b)
    combined = ra + rb
    gap = dist - combined
    if gap > 0:
        contact = f"gap of {gap:.3f} units (not touching)"
    elif gap < 0:
        contact = f"overlapping by {abs(gap):.3f} units"
    else:
        contact = "surfaces exactly touching"
    return (f"Distance '{from_id}' to '{to_id}': {dist:.4f} units. "
            f"Radii: {ra:.3f} + {rb:.3f} = {combined:.3f}. "
            f"Surface contact: {contact}.")


def op_comment(scene, kwargs):
    """
    comment text=<string>

    Adds a human-readable section marker to history. No geometry is changed.
    Useful for annotating long build scripts: 'comment text=starting the head'.
    """
    text = kwargs.get('text', kwargs.get('msg', kwargs.get('note', '')))
    if not text:
        raise ValueError("Specify text=<string>.")
    return f"# {text}"


def op_rename(scene, kwargs):
    """rename target=<id> id=<new_id>"""
    target_id = require(kwargs, 'target')
    new_id    = require(kwargs, 'id')
    obj = resolve_target(scene, target_id)
    if scene.find_object(new_id):
        raise ValueError(f"ID '{new_id}' is already in use.")
    old_id = obj.id; obj.id = new_id
    return f"'{old_id}' renamed to '{new_id}'."


def op_tag(scene, kwargs):
    """
    tag target=<id> add=tag1,tag2
    tag target=<id> remove=tag1,tag2
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    if 'add' in kwargs:
        for t in [x.strip() for x in kwargs['add'].split(',') if x.strip()]:
            if t not in obj.tags: obj.tags.append(t)
        return f"'{target_id}' tags: {', '.join(obj.tags) or '(none)'}."
    elif 'remove' in kwargs:
        rm = {t.strip() for t in kwargs['remove'].split(',')}
        obj.tags = [t for t in obj.tags if t not in rm]
        return f"'{target_id}' tags: {', '.join(obj.tags) or '(none)'}."
    raise ValueError("Specify add=tag1,tag2 or remove=tag1,tag2.")


def op_param(scene, kwargs):
    """
    param target=<id> key=value [key=value ...]

    Set primitive-specific parameters directly (radius, subdivisions, etc).
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    changes   = [(k, v) for k, v in kwargs.items() if k != 'target']
    if not changes:
        raise ValueError("No parameters given. Example: param target=head subdivisions=4")
    for k, v in changes: obj.set_param(k, v)
    return f"'{target_id}' params: {', '.join(f'{k}={v}' for k,v in changes)}."


def op_viewpoint(scene, kwargs):
    """Set viewpoint directly. For most adjustments use turn/tilt/zoom/move instead.

    viewpoint [yaw=N] [pitch=N] [zoom=N] [roll=N] [focus=x,y,z] [pos=x,y,z]
              (az= and el= still accepted as aliases)

    Common starting points:
      Scene facing away (back toward you): yaw=0   pitch=0
      Scene facing you (default for new):  yaw=180 pitch=0
      Classic 3/4 view:                    yaw=330 pitch=25
      Looking straight down:               yaw=0   pitch=89

    Common starting points (use turn/tilt to adjust from here):
      Scene facing away (back toward modeller): yaw=0   pitch=0
      Scene facing you (face toward modeller):  yaw=180 pitch=0
      Looking down from above:               az=0   el=89
      3/4 view (scene rotated left, facing): az=330 el=25 (default)

    Note: there is no "Front view" or "Camera". You hold the clay.
    Turn/tilt the sphere until it feels right, then check --feedback.
    """
    name = opt(kwargs, 'name', 'default')
    vp   = next((v for v in scene.viewpoints if v.name == name), None)
    if vp is None:
        vp = Viewpoint(name=name); scene.viewpoints.append(vp)
    scene.viewpoints.remove(vp); scene.viewpoints.insert(0, vp)
    changes = []
    # Accept both technical (az/el/scale) and human-friendly names
    _az = next((kwargs[k] for k in ('az','yaw','turn','rotate') if k in kwargs), None)
    _el = next((kwargs[k] for k in ('el','pitch','tilt') if k in kwargs), None)
    _sc = next((kwargs[k] for k in ('scale','zoom','distance') if k in kwargs), None)
    _la = next((kwargs[k] for k in ('look_at','focus','centre','center') if k in kwargs), None)
    if _az is not None: vp.az    = float(_az) % 360;            changes.append(f"yaw={vp.az:.1f}°")
    if _el is not None: vp.el    = float(_el) % 360;            changes.append(f"pitch={vp.el:.1f}°")
    if 'roll'  in kwargs: vp.roll  = float(kwargs['roll']) % 360; changes.append(f"roll={vp.roll:.1f}°")
    if _sc is not None: vp.scale = float(_sc);                   changes.append(f"zoom={vp.scale}")
    if 'pos'   in kwargs: vp.pos  = Vec3.parse(kwargs['pos']);    changes.append(f"exact position {vp.pos}")
    if _la is not None: vp.look_at = Vec3.parse(_la);             changes.append(f"focus {vp.look_at}")
    return f"Viewpoint '{name}' active. {', '.join(changes) if changes else 'No changes.'}"

def op_turn(scene, kwargs):
    """
    turn left=N              -- spin the scene-sphere left by N degrees
    turn right=N             -- spin the scene-sphere right by N degrees
    turn target=<id> left=N  -- spin an object's local sphere left (rotate around its Y axis)
    turn target=<id> right=N -- spin an object's local sphere right

    Without target: rotates the whole scene in your hands (viewpoint az).
    With target: spins that object on its own vertical axis.
    Relative -- always a delta. Like turning a turntable left or right.
    """
    if 'target' in kwargs:
        obj = resolve_target(scene, kwargs['target'])
        delta = float(kwargs.get('left', 0)) - float(kwargs.get('right', 0))
        obj.transform.rotate.y = (obj.transform.rotate.y + delta) % 360
        return f"Turned '{kwargs['target']}' {'left' if delta>0 else 'right'} {abs(delta):.1f}°. Local Y now {obj.transform.rotate.y:.1f}°."
    vp = scene.active_viewpoint()
    if 'left'  in kwargs: vp.az = (vp.az + float(kwargs['left']))  % 360
    if 'right' in kwargs: vp.az = (vp.az - float(kwargs['right'])) % 360
    return f"Turned sphere. az now {vp.az:.1f}°."


def op_tilt(scene, kwargs):
    """
    tilt toward=N              -- tip the scene-sphere top toward you
    tilt away=N                -- tip the scene-sphere top away from you
    tilt target=<id> toward=N  -- tip an object's local sphere toward you (rotate around its X axis)
    tilt target=<id> away=N    -- tip an object's local sphere away

    Without target: tilts the whole scene in your hands (viewpoint el).
    With target: tips that object on its own left-right axis.
    Relative -- always a delta. Clamped to -89..89 for scene sphere.
    """
    if 'target' in kwargs:
        obj = resolve_target(scene, kwargs['target'])
        delta = float(kwargs.get('toward', kwargs.get('forward', kwargs.get('down', 0)))) - \
                float(kwargs.get('away',   kwargs.get('back',    kwargs.get('up',   0))))
        obj.transform.rotate.x = (obj.transform.rotate.x + delta) % 360
        return f"Tilted '{kwargs['target']}' {'toward' if delta>0 else 'away'} {abs(delta):.1f}°. Local X now {obj.transform.rotate.x:.1f}°."
    vp = scene.active_viewpoint()
    _toward = float(kwargs.get('toward', kwargs.get('forward', kwargs.get('down', 0))))
    _away   = float(kwargs.get('away',   kwargs.get('back',    kwargs.get('up',   0))))
    if _toward: vp.el = max(-89, min(89, vp.el + _toward))
    if _away:   vp.el = max(-89, min(89, vp.el - _away))
    return f"Tilted sphere. el now {vp.el:.1f}°."


def op_zoom(scene, kwargs):
    """
    zoom in=N   -- bring the scene closer (scale multiplied by N, or +N if small)
    zoom out=N  -- push the scene further away (scale divided by N, or -N if small)

    Changes how much of the scene fills your felt space.
    Like pulling clay closer to your hands or pushing it further away.
    Relative -- multiplicative delta. zoom in=2 doubles the apparent size.
    """
    vp = scene.active_viewpoint()
    n = float(kwargs.get('in', kwargs.get('out', 1.0)))
    if n <= 0: return "zoom: N must be positive."
    if 'in'  in kwargs: vp.scale = vp.scale * n
    if 'out' in kwargs: vp.scale = vp.scale / n
    return f"Zoomed sphere. scale now {round(vp.scale, 4)}."


def op_nudge(scene, kwargs):
    """
    Pan the scene centre or move an object -- alias for 'move' with no target.

    nudge left/right/up/down/toward/away=N       -- pan the scene centre
    nudge target=<id> left/right/up/down/away=N  -- move object
        -- move an object in your felt space
           directions are relative to current scene-sphere orientation (viewpoint az/el)
           so 'nudge left' always moves left in YOUR space regardless of how the scene is rotated

    Relative -- always a delta. Units match scene units.
    """
    import math as _m
    vp = scene.active_viewpoint()
    az_r = _m.radians(vp.az)
    # Right vector in world space (perpendicular to az, horizontal)
    r_x = _m.cos(az_r); r_z = _m.sin(az_r)
    # Forward vector (into the scene from you)
    f_x = -r_z; f_z = r_x
    dx = dy = dz = 0.0
    if 'right'  in kwargs: n=float(kwargs['right']);  dx += r_x*n; dz += r_z*n
    if 'left'   in kwargs: n=float(kwargs['left']);   dx -= r_x*n; dz -= r_z*n
    if 'up'     in kwargs: dy += float(kwargs['up'])
    if 'down'   in kwargs: dy -= float(kwargs['down'])
    if 'toward' in kwargs: n=float(kwargs['toward']); dx += f_x*n; dz += f_z*n
    if 'away'   in kwargs: n=float(kwargs['away']);   dx -= f_x*n; dz -= f_z*n

    if 'target' in kwargs:
        # Move object in felt space
        obj = resolve_target(scene, kwargs['target'])
        # Convert world-space delta to object's local space
        parent = scene.find_parent(kwargs['target'])
        if parent:
            try:
                parent_M = scene._world_matrix(parent)
                # Apply delta in world space then convert to local
                wp = scene.world_pos(obj)
                new_wp = Vec3(wp.x+dx, wp.y+dy, wp.z+dz)
                local_pos = parent_M.inverse() * new_wp
                obj.transform.translate = local_pos
                return f"Nudged '{kwargs['target']}'. Felt: {scene._felt_desc(obj, vp)}."
            except Exception:
                pass
        # Top-level object -- world = local
        t = obj.transform.translate
        obj.transform.translate = Vec3(t.x+dx, t.y+dy, t.z+dz)
        return f"Nudged '{kwargs['target']}'. New position: ({obj.transform.translate.x:.2f}, {obj.transform.translate.y:.2f}, {obj.transform.translate.z:.2f})."
    else:
        la = vp.look_at if vp.look_at else Vec3(0, 0, 0)
        vp.look_at = Vec3(la.x+dx, la.y+dy, la.z+dz)
        return f"Nudged centre to ({vp.look_at.x:.2f}, {vp.look_at.y:.2f}, {vp.look_at.z:.2f})."

def op_roll(scene, kwargs):
    """
    roll left=N              -- lean the scene-sphere left (roll the whole scene)
    roll right=N             -- lean the scene-sphere right
    roll target=<id> left=N  -- lean an object left on its own front-back axis (local Z)
    roll target=<id> right=N -- lean an object right

    Without target: rolls the whole scene (currently not stored in viewpoint -- future feature).
    With target: rotates the object around its local Z axis (lean left/right).
    Relative -- always a delta.
    """
    if 'target' in kwargs:
        obj = resolve_target(scene, kwargs['target'])
        delta = float(kwargs.get('right', 0)) - float(kwargs.get('left', 0))
        obj.transform.rotate.z = (obj.transform.rotate.z + delta) % 360
        return f"Rolled '{kwargs['target']}' {'right' if delta>0 else 'left'} {abs(delta):.1f}°. Local Z now {obj.transform.rotate.z:.1f}°."
    vp = scene.active_viewpoint()
    delta = float(kwargs.get('right', 0)) - float(kwargs.get('left', 0))
    vp.roll = (vp.roll + delta) % 360
    return f"Rolled sphere {'right' if delta>0 else 'left'} {abs(delta):.1f}°. Roll now {vp.roll:.1f}°."




def op_group(scene, kwargs):
    """
    group id=<group_id> members=id1,id2,id3

    Creates a null container and attaches named objects to it.
    Move or scale the group to affect all members together.
    """
    group_id = require(kwargs, 'id')
    members  = [m.strip() for m in require(kwargs, 'members').split(',')]
    for mid in members: resolve_target(scene, mid)   # validate all exist first
    group = SceneObject(scene.unique_id(group_id), 'null')
    group.tags.append('group')
    scene.objects.append(group)
    moved = []
    for mid in members:
        obj    = scene.find_object(mid)
        parent = scene.find_parent(mid)
        (parent.children if parent else scene.objects).remove(obj)
        group.children.append(obj)
        moved.append(mid)
    return (f"Group '{group.id}' created containing: {', '.join(moved)}. "
            f"Move or scale '{group.id}' to affect all members.")


def op_snap(scene, kwargs):
    """
    snap target=<id> to=<other_id> [gap=n]

    Moves 'target' so its surface just touches the surface of 'other'.
    Does NOT reparent -- target stays in its current hierarchy.
    gap= adds extra clearance (default 0). Negative gap = slight overlap.

    This is the plasticine press gesture: bring two pieces together until
    they just touch, without merging or overlapping.
    """
    target_id = require(kwargs, 'target')
    other_id  = require(kwargs, 'to')
    gap       = float(kwargs.get('gap', 0.0))

    target = resolve_target(scene, target_id)
    other  = resolve_target(scene, other_id)

    target_world = scene.world_pos(target)
    target_r     = scene.world_radius(target)

    # Find closest point on other's surface from target's centre
    sp, normal = _surface_point(scene, other, target_world)

    # Place target centre at: surface_point + normal * (target_radius + gap)
    # This puts target's surface exactly touching other's surface
    new_world = dm_Vec3_add(sp, dm_Vec3_scale(normal, target_r + gap))

    # Convert new world position to target's parent local space
    parent = scene.find_parent(target_id)
    if parent:
        try:
            local_pos = scene._world_matrix(parent).inverse() * new_world
        except Exception:
            local_pos = new_world
    else:
        local_pos = new_world

    target.transform.translate = local_pos
    wp = scene.world_pos(target)
    return (f"'{target_id}' snapped to surface of '{other_id}'. "
            f"Gap: {gap}. "
            f"World: ({wp.x:.3f}, {wp.y:.3f}, {wp.z:.3f}).")


def _vec3_op(a, b, op):
    """Helper for Vec3 arithmetic without importing math."""
    if op == '+': return Vec3(a.x+b.x, a.y+b.y, a.z+b.z)
    if op == '-': return Vec3(a.x-b.x, a.y-b.y, a.z-b.z)

def dm_Vec3_add(a, b):   return Vec3(a.x+b.x, a.y+b.y, a.z+b.z)
def dm_Vec3_scale(v, s): return Vec3(v.x*s, v.y*s, v.z*s)


def op_align(scene, kwargs):
    """target=<id> axis=x|y|z mirror_of=<source_id>

    Adjusts target's position and rotation so it is the mirror image of
    source in world space across the specified axis plane.

    Unlike 'mirror', which creates a new object, 'align' moves an existing
    object. Useful for correcting an object after manual adjustment.

    Example:
      align target=ear_right axis=x mirror_of=ear_left
    """
    target_id = require(kwargs, 'target')
    source_id = require(kwargs, 'mirror_of')
    axis      = require(kwargs, 'axis').lower()
    if axis not in ('x', 'y', 'z'):
        raise ValueError(f"axis must be x, y, or z. Got: '{axis}'")

    target = resolve_target(scene, target_id)
    source = resolve_target(scene, source_id)

    # Get source world position and negate the mirror axis
    src_wp = scene.world_pos(source)
    if axis == 'x':   new_wp = Vec3(-src_wp.x,  src_wp.y,  src_wp.z)
    elif axis == 'y': new_wp = Vec3( src_wp.x, -src_wp.y,  src_wp.z)
    else:             new_wp = Vec3( src_wp.x,  src_wp.y, -src_wp.z)

    # Convert new world position to target's parent local space
    parent = scene.find_parent(target_id)
    if parent:
        try:
            local_pos = scene._world_matrix(parent).inverse() * new_wp
        except Exception:
            local_pos = new_wp
    else:
        local_pos = new_wp
    target.transform.translate = local_pos

    # Mirror rotation: negate the two non-mirror axes (same as op_mirror)
    src_r = source.transform.rotate
    if axis == 'x':
        target.transform.rotate = Transform.norm_rot(Vec3( src_r.x, -src_r.y, -src_r.z))
    elif axis == 'y':
        target.transform.rotate = Transform.norm_rot(Vec3(-src_r.x,  src_r.y, -src_r.z))
    else:
        target.transform.rotate = Transform.norm_rot(Vec3(-src_r.x, -src_r.y,  src_r.z))

    wp = scene.world_pos(target)
    return (f"'{target_id}' aligned as mirror of '{source_id}' across {axis}-axis. "
            f"World: ({wp.x:.3f}, {wp.y:.3f}, {wp.z:.3f}).")


def op_mirror(scene, kwargs):
    """
    mirror target=<id> axis=x|y|z [as=<new_id>]

    Mirrors an object and all its children across the specified axis.
    Creates a new object with negated position on that axis.
    Rotations on the other two axes are also negated (correct chirality).

    Example:
      mirror target=ear_left axis=x as=ear_right
    """
    target_id   = require(kwargs, 'target')
    axis        = require(kwargs, 'axis').lower()
    obj         = resolve_target(scene, target_id)
    if axis not in ('x', 'y', 'z'):
        raise ValueError(f"axis must be x, y, or z. Got: '{axis}'")
    new_id_base = opt(kwargs, 'as', f"{target_id}_mirror")
    new_id      = scene.unique_id(new_id_base)

    new_obj = copy.deepcopy(obj)

    def mirror_obj(o):
        t = o.transform.translate
        if axis == 'x':
            t.x = -t.x
            o.transform.rotate.y = -o.transform.rotate.y
            o.transform.rotate.z = -o.transform.rotate.z
        elif axis == 'y':
            t.y = -t.y
            o.transform.rotate.x = -o.transform.rotate.x
            o.transform.rotate.z = -o.transform.rotate.z
        elif axis == 'z':
            t.z = -t.z
            o.transform.rotate.x = -o.transform.rotate.x
            o.transform.rotate.y = -o.transform.rotate.y
        if o.attach_point:
            ap = o.attach_point
            if axis == 'x': ap.x = -ap.x
            elif axis == 'y': ap.y = -ap.y
            elif axis == 'z': ap.z = -ap.z
        for child in o.children: mirror_obj(child)

    mirror_obj(new_obj)

    def rename_tree(o, old_base, new_base):
        if o.id.startswith(old_base):
            o.id = scene.unique_id(o.id.replace(old_base, new_base, 1))
        else:
            o.id = scene.unique_id(o.id + '_m')
        for child in o.children: rename_tree(child, old_base, new_base)

    new_obj.id = new_id
    for child in new_obj.children: rename_tree(child, target_id, new_id)

    parent = scene.find_parent(target_id)
    if parent: parent.children.append(new_obj)
    else: scene.objects.append(new_obj)

    wp = scene.world_pos(new_obj)
    return (f"Mirrored '{target_id}' across {axis}-axis as '{new_id}'. "
            f"World position: ({wp.x:.2f}, {wp.y:.2f}, {wp.z:.2f}).")


def op_pose(scene, kwargs):
    """
    pose name=<pose_name> [root=<id>]      - save current transform state
    pose restore=<pose_name> [root=<id>]   - restore saved transform state

    Saves or restores the transform state (translate, rotate, scale) of an
    entire object subtree. 'root' defaults to all top-level objects if omitted.

    Lets you build one rig and show it in multiple positions without
    destructively editing the file.

    Examples:
      pose name=standing
      pose name=swimming root=body
      pose restore=standing
    """
    import copy as _copy

    def collect_subtree(obj):
        result = [obj]
        for child in obj.children:
            result.extend(collect_subtree(child))
        return result

    if 'restore' in kwargs:
        pname = kwargs['restore']
        if pname not in scene.poses:
            known = ', '.join(sorted(scene.poses.keys())) or 'none'
            raise ValueError(f"No pose named '{pname}'. Known poses: {known}.")
        pdata = scene.poses[pname]
        restored = []
        for oid, (t, r, s) in pdata.items():
            obj = scene.find_object(oid)
            if obj:
                obj.transform.translate = _copy.copy(t)
                obj.transform.rotate    = Transform.norm_rot(_copy.copy(r))
                obj.transform.scale     = _copy.copy(s)
                restored.append(oid)
        return f"Pose '{pname}' restored. {len(restored)} objects updated."

    elif 'name' in kwargs:
        pname = kwargs['name']
        root_id = kwargs.get('root')
        if root_id:
            root_obj = resolve_target(scene, root_id)
            objs = collect_subtree(root_obj)
        else:
            objs = list(scene.all_objects())
        pdata = {}
        for obj in objs:
            pdata[obj.id] = (
                Vec3(obj.transform.translate.x,
                     obj.transform.translate.y,
                     obj.transform.translate.z),
                Vec3(obj.transform.rotate.x,
                     obj.transform.rotate.y,
                     obj.transform.rotate.z),
                Vec3(obj.transform.scale.x,
                     obj.transform.scale.y,
                     obj.transform.scale.z),
            )
        scene.poses[pname] = pdata
        overwrite = ' (overwrote existing)' if pname in scene.poses else ''
        return f"Pose '{pname}' saved.{overwrite} {len(pdata)} objects stored."

    else:
        raise ValueError("Specify name=<pose_name> to save, or restore=<pose_name> to restore.")


def op_clone(scene, kwargs):
    """
    clone target=<id> as=<new_id>

    Deep copy of an object and all its children, with a new ID.
    The clone is placed at the same level as the original.
    All parameters, materials, transforms, and children are preserved.

    Example:
      clone target=pupil_left as=pupil_right
      move target=pupil_right to=3.2,2.8,10.9
    """
    target_id   = require(kwargs, 'target')
    new_id_base = require(kwargs, 'as')
    obj         = resolve_target(scene, target_id)

    new_obj    = copy.deepcopy(obj)
    new_obj.id = scene.unique_id(new_id_base)

    def rename_children(o):
        for child in o.children:
            child.id = scene.unique_id(child.id + '_c')
            rename_children(child)

    rename_children(new_obj)

    parent = scene.find_parent(target_id)
    if parent: parent.children.append(new_obj)
    else: scene.objects.append(new_obj)

    return f"Cloned '{target_id}' as '{new_obj.id}'. Move or modify the clone independently."


def op_text(scene, kwargs):
    """Add a text label. Use 'add type=text' -- it is more flexible.

    add type=text id=<id> content=<string> [size=N] [fill=#hex]

    Text renders as a flat billboard label in all export formats.
    Essential for annotating anatomy and screen-reader accessibility.
    """
    return ("Use 'add type=text' instead: add type=text id=<id> content=<string> size=N. ")


# -- Pull/dent deformation (clay press gesture) ----------------------------
def op_pull(scene, kwargs):
    """
    pull target=<id> into=<id> [depth=<n>]
    dent target=<id> into=<id> [depth=<n>]

    Presses 'target' into 'into' by 'depth' units past the point of surface contact.
    This is the plasticine press gesture -- two lumps of clay meeting and merging.

    The visual merge (smooth organic blending at the contact zone) is handled
    automatically by the blob{} renderer when objects overlap.

    depth=0  means surfaces just touching (same as snap)
    depth=2  means 2 units of interpenetration (clay pressed together)
    depth<0  means gap (pull apart instead of together)

    The target stays in its current parent hierarchy. Only its translate is adjusted.
    """
    import math as _math

    target_id = require(kwargs, 'target')
    into_id   = require(kwargs, 'into')
    depth     = float(kwargs.get('depth', 1.0))

    target = resolve_target(scene, target_id)
    into   = resolve_target(scene, into_id)

    target_world = scene.world_pos(target)
    into_world   = scene.world_pos(into)
    target_r     = scene.world_radius(target)
    into_r       = scene.world_radius(into)

    # Direction from into-centre to target-centre (approach vector)
    dx = target_world.x - into_world.x
    dy = target_world.y - into_world.y
    dz = target_world.z - into_world.z
    dist = _math.sqrt(dx*dx + dy*dy + dz*dz)

    if dist < 1e-6:
        # Objects at same position -- push target along Y
        dx, dy, dz, dist = 0, 1, 0, 1

    nx, ny, nz = dx/dist, dy/dist, dz/dist

    # Place target so its surface is 'depth' units inside 'into'
    # Contact point: into_centre + into_r * normal
    # Target centre at: contact_point + target_r * normal - depth * normal
    #                 = into_centre + (into_r + target_r - depth) * normal
    new_dist = into_r + target_r - depth
    new_world = Vec3(
        into_world.x + nx * new_dist,
        into_world.y + ny * new_dist,
        into_world.z + nz * new_dist,
    )

    # Convert to parent local space
    parent = scene.find_parent(target_id)
    if parent:
        try:
            local_pos = scene._world_matrix(parent).inverse() * new_world
        except Exception:
            local_pos = new_world
    else:
        local_pos = new_world

    target.transform.translate = local_pos
    wp = scene.world_pos(target)

    actual_dist = _math.sqrt((wp.x-into_world.x)**2 +
                             (wp.y-into_world.y)**2 +
                             (wp.z-into_world.z)**2)
    actual_penetration = into_r + target_r - actual_dist

    verb = "dented" if depth > 0 else "pulled away from"
    return (f"'{target_id}' {verb} '{into_id}' by {abs(depth):.2f} units. "
            f"Penetration: {actual_penetration:.3f} units. "
            f"Use 'press target={target_id} into={into_id}' to record deformation in the DMS file. "
            f"World: ({wp.x:.3f}, {wp.y:.3f}, {wp.z:.3f}).")


def op_press(scene, kwargs):
    """
    press target=<id> into=<id> [depth=<n>]

    Presses 'target' into 'into', deforming 'into' to accept 'target'.
    This is the core clay operation -- like pressing your thumb into a ball of clay.

    What happens:
      - 'target' is moved so it overlaps 'into' by 'depth' units
      - 'into' is tagged deformed_by=<target_id> (recorded in DMS file)
      - 'target' is tagged pressed_into=<into_id> (recorded in DMS file)
      - At render time, POV-Ray emits: difference { into target }
        which carves the target-shaped socket out of into's surface

    depth=0   surfaces just touching (records the relationship, no overlap)
    depth=2   2 units of penetration (deeper socket)
    depth=-1  target pulled back 1 unit from surface (gap, but relationship recorded)

    To undo: use 'unpress target=<id>'

    Examples:
      press target=eyeball_left into=skull depth=2
      press target=nose_tip into=skull depth=1.5
    """
    import math as _math

    target_id = require(kwargs, 'target')
    into_id   = require(kwargs, 'into')
    depth     = float(kwargs.get('depth', 1.0))

    target = resolve_target(scene, target_id)
    into   = resolve_target(scene, into_id)

    # Move target to the press position
    target_world = scene.world_pos(target)
    into_world   = scene.world_pos(into)
    target_r     = scene.world_radius(target)
    into_r       = scene.world_radius(into)

    dx = target_world.x - into_world.x
    dy = target_world.y - into_world.y
    dz = target_world.z - into_world.z
    dist = _math.sqrt(dx*dx + dy*dy + dz*dz)

    if dist < 1e-6:
        dx, dy, dz, dist = 0, 0, 1, 1  # default: press along Z

    nx, ny, nz = dx/dist, dy/dist, dz/dist
    new_dist = into_r + target_r - depth
    new_world = Vec3(
        into_world.x + nx * new_dist,
        into_world.y + ny * new_dist,
        into_world.z + nz * new_dist,
    )

    parent = scene.find_parent(target_id)
    if parent:
        try:
            local_pos = scene._world_matrix(parent).inverse() * new_world
        except Exception:
            local_pos = new_world
    else:
        local_pos = new_world
    target.transform.translate = local_pos

    # Record deformation in DMS tags -- explicit, never implicit

    # If target was previously pressed into something else, remove that deformed_by tag
    for old_tag in [t for t in target.tags if t.startswith('pressed_into=')]:
        old_base_id = old_tag.split('=', 1)[1]
        if old_base_id != into_id:
            old_base = scene.find_object(old_base_id)
            if old_base:
                old_base.tags = [t for t in old_base.tags
                                 if t != f'deformed_by={target_id}']

    deform_tag = f'deformed_by={target_id}'
    press_tag  = f'pressed_into={into_id}'

    if deform_tag not in into.tags:
        into.tags.append(deform_tag)
    target.tags = [t for t in target.tags if not t.startswith('pressed_into=')]
    target.tags.append(press_tag)

    wp = scene.world_pos(target)
    actual_penetration = into_r + target_r - _math.sqrt(
        (wp.x-into_world.x)**2 + (wp.y-into_world.y)**2 + (wp.z-into_world.z)**2)

    return (f"'{target_id}' pressed {depth:.2f} units into '{into_id}'. "
            f"Penetration: {actual_penetration:.3f} units. "
            f"Tags set: '{into_id}' deformed_by={target_id}, '{target_id}' pressed_into={into_id}. "
            f"POV-Ray will render difference{{ {into_id} {target_id} }}.")


def op_unpress(scene, kwargs):
    """
    unpress target=<id>

    Removes the deformation relationship between 'target' and whatever it
    was pressed into. Clears the pressed_into tag on target and the
    corresponding deformed_by tag on the receiving object.

    Does NOT move target back to its original position -- use 'move' if needed.

    Example:
      unpress target=eyeball_left
    """
    target_id = require(kwargs, 'target')
    target    = resolve_target(scene, target_id)

    # Find what this target was pressed into
    press_tags = [t for t in target.tags if t.startswith('pressed_into=')]
    if not press_tags:
        return f"'{target_id}' has no pressed_into relationship to remove."

    removed = []
    for pt in press_tags:
        into_id = pt.split('=', 1)[1]
        into_obj = scene.find_object(into_id)
        if into_obj:
            deform_tag = f'deformed_by={target_id}'
            if deform_tag in into_obj.tags:
                into_obj.tags.remove(deform_tag)
                removed.append(f"removed deformed_by={target_id} from '{into_id}'")
        target.tags.remove(pt)
        removed.append(f"removed pressed_into={into_id} from '{target_id}'")

    if not target.tags:
        target.tags = []  # ensure never truly empty -- serialiser writes 'null'

    return f"Unpress complete: {'; '.join(removed)}."


# ═════════════════════════════════════════════════════════════════════════════
# § OPERATIONS REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

OPERATIONS = {
    'add':       op_add,
    'color':     op_color,
    'colour':    op_color,     # British spelling alias
    'material':  op_material,  # named material presets
    'move':      op_move,
    'rotate':    op_rotate,
    'scale':     op_scale,
    'deform':    op_deform,
    'attach':    op_attach,
    'detach':    op_detach,
    'delete':    op_delete,
    'remove':    op_delete,    # alias
    'rename':    op_rename,
    'tag':       op_tag,
    'param':     op_param,
    'turn':      op_turn,       # spin sphere left/right (yaw delta)
    'yaw':       op_turn,       # alias: turn
    'tilt':      op_tilt,       # tip sphere toward/away (pitch delta)
    'pitch':     op_tilt,       # alias: tilt
    'zoom':      op_zoom,       # bring scene closer/further (scale delta)
    'push':      op_zoom,       # alias: zoom (push away / pull towards)
    'nudge':     op_nudge,      # shift scene centre or object in felt space
    'roll':      op_roll,       # lean sphere or object left/right (local Z)
    'viewpoint': op_viewpoint,
    'group':     op_group,
    'mirror':    op_mirror,
    'clone':     op_clone,
    'snap':      op_snap,
    'align':     op_align,
    'pose':      op_pose,       # move target to touch surface of another object
    # -- PENDING IMPLEMENTATION --
    'comment':   op_comment,    # history section marker
    'measure':   op_measure,    # world-space distance between two objects
    'text':      op_text,       # text primitive (billboard label)
    'pull':      op_pull,       # plasticine pull/dent at intersection
    'dent':      op_pull,       # alias for pull
    'dent':      op_pull,       # alias for pull
    'press':     op_press,      # clay deformation: records deformed_by in DMS
    'unpress':   op_unpress,    # remove press relationship
}


# ═════════════════════════════════════════════════════════════════════════════

"""DwarvenModeller -- all exporters: SVG, POV, PNG, OBJ, STL, glTF, braille."""
from __future__ import annotations
import math, os, subprocess, tempfile
from .constants import *
from .math_utils import *
from .scene import *
from .primitives import *
from .feedback import *

# -- Shared projection helper ------------------------------------------------─




__all__ = ['_proj_for_export', '_skip_in_emit', 'export_svg', '_camera_dist', 'export_povray', '_viewpoint_export_matrix', 'export_obj', 'export_stl', 'export_x3d', 'export_gltf', 'export_css3d', 'export_spatial_text', 'export_svg_povray', 'export_svg_trace', 'export_png_native', 'export_png', '_export_png_povray', '_export_disabled', '_BRAILLE_MAP', '_BRAILLE_NUM_IND', '_text_to_braille', '_build_scene_text', 'export_braille_text', 'export_braille_render', 'EXPORT_FORMATS', 'run_export', 'ansi_render']

def _proj_for_export(vp):
    """Return (proj, depth, face_nz) functions for the given viewpoint.

    Uses proper az/el rotation matrix - not a shear approximation.
    The old shear form -(y - rz*sin(el)) breaks at high elevations (el=90).

    If vp.pos is set, derives az/el from pos relative to look_at.
    """
    az_deg, el_deg = vp.az, vp.el

    if vp.pos:
        p  = vp.pos
        lx = vp.look_at.x if vp.look_at else 0
        ly = vp.look_at.y if vp.look_at else 0
        lz = vp.look_at.z if vp.look_at else 0
        ox, oy, oz = p.x - lx, p.y - ly, p.z - lz
        dist = math.sqrt(ox**2 + oy**2 + oz**2)
        if dist > 1e-10:
            el_deg = math.degrees(math.asin(max(-1.0, min(1.0, oy / dist))))
            az_deg = math.degrees(math.atan2(ox, -oz))

    az = math.radians(az_deg)
    el = math.radians(el_deg)
    sc = vp.scale

    def proj(v):
        x, y, z = v
        # Step 1: rotate around Y by az
        rx =  x*math.cos(az) - z*math.sin(az)
        rz =  x*math.sin(az) + z*math.cos(az)
        # Step 2: rotate around horizontal axis by el (proper rotation)
        ry2 = y*math.cos(el) - rz*math.sin(el)
        return (-rx * sc, -ry2 * sc)  # negate rx: EAST(+X) appears on RIGHT

    # Camera sits at distance `dist` in the NEGATIVE view direction.
    # View direction in world-rotated space = (0, sin(el), cos(el)).
    # Camera depth coordinate = -dist (negative of view axis).
    # Object depth coordinate = y*sin(el) + rz*cos(el).
    # Distance from camera = object_depth - camera_depth = object_depth + dist.
    # Since dist is constant, sort by object_depth alone is equivalent.
    # But we need: further from camera → painted first (reverse=True).
    # Further from camera = larger (object_depth - camera_depth) = larger (object_depth + dist).
    # Camera is at NEGATIVE view axis → objects in POSITIVE direction are further away.
    # So reverse=True (higher depth = further = painted first) is correct.
    def depth(v):
        x, y, z = v
        rx =  x*math.cos(az) - z*math.sin(az)
        rz =  x*math.sin(az) + z*math.cos(az)
        return y*math.sin(el) + rz*math.cos(el)

    # Camera direction vector (unit vector FROM camera TOWARD scene)
    _cam_dir_x = -math.cos(el) * math.sin(az)
    _cam_dir_y = -math.sin(el)
    _cam_dir_z =  math.cos(el) * math.cos(az)

    def face_nz(tri):
        """Return positive if face is visible from camera (front-facing).
        Uses 3D world-space normal dot camera-direction - correct for all angles.
        Also returns the projected 2D cross product magnitude for screen-area tests.
        """
        a, b, c = tri
        # World-space face normal via cross product
        ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
        ac = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
        nx = ab[1]*ac[2] - ab[2]*ac[1]
        ny = ab[2]*ac[0] - ab[0]*ac[2]
        nz = ab[0]*ac[1] - ab[1]*ac[0]
        # Dot with camera direction - negative means face points TOWARD camera = visible
        dot = nx*_cam_dir_x + ny*_cam_dir_y + nz*_cam_dir_z
        # Return magnitude (for screen area check) with sign flipped so positive = visible
        return -dot

    return proj, depth, face_nz


def _skip_in_emit(obj):
    """True if this object should be skipped in analytical exporters (null/group)."""
    return obj.type == 'null' or 'group' in obj.tags


# -- SVG ----------------------------------------------------------------------

def export_svg(scene, out_path, size=512):
    """Export scene as SVG. Uses camera-space BSP for correct painter ordering.

    #doc ARCHITECTURE: Mirrors tscircuit/simple-3d-svg.
    Pipeline: world coords → camera space → back-face cull → BSP sort → project 2D → render.
    Camera is at origin in camera space, simplifying BSP camera-side tests.

    #doc PROJECTION QUIRK: Orthographic projection (not perspective).
    Camera basis: fwd = normalize(lookAt - camPos), rgt = cross(worldUp, fwd),
    up = cross(rgt, fwd). Note: cross(worldUp, fwd) NOT cross(fwd, worldUp) -
    the order matters for handedness. Getting this wrong inverts left/right AND
    causes vertical flip at non-zero elevations.
    proj2d: screen_x = cam_x * scale, screen_y = cam_y * scale (NO Y-flip needed
    because the camera basis already handles orientation correctly).

    #doc BACK-FACE CULL: Uses camera-space dot product: vdot(normal, cam_vertex) >= 0
    means back-facing (normal points away from camera at origin). This is correct
    for orthographic projection. Faces with vdot < 0 are front-facing and visible.

    #doc SCREEN-AREA CULL: Projected triangles with screen area < 2.0 sq units
    are discarded as degenerate. This removes most edge faces of thin slabs
    (document pages, die colour faces) but NOT all - see KNOWN LIMITATION.

    #doc KNOWN LIMITATION: Thin slabs at oblique angles can show inner faces
    (the face pointing toward the object interior that also happens to face camera).
    This is geometrically correct but visually wrong for die/document construction
    patterns. The svg_trace pipeline (POV → vtracer) handles this correctly.
    """
    vp = scene.active_viewpoint()

    # -- Colour helpers --------------------------------------------------------
    def hex_to_rgb(h):
        h = h.strip().lstrip('#')
        if len(h) == 3: h = h[0]*2+h[1]*2+h[2]*2
        return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)

    def shade_face(fill, cam_normal):
        """Shade fill colour by face normal Z in camera space (simple-3d-svg style)."""
        try:
            r,g,b = hex_to_rgb(fill)
        except Exception:
            return fill
        # Normalise cam_normal
        nx,ny,nz = cam_normal
        mag = math.sqrt(nx*nx+ny*ny+nz*nz)
        if mag < 1e-12: return fill
        nz /= mag
        # nz > 0 → face points toward camera → lighten slightly
        # nz < 0 → face points away → darken (shouldn't be visible, but handle anyway)
        # Use ambient 0.6 + diffuse 0.4 * |nz|
        # Light direction: slightly above camera (0, 0.3, 1) normalised in cam space
        lx,ly,lz = 0.0, 0.3, 1.0
        lm = math.sqrt(lx*lx+ly*ly+lz*lz)
        lx,ly,lz = lx/lm, ly/lm, lz/lm
        nx2,ny2,nz2 = nx/mag*mag, ny/mag*mag, nz  # already normalised above
        nx2 = cam_normal[0]/mag; ny2 = cam_normal[1]/mag
        diffuse = max(0.0, nx2*lx + ny2*ly + nz2*lz)
        brightness = 0.55 + 0.45 * diffuse
        r2 = min(255, int(r * brightness))
        g2 = min(255, int(g * brightness))
        b2 = min(255, int(b * brightness))
        return f'#{r2:02x}{g2:02x}{b2:02x}'

    # -- Camera basis vectors --------------------------------------------------
    # LOCKED CAMERA approach: camera fixed at <0, 0, -dist>.
    # Scene world points are pre-rotated by az(Y) then el(X) before projection.
    # Eliminates gimbal lock. Matches native renderer and POV approach.
    _dist = _camera_dist(scene, vp)

    def vsub(a,b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
    def vadd(a,b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
    def vdot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
    def vcross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    def vnorm(a):
        m=math.sqrt(vdot(a,a)); return (a[0]/m,a[1]/m,a[2]/m) if m>1e-12 else (0,0,1)
    def vscale(a,s): return (a[0]*s,a[1]*s,a[2]*s)

    # Pre-rotation matrices: az around Y (clockwise), then el around rotated X
    _az_r  = math.radians(vp.az)
    _el_r  = math.radians(-vp.el if PITCH_INVERSION else vp.el)
    _cos_az, _sin_az = math.cos(_az_r), math.sin(_az_r)
    _cos_el, _sin_el = math.cos(_el_r), math.sin(_el_r)

    # look_at offset
    _lx = vp.look_at.x if vp.look_at else 0.0
    _ly = vp.look_at.y if vp.look_at else 0.0
    _lz = vp.look_at.z if vp.look_at else 0.0

    def rotate_point(p):
        """Rotate world point by az(Y) then el(X), matching native _view() convention."""
        x, y, z = p[0]-_lx, p[1]-_ly, p[2]-_lz
        # az rotation around Y (clockwise: use +sin for DM convention)
        rx  =  x*_cos_az + z*_sin_az
        rz  = -x*_sin_az + z*_cos_az
        # el rotation around X
        ry2 =  y*_cos_el - rz*_sin_el
        rz2 =  y*_sin_el + rz*_cos_el
        return (rx, ry2, rz2)

    # Camera fixed at <0, 0, -dist> looking at origin
    cam_pos = (0.0, 0.0, -_dist)
    look_at = (0.0, 0.0, 0.0)
    fwd = (0.0, 0.0, 1.0)   # fixed: camera looks along +Z
    rgt = (1.0, 0.0, 0.0)   # fixed: right is +X
    up  = (0.0, 1.0, 0.0)   # fixed: up is +Y

    def to_cam(p):
        """Rotate world point to camera space. Camera at origin looking along +Z."""
        return rotate_point(p)

    def proj2d(pc, sc):
        """Project camera-space point to 2D SVG coords (orthographic, scaled).
        Y is negated: camera-space +Y = up, but SVG +Y = down.
        Roll applied as 2D rotation of screen coords after projection."""
        sx, sy = pc[0]*sc, -pc[1]*sc
        if vp.roll:
            _rr = math.radians(vp.roll)
            _cr, _sr = math.cos(_rr), math.sin(_rr)
            return (sx*_cr - sy*_sr, sx*_sr + sy*_cr)
        return (sx, sy)

    # -- Tessellate and transform to camera space ------------------------------
    pairs = tessellate_scene(scene, subdivisions=2)
    W_scene = None  # will compute from projected extents

    # Compute scale: use vp.scale, adjusted so scene fits nicely
    sc = vp.scale

    raw_faces = []  # list of (cam_verts, pts_2d, fill, stroke, sw, opacity)
    for tris, mat in pairs:
        for tri in tris:
            # Transform to camera space
            cam_tri = tuple(to_cam(v) for v in tri)
            # Back-face cull in camera space.
            # Camera looks along +Z (fwd = (0,0,1)).
            # Face is front-facing if its normal has a negative Z component
            # (normal points toward camera = toward -Z).
            # Use cross product of camera-space edges; check sign of Z component.
            e1 = vsub(cam_tri[1], cam_tri[0])
            e2 = vsub(cam_tri[2], cam_tri[0])
            n  = vcross(e1, e2)
            # n.z < 0 means normal points toward camera (-Z direction) = front-facing
            if n[2] >= 0:
                continue  # back-face
            # Shade fill by face normal in camera space
            shaded_fill = shade_face(mat.fill, n)
            pts2 = tuple(proj2d(v, sc) for v in cam_tri)
            # Screen area cull - skip degenerate/tiny faces
            a,b,c = pts2
            area = abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))*0.5
            if area < 2.0:
                continue
            raw_faces.append((cam_tri, pts2, shaded_fill, mat.stroke,
                               mat.stroke_width, mat.opacity))

    if not raw_faces:
        return "Nothing visible from current viewpoint."

    if not raw_faces:
        return "Nothing visible from current viewpoint."

    # -- BSP sort in camera space ----------------------------------------------
    # Camera is at origin in camera space - simplifies cameraSide check.
    EPS = 1e-6

    def bsp_build(faces):
        if not faces: return None
        pivot = faces[0]
        cam_v, pts2, f, s, sw, op = pivot
        p0,p1,p2 = cam_v[0],cam_v[1],cam_v[2]
        normal = vcross(vsub(p1,p0), vsub(p2,p0))
        front_list, back_list = [], []
        for face in faces[1:]:
            fv = face[0]
            dists = [vdot(normal, vsub(v, p0)) for v in fv]
            pos = sum(1 for d in dists if d >  EPS)
            neg = sum(1 for d in dists if d < -EPS)
            if not pos and not neg:
                front_list.append(face)  # coplanar
            elif not neg:
                front_list.append(face)
            elif not pos:
                back_list.append(face)
            else:
                # Split face by plane
                fc_cam, fb_cam = [], []
                fc_pts, fb_pts = [], []
                n = len(fv)
                for i in range(n):
                    j = (i+1)%n
                    vc, vn = fv[i], fv[j]
                    pc, pn = face[1][i], face[1][j]
                    da, db = dists[i], dists[j]
                    if da >= -EPS:
                        fc_cam.append(vc); fc_pts.append(pc)
                    if da <=  EPS:
                        fb_cam.append(vc); fb_pts.append(pc)
                    if (da > EPS and db < -EPS) or (da < -EPS and db > EPS):
                        t = da/(da-db)
                        ic = tuple(vc[k]+t*(vn[k]-vc[k]) for k in range(3))
                        ip = (pc[0]+t*(pn[0]-pc[0]), pc[1]+t*(pn[1]-pc[1]))
                        fc_cam.append(ic); fc_pts.append(ip)
                        fb_cam.append(ic); fb_pts.append(ip)
                fill,stroke,sw2,opa = face[2],face[3],face[4],face[5]
                if len(fc_cam)>=3: front_list.append((tuple(fc_cam),tuple(fc_pts),fill,stroke,sw2,opa))
                if len(fb_cam)>=3: back_list.append((tuple(fb_cam),tuple(fb_pts),fill,stroke,sw2,opa))
        return (normal, p0, pivot, bsp_build(front_list), bsp_build(back_list))

    def bsp_traverse(node, result):
        if node is None: return
        normal, p0, pivot, front, back = node
        # Camera at origin; dot(normal, -p0) tells which side camera is on
        cam_side = vdot(normal, vscale(p0, -1))
        if cam_side >= 0:
            bsp_traverse(back,  result)
            result.append(pivot)
            bsp_traverse(front, result)
        else:
            bsp_traverse(front, result)
            result.append(pivot)
            bsp_traverse(back,  result)

    bsp_root = bsp_build(raw_faces)
    ordered  = []
    bsp_traverse(bsp_root, ordered)

    # -- Merge coplanar adjacent triangles into quads --------------------------
    # Group by material, find pairs sharing an edge on same plane, merge.
    EPS_M = 1e-3
    from collections import defaultdict
    mat_groups = defaultdict(list)
    for face in ordered:
        cam_v, pts2, f, s, sw, op = face
        mat_groups[(f,s,sw,op)].append((cam_v, pts2))

    # Build final polygon list preserving BSP back-to-front order
    # We need to re-sort merged polys by their original BSP position
    face_order = {id(face): i for i, face in enumerate(ordered)}

    merged = []  # (pts2_poly, fill, stroke, sw, opacity, order_idx)
    for (f,s,sw,op), face_list in mat_groups.items():
        used = [False]*len(face_list)
        for i in range(len(face_list)):
            if used[i]: continue
            cam_i, pts_i = face_list[i]
            merged_j = None
            for j in range(i+1, len(face_list)):
                if used[j]: continue
                cam_j, pts_j = face_list[j]
                # Same plane check: normals parallel and same d
                e1i=vsub(cam_i[1],cam_i[0]); e2i=vsub(cam_i[2],cam_i[0]); ni=vcross(e1i,e2i)
                e1j=vsub(cam_j[1],cam_j[0]); e2j=vsub(cam_j[2],cam_j[0]); nj=vcross(e1j,e2j)
                mi=math.sqrt(vdot(ni,ni)); mj=math.sqrt(vdot(nj,nj))
                if mi<EPS_M or mj<EPS_M: continue
                ni=(ni[0]/mi,ni[1]/mi,ni[2]/mi); nj=(nj[0]/mj,nj[1]/mj,nj[2]/mj)
                di=vdot(ni,cam_i[0]); dj=vdot(nj,cam_j[0])
                if abs(abs(vdot(ni,nj))-1)>EPS_M or abs(di-dj)>EPS_M: continue
                # Shared edge check in 2D screen space
                def close(a,b): return abs(a[0]-b[0])<EPS_M and abs(a[1]-b[1])<EPS_M
                shared_pts = [p for p in pts_i if any(close(p,q) for q in pts_j)]
                if len(shared_pts) == 2:
                    # Build quad: unshared_i, shared[0], unshared_j, shared[1]
                    u_i = next(p for p in pts_i if not any(close(p,q) for q in shared_pts))
                    u_j = next(p for p in pts_j if not any(close(p,q) for q in shared_pts))
                    quad = [u_i, shared_pts[0], u_j, shared_pts[1]]
                    merged_j = j
                    used[i]=used[j]=True
                    # Use earlier BSP index for sort
                    orig_face_i = ordered[list(mat_groups[(f,s,sw,op)]).index(face_list[i]) if False else 0]
                    merged.append((quad, f, s, sw, op, i))
                    break
            if not used[i]:
                used[i]=True
                merged.append((list(pts_i), f, s, sw, op, i))

    # -- Render --------------------------------------------------------------─
    all_pts = [p for poly,*_ in merged for p in poly]
    if not all_pts: return "Nothing visible from current viewpoint."
    xs=[p[0] for p in all_pts]; ys=[p[1] for p in all_pts]
    pad=2
    vx=min(xs)-pad; vy=min(ys)-pad; vw=max(xs)-vx+pad; vh=max(ys)-vy+pad
    scene_to_px = size / max(vw,vh) if max(vw,vh)>0 else 1.0
    svgl=[
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vx:.2f} {vy:.2f} {vw:.2f} {vh:.2f}" width="{size}" height="{size}">',
    ]
    for poly, fill, stroke, sw, opacity, _ in merged:
        pts=' '.join(f'{p[0]:.2f},{p[1]:.2f}' for p in poly)
        op=f' opacity="{opacity}"' if opacity<1 else ''
        sw_px = sw / scene_to_px
        svgl.append(f'  <polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw_px:.3f}"{op}/>')
    svgl.append('</svg>')
    with open(out_path,'w') as f: f.write('\n'.join(svgl))
    return f"Exported SVG: {out_path} ({len(merged)} polygons)."


# -- Shared camera distance helper --------------------------------------------
def _camera_dist(scene, vp):
    """Compute camera distance for az/el viewpoints.

    Priority:
      1. vp.pos is set: use it directly, dist = magnitude of pos relative to look_at.
      2. Otherwise: measure scene extent from the look_at point (or origin if none),
         then place camera at max_reach * 2.5 from that centre, minimum 30.

    Replaces the hardcoded dist=50 that ignored scene size and look_at offset.
    Factor 2.5 gives comfortable framing: scene fully visible with margin.
    vp.scale is the 2D projection multiplier -- it does NOT affect camera distance.
    Camera distance is auto-fitted to scene extent only.
    """
    lx = vp.look_at.x if vp.look_at else 0.0
    ly = vp.look_at.y if vp.look_at else 0.0
    lz = vp.look_at.z if vp.look_at else 0.0

    if vp.pos:
        # Explicit placement: distance from look_at to camera pos
        dx = vp.pos.x - lx
        dy = vp.pos.y - ly
        dz = vp.pos.z - lz
        return math.sqrt(dx*dx + dy*dy + dz*dz)

    # Measure scene extent from look_at centre
    all_objs = [o for o in scene.all_objects() if not _should_skip(o)]
    if not all_objs:
        return 50.0

    max_r = 0.0
    for obj in all_objs:
        wp = scene.world_pos(obj)
        wr = scene.world_radius(obj)
        # Distance from look_at to object edge
        dx = wp.x - lx
        dy = wp.y - ly
        dz = wp.z - lz
        reach = math.sqrt(dx*dx + dy*dy + dz*dz) + wr
        if reach > max_r:
            max_r = reach

    return max(50.0, max_r * 1.8)


# -- POV-Ray ------------------------------------------------------------------

def export_povray(scene, out_path):
    """Export scene to POV-Ray .pov format. Spheres/cylinders stay analytical.

    #doc COORDINATE QUIRK: DM uses right-handed Y-up with camera at -Z for az=0.
    POV-Ray also uses right-handed Y-up but camera convention differs.
    Camera position is computed as:
      cx = dist * cos(el) * sin(az)
      cy = dist * sin(el)
      cz = -dist * cos(el) * cos(az)
    The negative Z on cz is intentional - az=0 means "looking from front" which
    is the -Z direction in our system. This matches the SVG projection exactly.

    #doc CUBE QUIRK: Cubes are tessellated to mesh2 to correctly bake in
    parent-chain rotation matrices. A POV-Ray box{} primitive cannot represent
    an arbitrarily rotated cube from a parent chain, so we tessellate at
    subdivisions=1 (6 faces, 12 triangles) and emit world-space vertices.

    #doc MERGE_GROUP QUIRK: Objects tagged merge_group=X are emitted inside a
    POV-Ray union{} block with a shared texture. This removes internal surface
    boundaries between adjacent primitives (e.g. sphere+sphere head+muzzle),
    giving seamless organic blending. The texture of the first object in the
    group is used for the whole union.
    """
    vp = scene.active_viewpoint()

    # Camera position: explicit pos= overrides az/el computation.
    # GROUND TRUTH is the viewpoint az/el as set and navigated in DM.
    # All exports must render from this exact angle - no recalculation.
    # Camera approach: LOCK camera, ROTATE scene.
    # Camera is fixed at <0, 0, -dist>. Scene rotates to match az/el.
    # This eliminates gimbal lock, sky vector issues, and all camera orbit math.
    # Same approach as native renderer -- rotate the clay, not the viewer.
    dist = _camera_dist(scene, vp)
    lx = vp.look_at.x if vp.look_at else 0.0
    ly = vp.look_at.y if vp.look_at else 0.0
    lz = vp.look_at.z if vp.look_at else 0.0
    if vp.pos:
        cam_pos = f'<{vp.pos.x},{vp.pos.y},{vp.pos.z}>'
    else:
        cam_pos = f'<0,0,{-dist:.2f}>'
    look = '<0,0,0>'   # locked camera always looks at origin; scene is pre-translated
    cam_flip = False
    sky = '<0,1,0>'  # always valid -- camera never moves off Z axis

    def h2pov(h):
        r,g,b=_hex_to_rgb(h)
        return f'rgb<{r/255:.4f},{g/255:.4f},{b/255:.4f}>'

    lines = [
        f'// DwarvenModeller POV-Ray export  {_now()[:19]}',
        '',
        'global_settings { ambient_light rgb<0,0,0> }', '',
        f'camera {{ location {cam_pos} look_at {look} angle 45 }}', '',
        '// Transparent background - render with +UA for alpha, or remove for opaque black',
        'background { color rgbt <0,0,0,1> }', '',
        '// Mirror scene on X axis to match DM native projection convention',
        '#declare DM_scene = union {',
    ]

    # -- F6: collect merge_group tags → emit as POV union{} blocks ------------
    from collections import defaultdict
    merge_groups = defaultdict(list)
    blob_groups  = defaultdict(list)   # blob{} for smooth organic merging
    deform_map   = defaultdict(list)   # obj_id -> [pressing_obj_ids] (deformed_by + carve=true)
    for obj in scene.all_objects():
        for tag in obj.tags:
            if tag.startswith('merge_group='):
                merge_groups[tag.split('=',1)[1].strip()].append(obj)
            elif tag.startswith('blob_group='):
                blob_groups[tag.split('=',1)[1].strip()].append(obj)
            elif tag.startswith('deformed_by=') and 'carve=true' in obj.tags:
                # Only trigger difference{} if the base object is explicitly marked carve=true.
                # deformed_by= records the relationship; carve=true opts into POV subtraction.
                presser_id = tag.split('=',1)[1].strip()
                deform_map[obj.id].append(presser_id)
    merge_group_ids = {obj.id for grp in merge_groups.values() for obj in grp}
    blob_group_ids  = {obj.id for grp in blob_groups.values()  for obj in grp}
    # Objects that will be emitted as difference{} blocks (carve=true + deformed_by)
    deformed_ids    = set(deform_map.keys())

    def emit_pov_object(obj, parent_M, lines_out, tx_override=None):
        """Emit a single object's POV geometry into lines_out."""
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M
        if _skip_in_emit(obj): return
        wp = world_M * Vec3(0, 0, 0)
        wpx, wpy, wpz = wp.x, wp.y, wp.z
        mat   = obj.material
        fill  = h2pov(mat.fill)
        shine = mat.shininess
        tx_block = tx_override or (
            f'texture {{ pigment {{ color {fill} }} {mat.povray_finish} }}' if mat.povray_finish else
            f'texture {{ pigment {{ color {fill} transmit {1-mat.opacity:.2f} }} }}' if mat.opacity < 1 else
            f'texture {{ pigment {{ color {fill} }} finish {{ emission 1.0 diffuse 0.0 specular 0.0 }} }}'
        )
        t = obj.type; p = obj.params; sc = obj.transform.scale
        if t in ('sphere', 'icosahedron'):
            r = float(p.get('radius', 1.0))
            lines_out.append(f'  sphere {{ <{wpx:.4f},{wpy:.4f},{wpz:.4f}>, {r}')
            lines_out.append(f'    {tx_block}')
            if sc.x!=1 or sc.y!=1 or sc.z!=1:
                lines_out.append(f'    scale <{sc.x},{sc.y},{sc.z}>')
            lines_out.append('  }')
        elif t == 'cube':
            tris = tessellate_object(_obj_no_children(obj), parent_M, subdivisions=1)
            if tris:
                # Per-face shading: bake native _shade formula into each triangle's colour.
                # Use native rotation convention (clockwise az = +sin) to compute
                # face normal Z in camera space, matching ansi_render._view() exactly.
                _az_r  = math.radians(vp.az)
                _el_r  = math.radians(-vp.el if PITCH_INVERSION else vp.el)
                _cos_az, _sin_az = math.cos(_az_r), math.sin(_az_r)
                _cos_el, _sin_el = math.cos(_el_r), math.sin(_el_r)

                def _face_nz(tri):
                    v0,v1,v2 = tri
                    ex,ey,ez = v1[0]-v0[0],v1[1]-v0[1],v1[2]-v0[2]
                    fx,fy,fz = v2[0]-v0[0],v2[1]-v0[1],v2[2]-v0[2]
                    nx=ey*fz-ez*fy; ny=ez*fx-ex*fz; nz=ex*fy-ey*fx
                    nm=math.sqrt(nx*nx+ny*ny+nz*nz)
                    if nm<1e-10: return 0.0
                    nx,ny,nz = nx/nm,ny/nm,nz/nm
                    # Native clockwise az rotation around Y
                    rx  =  nx*_cos_az + nz*_sin_az
                    rz  = -nx*_sin_az + nz*_cos_az
                    ry2 =  ny*_cos_el - rz*_sin_el
                    rz2 =  ny*_sin_el + rz*_cos_el
                    return -rz2  # -rz2: camera looks along -Z

                if mat.povray_finish:
                    # Custom finish overrides shading -- use single tx_block
                    all_v = list({v for tri in tris for v in tri})
                    vi = {v:i for i,v in enumerate(all_v)}
                    lines_out.append('  mesh2 {')
                    lines_out.append(f'    vertex_vectors {{ {len(all_v)},')
                    for v in all_v: lines_out.append(f'      <{v[0]:.4f},{v[1]:.4f},{v[2]:.4f}>,')
                    lines_out.append('    }')
                    lines_out.append(f'    face_indices {{ {len(tris)},')
                    for tri in tris: lines_out.append(f'      <{vi[tri[0]]},{vi[tri[1]]},{vi[tri[2]]}>,')
                    lines_out.append('    }')
                    lines_out.append(f'    {tx_block}')
                    lines_out.append('  }')
                else:
                    # Group triangles by shaded colour to minimise output size
                    rgb_base = _hex_to_rgb(mat.fill)
                    _AMBIENT, _DIFFUSE = 0.6, 0.4
                    from collections import defaultdict as _dd
                    groups = _dd(list)
                    for tri in tris:
                        nz = _face_nz(tri)
                        t_val = max(0.0, nz)
                        br = _AMBIENT + _DIFFUSE * t_val
                        r = min(255, int(rgb_base[0] * br))
                        g = min(255, int(rgb_base[1] * br))
                        b = min(255, int(rgb_base[2] * br))
                        groups[(r,g,b)].append(tri)
                    for (r,g,b), gtris in groups.items():
                        col = f'rgb<{r/255:.4f},{g/255:.4f},{b/255:.4f}>'
                        all_v = list({v for tri in gtris for v in tri})
                        vi = {v:i for i,v in enumerate(all_v)}
                        lines_out.append('  mesh2 {')
                        lines_out.append(f'    vertex_vectors {{ {len(all_v)},')
                        for v in all_v: lines_out.append(f'      <{v[0]:.4f},{v[1]:.4f},{v[2]:.4f}>,')
                        lines_out.append('    }')
                        lines_out.append(f'    face_indices {{ {len(gtris)},')
                        for tri in gtris: lines_out.append(f'      <{vi[tri[0]]},{vi[tri[1]]},{vi[tri[2]]}>,')
                        lines_out.append('    }')
                        lines_out.append(f'    texture {{ pigment {{ color {col} }} finish {{ emission 1.0 diffuse 0.0 specular 0.0 }} }}')
                        lines_out.append('  }')
        elif t == 'cylinder':
            r=float(p.get('radius',1.0)); h=float(p.get('height',2.0))
            # Transform local cap centres through world matrix (respects rotation)
            cap_b = world_M * Vec3(0, -h/2, 0)
            cap_t = world_M * Vec3(0,  h/2, 0)
            lines_out.append(f'  cylinder {{ <{cap_b.x:.4f},{cap_b.y:.4f},{cap_b.z:.4f}>,'
                             f'<{cap_t.x:.4f},{cap_t.y:.4f},{cap_t.z:.4f}>,{r}')
            lines_out.append(f'    {tx_block}')
            lines_out.append('  }')
        elif t == 'cone':
            rb=float(p.get('base_radius',1.0)); rt=float(p.get('top_radius',0.0))
            h=float(p.get('height',2.0))
            cap_b = world_M * Vec3(0, -h/2, 0)
            cap_t = world_M * Vec3(0,  h/2, 0)
            lines_out.append(f'  cone {{ <{cap_b.x:.4f},{cap_b.y:.4f},{cap_b.z:.4f}>,{rb},'
                             f'<{cap_t.x:.4f},{cap_t.y:.4f},{cap_t.z:.4f}>,{rt}')
            lines_out.append(f'    {tx_block}')
            lines_out.append('  }')
        elif t == 'capsule':
            r=float(p.get('radius',1.0)); h=float(p.get('height',2.0))
            cap_b = world_M * Vec3(0, -h/2, 0)
            cap_t = world_M * Vec3(0,  h/2, 0)
            lines_out.append(f'  union {{')
            lines_out.append(f'    cylinder {{ <{cap_b.x:.4f},{cap_b.y:.4f},{cap_b.z:.4f}>,'
                             f'<{cap_t.x:.4f},{cap_t.y:.4f},{cap_t.z:.4f}>,{r} }}')
            lines_out.append(f'    sphere {{ <{cap_t.x:.4f},{cap_t.y:.4f},{cap_t.z:.4f}>,{r} }}')
            lines_out.append(f'    sphere {{ <{cap_b.x:.4f},{cap_b.y:.4f},{cap_b.z:.4f}>,{r} }}')
            lines_out.append(f'    {tx_block}')
            lines_out.append('  }')
        elif t == 'text':
            # POV-Ray native text{} primitive -- billboard facing camera
            content  = str(p.get('content', 'text')).replace('"', "'")
            size     = float(p.get('size', 5.0))
            depth_t  = float(p.get('depth', 0.5))
            font     = str(p.get('font', 'timrom.ttf'))
            offset_x = -len(content) * size * 0.35
            import math as _tm2
            lines_out.append(f'  text {{')
            lines_out.append(f'    ttf "{font}" "{content}" {depth_t:.3f}, 0')
            lines_out.append(f'    {tx_block}')
            lines_out.append(f'    scale {size:.4f}')
            lines_out.append(f'    translate <{offset_x:.4f}, 0, 0>')
            lines_out.append(f'    scale <-1,1,1>')
            lines_out.append(f'    translate <{wpx:.4f},{wpy:.4f},{wpz:.4f}>')
            lines_out.append('  }')
        else:
            tris = tessellate_object(_obj_no_children(obj), parent_M, subdivisions=3)
            if tris:
                all_v = list({v for tri in tris for v in tri})
                vi = {v:i for i,v in enumerate(all_v)}
                lines_out.append('  mesh2 {')
                lines_out.append(f'    vertex_vectors {{ {len(all_v)},')
                for v in all_v: lines_out.append(f'      <{v[0]:.4f},{v[1]:.4f},{v[2]:.4f}>,')
                lines_out.append('    }')
                lines_out.append(f'    face_indices {{ {len(tris)},')
                for tri in tris: lines_out.append(f'      <{vi[tri[0]]},{vi[tri[1]]},{vi[tri[2]]}>,')
                lines_out.append('    }')
                lines_out.append(f'    {tx_block}')
                lines_out.append('  }')

    # Emit merge groups first (union{} -- removes internal surfaces)
    for gname, grp_objs in merge_groups.items():
        rep_mat = grp_objs[0].material
        fill = h2pov(rep_mat.fill); shine = rep_mat.shininess
        tx = (f'texture {{ pigment {{ color {fill} }} {rep_mat.povray_finish} }}' if rep_mat.povray_finish else
              f'texture {{ pigment {{ color {fill} transmit {1-rep_mat.opacity:.2f} }} }}' if rep_mat.opacity < 1 else
              f'texture {{ pigment {{ color {fill} }} finish {{ emission 1.0 diffuse 0.0 specular 0.0 }} }}')
        lines.append(f'// merge_group={gname}')
        lines.append('union {')
        for obj in grp_objs:
            parent = scene.find_parent(obj.id)
            parent_M = scene.world_matrix_of(parent.id) if parent else None
            lines.append(f'  // {obj.id}')
            emit_pov_object(obj, parent_M, lines)
        # Only add group-level texture if objects don't have per-face textures.
        # Cubes use per-face shading (inline textures), so skip group texture for them.
        # Null objects are transparent hinges -- exclude from the check.
        renderable = [o for o in grp_objs if o.type != 'null']
        all_cubes = all(o.type == 'cube' for o in renderable)
        if not all_cubes:
            lines.append(f'  {tx}')
        lines.append('}')
        lines.append('')

    # Emit blob groups (blob{} -- smooth organic merging between components)
    for gname, grp_objs in blob_groups.items():
        rep_mat = grp_objs[0].material
        fill = h2pov(rep_mat.fill); shine = rep_mat.shininess
        tx = (f'texture {{ pigment {{ color {fill} }} {rep_mat.povray_finish} }}' if rep_mat.povray_finish else
              f'texture {{ pigment {{ color {fill} transmit {1-rep_mat.opacity:.2f} }} }}' if rep_mat.opacity < 1 else
              f'texture {{ pigment {{ color {fill} }} finish {{ emission 1.0 diffuse 0.0 specular 0.0 }} }}')
        lines.append(f'// blob_group={gname}')
        lines.append('blob {')
        lines.append('  threshold 0.5')
        for obj in grp_objs:
            parent = scene.find_parent(obj.id)
            parent_M = scene.world_matrix_of(parent.id) if parent else None
            local_M  = obj.transform.matrix()
            world_M  = (parent_M * local_M) if parent_M else local_M
            wp  = world_M * Vec3(0, 0, 0)
            p   = obj.params
            t   = obj.type
            sc  = obj.transform.scale
            lines.append(f'  // {obj.id}')
            if t in ('sphere', 'icosahedron', 'octahedron', 'tetrahedron', 'dodecahedron'):
                r = float(p.get('radius', 1.0)) * max(sc.x, sc.y, sc.z)
                lines.append(f'  sphere {{ <{wp.x:.4f},{wp.y:.4f},{wp.z:.4f}>, {r:.4f}, 2.0 }}')
            elif t == 'cylinder':
                r = float(p.get('radius', 1.0)); h = float(p.get('height', 2.0))
                cb = world_M * Vec3(0, -h/2, 0)
                ct = world_M * Vec3(0,  h/2, 0)
                lines.append(f'  cylinder {{ <{cb.x:.4f},{cb.y:.4f},{cb.z:.4f}>,'
                             f'<{ct.x:.4f},{ct.y:.4f},{ct.z:.4f}>,{r:.4f}, 2.0 }}')
            else:
                # Fallback: approximate as sphere using bounding radius
                r = scene.world_radius(obj)
                lines.append(f'  sphere {{ <{wp.x:.4f},{wp.y:.4f},{wp.z:.4f}>, {r:.4f}, 2.0 }}')
        lines.append(f'  {tx}')
        lines.append('}')
        lines.append('')

    # -- Clay deformation: emit difference{} for objects with deformed_by tags --
    # deformed_by=<presser_id> tags are set by the 'press' op and recorded in
    # the DMS file. The base object is emitted first, then all pressers are
    # subtracted from it, carving sockets at each press point.
    for base_id, presser_ids in deform_map.items():
        base_obj = scene.find_object(base_id)
        if not base_obj or _should_skip(base_obj): continue
        if base_id in merge_group_ids or base_id in blob_group_ids: continue

        base_parent = scene.find_parent(base_id)
        base_M = scene.world_matrix_of(base_parent.id) if base_parent else None

        mat = base_obj.material
        fill = h2pov(mat.fill); shine = mat.shininess
        tx = (f'texture {{ pigment {{ color {fill} }} {mat.povray_finish} }}' if mat.povray_finish else
              f'texture {{ pigment {{ color {fill} transmit {1-mat.opacity:.2f} }} }}' if mat.opacity < 1 else
              f'texture {{ pigment {{ color {fill} }} finish {{ emission 1.0 diffuse 0.0 specular 0.0 }} }}')

        valid_pressers = [pid for pid in presser_ids if scene.find_object(pid)]
        if not valid_pressers:
            continue  # presser deleted -- skip, base will render normally

        lines.append(f'// {base_id} (deformed by: {", ".join(valid_pressers)})')
        lines.append('difference {')
        lines.append(f'  // base object')
        emit_pov_object(base_obj, base_M, lines)
        for pid in valid_pressers:
            presser = scene.find_object(pid)
            presser_parent = scene.find_parent(pid)
            presser_M = scene.world_matrix_of(presser_parent.id) if presser_parent else None
            lines.append(f'  // socket carved by: {pid}')
            emit_pov_object(presser, presser_M, lines)
        lines.append(f'  {tx}')
        lines.append('}')
        lines.append('')

    text_lines = []  # text objects emitted outside the union to avoid occlusion

    def emit(obj, parent_M=None):
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M

        # Skip null/group - but still recurse into children
        if _skip_in_emit(obj):
            for child in obj.children: emit(child, world_M)
            return

        # Skip objects emitted as part of a merge_group or blob_group
        if obj.id in merge_group_ids or obj.id in blob_group_ids:
            for child in obj.children: emit(child, world_M)
            return

        # Skip objects emitted inside a deformed_by difference{} block
        if obj.id in deformed_ids:
            for child in obj.children: emit(child, world_M)
            return

        wp = world_M * Vec3(0, 0, 0)
        wpx, wpy, wpz = wp.x, wp.y, wp.z
        mat   = obj.material
        fill  = h2pov(mat.fill)
        shine = mat.shininess

        if mat.povray_finish:
            tx_block = f'texture {{ pigment {{ color {fill} }} {mat.povray_finish} }}'
        elif mat.opacity < 1:
            tx_block = f'texture {{ pigment {{ color {fill} transmit {1-mat.opacity:.2f} }} }}'
        else:
            tx_block = (f'texture {{ pigment {{ color {fill} }} '
                        f'finish {{ emission 1.0 diffuse 0.0 specular 0.0 }} }}')

        t = obj.type; p = obj.params
        sc = obj.transform.scale; rot = obj.transform.rotate

        lines.append(f'// {obj.id} ({t})')

        if t in ('sphere', 'icosahedron'):
            r = float(p.get('radius', 1.0))
            lines.append(f'sphere {{ <{wpx:.4f},{wpy:.4f},{wpz:.4f}>, {r}')
            lines.append(f'  {tx_block}')
            if sc.x!=1 or sc.y!=1 or sc.z!=1:
                lines.append(f'  scale <{sc.x},{sc.y},{sc.z}>')
            lines.append('}')

        elif t == 'cube':
            # Tessellate to bake in parent-chain rotations
            tris = tessellate_object(_obj_no_children(obj), parent_M, subdivisions=1)
            if tris:
                all_v = list({v for tri in tris for v in tri})
                vi    = {v:i for i,v in enumerate(all_v)}
                lines.append(f'mesh2 {{')
                lines.append(f'  vertex_vectors {{ {len(all_v)},')
                for v in all_v: lines.append(f'    <{v[0]:.4f},{v[1]:.4f},{v[2]:.4f}>,')
                lines.append(f'  }}')
                lines.append(f'  face_indices {{ {len(tris)},')
                for tri in tris: lines.append(f'    <{vi[tri[0]]},{vi[tri[1]]},{vi[tri[2]]}>,')
                lines.append(f'  }}')
                lines.append(f'  {tx_block}')
                lines.append('}')

        elif t == 'cylinder':
            r=float(p.get('radius',1.0)); h=float(p.get('height',2.0))
            cap_b = world_M * Vec3(0, -h/2, 0)
            cap_t = world_M * Vec3(0,  h/2, 0)
            lines.append(f'cylinder {{ <{cap_b.x:.4f},{cap_b.y:.4f},{cap_b.z:.4f}>,'
                         f'<{cap_t.x:.4f},{cap_t.y:.4f},{cap_t.z:.4f}>,{r}')
            lines.append(f'  {tx_block}')
            lines.append('}')

        elif t == 'torus':
            R=float(p.get('outer_radius',2.0)); r=float(p.get('inner_radius',0.5))
            lines.append(f'torus {{ {R},{r}  {tx_block}')
            lines.append(f'  translate <{wpx:.4f},{wpy:.4f},{wpz:.4f}>')
            lines.append('}')

        elif t == 'plane':
            lines.append(f'plane {{ y,{wpy:.4f}  {tx_block} }}')

        elif t == 'cone':
            rb=float(p.get('base_radius',1.0)); rt=float(p.get('top_radius',0.0))
            h=float(p.get('height',2.0))
            cap_b = world_M * Vec3(0, -h/2, 0)
            cap_t = world_M * Vec3(0,  h/2, 0)
            lines.append(f'cone {{ <{cap_b.x:.4f},{cap_b.y:.4f},{cap_b.z:.4f}>,{rb},'
                         f'<{cap_t.x:.4f},{cap_t.y:.4f},{cap_t.z:.4f}>,{rt}')
            lines.append(f'  {tx_block}')
            lines.append('}')

        elif t == 'capsule':
            r=float(p.get('radius',1.0)); h=float(p.get('height',2.0))
            cap_b = world_M * Vec3(0, -h/2, 0)
            cap_t = world_M * Vec3(0,  h/2, 0)
            lines.append('union {')
            lines.append(f'  cylinder {{ <{cap_b.x:.4f},{cap_b.y:.4f},{cap_b.z:.4f}>,'
                         f'<{cap_t.x:.4f},{cap_t.y:.4f},{cap_t.z:.4f}>,{r} }}')
            lines.append(f'  sphere {{ <{cap_t.x:.4f},{cap_t.y:.4f},{cap_t.z:.4f}>,{r} }}')
            lines.append(f'  sphere {{ <{cap_b.x:.4f},{cap_b.y:.4f},{cap_b.z:.4f}>,{r} }}')
            lines.append(f'  {tx_block}')
            lines.append('}')

        elif t == 'text':
            content = str(p.get('content', 'text')).replace('"', "'")
            size    = float(p.get('size', 5.0))
            depth_t = float(p.get('depth', 0.5))
            font    = str(p.get('font', 'timrom.ttf'))
            offset_x = -len(content) * size * 0.35
            # Physical text: when scene faces away (cos(az)>0), text is seen
            # from behind -- mirror it like transparent paper viewed from the back.
            # Text is always mirrored: POV text{} runs left-to-right in world space,
            # but DM text reads right-to-left on the object surface (like physical clay).
            text_lines.append('text {')
            text_lines.append(f'  ttf "{font}" "{content}" {depth_t:.3f}, 0')
            text_lines.append(f'  {tx_block}')
            text_lines.append(f'  scale {size:.4f}')
            text_lines.append(f'  translate <{offset_x:.4f}, 0, 0>')
            text_lines.append(f'  scale <-1,1,1>')
            text_lines.append(f'  translate <{wpx:.4f},{wpy:.4f},{wpz:.4f}>')
            # Apply same rotation as DM_scene so text rotates with geometry
            _txt_el = -vp.el if PITCH_INVERSION else vp.el
            _txt_az = vp.az
            if vp.look_at and (vp.look_at.x or vp.look_at.y or vp.look_at.z):
                lx_ = vp.look_at.x; ly_ = vp.look_at.y; lz_ = vp.look_at.z
                text_lines.append(f'  translate <{-lx_:.4f},{-ly_:.4f},{-lz_:.4f}>')
                text_lines.append(f'  rotate <0,{_txt_az:.4f},0>')
                text_lines.append(f'  rotate <{_txt_el:.4f},0,0>')
            else:
                text_lines.append(f'  rotate <0,{_txt_az:.4f},0>')
                text_lines.append(f'  rotate <{_txt_el:.4f},0,0>')
                _txt_roll = -(vp.roll if PITCH_INVERSION else -vp.roll)
                if _txt_roll: text_lines.append(f'  rotate <0,0,{_txt_roll:.4f}>')
            text_lines.append('}')

        else:
            # Platonic solids - tessellate to mesh2
            tris = tessellate_object(_obj_no_children(obj), parent_M, subdivisions=3)
            if tris:
                all_v = list({v for tri in tris for v in tri})
                vi    = {v:i for i,v in enumerate(all_v)}
                lines.append(f'mesh2 {{')
                lines.append(f'  vertex_vectors {{ {len(all_v)},')
                for v in all_v: lines.append(f'    <{v[0]:.4f},{v[1]:.4f},{v[2]:.4f}>,')
                lines.append(f'  }}')
                lines.append(f'  face_indices {{ {len(tris)},')
                for tri in tris: lines.append(f'    <{vi[tri[0]]},{vi[tri[1]]},{vi[tri[2]]}>,')
                lines.append(f'  }}')
                lines.append(f'  {tx_block}')
                lines.append('}')

        lines.append('')
        for child in obj.children: emit(child, world_M)

    for obj in scene.objects: emit(obj)

    # Close the union.
    # cam_flip=True  (cz<0): camera flipped to +Z, geometry correct as-is.
    # Both cases need X mirror to match native -rx convention (world +X = screen left).
    # cam_flip additionally moved the camera to +Z -- that fixes front-back.
    # scale <-1,1,1> fixes left-right in both cases.
    lines.append('}')
    # Rotate scene to match az/el viewpoint -- camera is fixed at <0,0,-dist>.
    # Rotation order: az (Y axis) first, then el (X axis). Matches native _view().
    # PITCH_INVERSION: negate el for POV to match native forward-pitch convention.
    _pov_el = -vp.el if PITCH_INVERSION else vp.el
    # az uses clockwise convention -- negate for POV right-hand rule
    _pov_az = vp.az
    # look_at offset: if look_at is set, translate scene so look_at is at origin
    lx = vp.look_at.x if vp.look_at else 0
    ly = vp.look_at.y if vp.look_at else 0
    lz = vp.look_at.z if vp.look_at else 0
    if lx or ly or lz:
        _pov_roll = -(vp.roll if PITCH_INVERSION else -vp.roll)
        lines.append(f'object {{ DM_scene translate <{-lx:.4f},{-ly:.4f},{-lz:.4f}> rotate <0,{_pov_az:.4f},0> rotate <{_pov_el:.4f},0,0> rotate <0,0,{_pov_roll:.4f}> }}')
    else:
        _pov_roll = -(vp.roll if PITCH_INVERSION else -vp.roll)
        lines.append(f'object {{ DM_scene rotate <0,{_pov_az:.4f},0> rotate <{_pov_el:.4f},0,0> rotate <0,0,{_pov_roll:.4f}> }}')
    lines.append('')
    if text_lines:
        lines.append('// Text labels (outside union for correct visibility)')
        lines.extend(text_lines)
        lines.append('')

    with open(out_path, 'w') as f: f.write('\n'.join(lines))
    exported = [o for o in scene.all_objects() if not _should_skip(o)]
    return f"Exported POV-Ray: {out_path} ({len(exported)} object{'s' if len(exported)!=1 else ''})."


# -- OBJ ----------------------------------------------------------------------

def _viewpoint_export_matrix(scene):
    """Return a Y-rotation matrix that orients the scene so DM's viewpoint
    faces the standard front direction used by OBJ/STL viewers (camera at -Z).
    Rotating by -az aligns DM's view with az=0 (standard front).
    """
    vp = scene.active_viewpoint()
    return Mat4.rotate_y(-vp.az)


def export_obj(scene, out_path):
    """Export scene as Wavefront OBJ -- compatible with Blender and most 3D tools.
    Geometry is exported in DM world space (no camera rotation applied).

    F-OBJ-MTL (pending): OBJ supports colour via a .mtl sidecar file.
    When implemented, each object's fill colour will be written as a named
    material in <out_path>.mtl and referenced from the OBJ via 'usemtl'.
    """
    lines_v = [f'# DwarvenModeller OBJ  {_now()[:19]}', '']
    lines_f = []; offset = 1

    def collect(obj, parent_M=None):
        nonlocal offset
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M
        if not _should_skip(obj):
            tris = tessellate_object(_obj_no_children(obj), parent_M, 3)
            if tris:
                lines_v.extend([f'o {obj.id}', f'# fill={obj.material.fill}'])
                for tri in tris:
                    for v in tri:
                        lines_v.append(f'v {v[0]:.6f} {v[1]:.6f} {-v[2]:.6f}')
                for i in range(len(tris)):
                    a = offset+i*3; lines_f.append(f'f {a} {a+1} {a+2}')
                offset += len(tris)*3
                lines_v.append('')
        for child in obj.children:
            collect(child, world_M)

    for obj in scene.objects:
        collect(obj)

    with open(out_path, 'w') as f: f.write('\n'.join(lines_v + lines_f))

    # NOTE on Blender import:
    # DM world space: X=right, Y=up, Z=toward viewer (camera at -Z for az=0/el=0).
    # OBJ/Blender use the same Y-up convention.
    # To match DM's default view in Blender: View menu > Viewpoint > Front
    # (or Numpad 1), then rotate 90 degrees so you're looking from -Z toward +Z.
    # Blender's default Front view looks from +Y, not -Z, so the model appears
    # rotated 90 degrees compared to DM's az=0 view.

    return f"Exported OBJ: {out_path}."


# -- STL ----------------------------------------------------------------------

def export_stl(scene, out_path, subdivisions=3):
    """Export scene as binary STL -- universal 3D printing format (Z-up).
    Geometry in DM world space. Sidecar .camera.json written for testbench.
    """
    pairs = tessellate_scene(scene, subdivisions)
    tris  = [tri for tris,_ in pairs for tri in tris]

    def normal(tri):
        a,b,c = [Vec3(*v) for v in tri]
        ab=b-a; ac=c-a
        n=Vec3(ab.y*ac.z-ab.z*ac.y, ab.z*ac.x-ab.x*ac.z, ab.x*ac.y-ab.y*ac.x)
        l=n.length()
        return (n.x/l, n.y/l, n.z/l) if l>1e-10 else (0,0,1)

    # Convert Y-up Z-forward to Z-up Y-forward (slicer convention)
    def stl_v(v): return (v[0], -v[2], v[1])
    def stl_n(n): return (n[0], -n[2], n[1])

    header = (b'DwarvenModeller STL export' + b'\x00'*54)[:80]
    buf    = [header, struct.pack('<I', len(tris))]
    for tri in tris:
        nx,ny,nz = normal(tri)
        cnx,cny,cnz = stl_n((nx,ny,nz))
        buf.append(struct.pack('<fff', cnx,cny,cnz))
        for v in tri: buf.append(struct.pack('<fff', *stl_v(v)))
        buf.append(struct.pack('<H', 0))
    with open(out_path, 'wb') as f:
        for b in buf: f.write(b)

    # Write camera sidecar -- same logic as OBJ
    import json as _json
    vp = scene.active_viewpoint()
    el_r = math.radians(-vp.el if PITCH_INVERSION else vp.el); az_r = math.radians(vp.az); dist = _camera_dist(scene, vp)
    if vp.pos:
        dm_cx, dm_cy, dm_cz = vp.pos.x, vp.pos.y, vp.pos.z
    else:
        lx = vp.look_at.x if vp.look_at else 0
        ly = vp.look_at.y if vp.look_at else 0
        lz = vp.look_at.z if vp.look_at else 0
        dm_cx = dist * math.cos(el_r) * math.sin(az_r) + lx
        dm_cy = dist * math.sin(el_r) + ly
        dm_cz = -dist * math.cos(el_r) * math.cos(az_r) + lz
    # Camera: use dm_cx directly (no negation). stl_v preserves X.
    # The manual Z-up rotation in the testbench handles orientation correctly.
    bl_x = dm_cx; bl_y = -dm_cz; bl_z = dm_cy
    lx = vp.look_at.x if vp.look_at else 0
    ly = vp.look_at.y if vp.look_at else 0
    lz = vp.look_at.z if vp.look_at else 0
    sidecar = out_path.rsplit('.', 1)[0] + '.camera.json'
    with open(sidecar, 'w') as f:
        _json.dump({'cam': [bl_x, bl_y, bl_z], 'look_at': [lx, -lz, ly]}, f)

    return f"Exported STL: {out_path} ({len(tris)} triangles)."


# -- X3D ----------------------------------------------------------------------

def export_x3d(scene, out_path):
    """Export scene as X3D - browser-viewable 3D, analytical primitives preserved."""
    vp = scene.active_viewpoint()

    def h2x3d(h):
        r,g,b=_hex_to_rgb(h); return f'{r/255:.3f} {g/255:.3f} {b/255:.3f}'

    el=math.radians(vp.el); dist=50
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 3.3//EN"',
        '  "http://www.web3d.org/specifications/x3d-3.3.dtd">',
        '<X3D version="3.3">',
        '<head>',
        f'  <meta name="generator" content="DwarvenModeller"/>',
        f'  <meta name="created"   content="{_now()[:19]}"/>',
        '</head>',
        '<Scene>',
        f'  <Viewpoint position="0 {dist*math.sin(el):.2f} {dist*math.cos(el):.2f}" '
        f'orientation="1 0 0 {-vp.el*math.pi/180:.4f}" description="default"/>',
        '',
    ]

    def emit(obj, parent_M=None):
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M
        if _skip_in_emit(obj):
            for child in obj.children: emit(child, world_M)
            return
        wp  = world_M * Vec3(0,0,0)
        sc  = obj.transform.scale
        mat = obj.material
        fill= h2x3d(mat.fill)
        t   = obj.type; p = obj.params
        x3z = -wp.z   # X3D Z faces viewer; ours faces away

        lines.append(f'  <!-- {obj.id} ({t}) -->')
        lines.append(f'  <Transform translation="{wp.x:.4f} {wp.y:.4f} {x3z:.4f}"'
                     f' scale="{sc.x:.4f} {sc.y:.4f} {sc.z:.4f}">')
        lines.append(f'    <Shape DEF="{obj.id}">')
        lines.append(f'      <Appearance>')
        lines.append(f'        <Material diffuseColor="{fill}" '
                     f'transparency="{1-mat.opacity:.3f}" shininess="{mat.shininess:.3f}"/>')
        lines.append(f'      </Appearance>')

        if t in ('sphere', 'icosahedron'):
            lines.append(f'      <Sphere radius="{float(p.get("radius",1.0))}"/>')
        elif t == 'cube':
            w=float(p.get('width',1.0)); h=float(p.get('height',1.0)); d=float(p.get('depth',1.0))
            lines.append(f'      <Box size="{w} {h} {d}"/>')
        elif t == 'cylinder':
            lines.append(f'      <Cylinder radius="{float(p.get("radius",1.0))}" '
                         f'height="{float(p.get("height",2.0))}"/>')
        elif t == 'plane':
            w=float(p.get('width',10.0)); d=float(p.get('depth',10.0))
            lines.append(f'      <Box size="{w} 0.001 {d}"/>')
        else:
            tris = tessellate_object(_obj_no_children(obj), parent_M, 2)
            if tris:
                all_v=[v for tri in tris for v in tri]
                coords=' '.join(f'{v[0]:.3f} {v[1]:.3f} {-v[2]:.3f}' for v in all_v)
                indices=' '.join(f'{i*3} {i*3+1} {i*3+2} -1' for i in range(len(tris)))
                lines.append(f'      <IndexedFaceSet solid="true" coordIndex="{indices}">')
                lines.append(f'        <Coordinate point="{coords}"/>')
                lines.append(f'      </IndexedFaceSet>')

        lines.extend([f'    </Shape>', f'  </Transform>', ''])
        for child in obj.children: emit(child, world_M)

    for obj in scene.objects: emit(obj)
    lines += ['</Scene>', '</X3D>']
    with open(out_path, 'w', encoding='utf-8') as f: f.write('\n'.join(lines))
    n = len([o for o in scene.all_objects() if not _should_skip(o)])
    return f"Exported X3D: {out_path} ({n} objects)."


# -- glTF --------------------------------------------------------------------─

def export_gltf(scene, out_path, subdivisions=3):
    """Export scene as glTF 2.0 with embedded binary. Works in Blender, web, games.

    #doc COORDINATE SYSTEM: DM is Y-up, Z-toward-viewer (az=0).
    glTF is Y-up, Z-backward. Mesh vertices export correctly (world-space Y-up).
    Camera position is converted: glTF cam_z = -DM cam_z (Z-axis flip).
    A camera node is embedded using the scene's stored viewpoint so Blender
    opens at the correct angle automatically.
    """
    vp   = scene.active_viewpoint()
    pairs = tessellate_scene(scene, subdivisions)
    gltf = {
        'asset': {'version':'2.0','generator':'DwarvenModeller'},
        'scene': 0,
        'scenes': [{'nodes': list(range(len(pairs))) + [-2]}],  # -2 = camera node added at end
        'nodes': [], 'meshes': [], 'materials': [],
        'cameras': [],
        'accessors': [], 'bufferViews': [], 'buffers': [],
    }
    bin_data = bytearray()

    def add_buffer_view(data_bytes, target):
        offset = len(bin_data); bin_data.extend(data_bytes)
        while len(bin_data)%4: bin_data.append(0)
        gltf['bufferViews'].append({'buffer':0,'byteOffset':offset,
                                    'byteLength':len(data_bytes),'target':target})
        return len(gltf['bufferViews'])-1

    def add_accessor(bv_idx, comp_type, count, acc_type, mins, maxs):
        gltf['accessors'].append({'bufferView':bv_idx,'byteOffset':0,
                                   'componentType':comp_type,'count':count,
                                   'type':acc_type,'min':mins,'max':maxs})
        return len(gltf['accessors'])-1

    ARRAY_BUFFER=34962; ELEMENT_BUFFER=34963; FLOAT=5126; UINT=5125

    for i,(tris,mat) in enumerate(pairs):
        if not tris: continue
        verts=[v for tri in tris for v in tri]; n_v=len(verts)
        pos_bytes=bytearray()
        for v in verts: pos_bytes+=struct.pack('<fff', v[0], v[1], -v[2])
        xs=[v[0] for v in verts]; ys=[v[1] for v in verts]; zs=[v[2] for v in verts]
        pos_bv =add_buffer_view(bytes(pos_bytes),ARRAY_BUFFER)
        pos_acc=add_accessor(pos_bv,FLOAT,n_v,'VEC3',[min(xs),min(ys),min(zs)],[max(xs),max(ys),max(zs)])
        idx_bytes=bytearray()
        for j in range(n_v): idx_bytes+=struct.pack('<I',j)
        idx_bv =add_buffer_view(bytes(idx_bytes),ELEMENT_BUFFER)
        idx_acc=add_accessor(idx_bv,UINT,n_v,'SCALAR',[0],[n_v-1])
        r,g,b=_hex_to_rgb(mat.fill)
        gltf['materials'].append({'name':f'mat_{i}','pbrMetallicRoughness':{
            'baseColorFactor':[r/255,g/255,b/255,mat.opacity],
            'metallicFactor':mat.shininess,'roughnessFactor':1.0-mat.shininess},
            'alphaMode':'BLEND' if mat.opacity<1.0 else 'OPAQUE'})
        gltf['meshes'].append({'name':f'mesh_{i}','primitives':[{
            'attributes':{'POSITION':pos_acc},'indices':idx_acc,'material':i}]})
        gltf['nodes'].append({'mesh':i,'name':f'node_{i}'})

    # -- Camera node ----------------------------------------------------------─
    # DM: Y-up, Z-toward-viewer (az=0 = camera at -Z looking toward +Z)
    # glTF: Y-up, Z-backward (camera looks along its local -Z axis)
    # Conversion: X unchanged, Y unchanged, Z negated.
    dist = _camera_dist(scene, vp)
    lx = vp.look_at.x if vp.look_at else 0
    ly = vp.look_at.y if vp.look_at else 0
    lz = vp.look_at.z if vp.look_at else 0

    if vp.pos:
        # Explicit camera position -- convert DM Z to glTF Z
        dm_cx = vp.pos.x; dm_cy = vp.pos.y; dm_cz = vp.pos.z
    else:
        el_r = math.radians(-vp.el if PITCH_INVERSION else vp.el); az_r = math.radians(vp.az)
        dm_cx =  dist * math.cos(el_r) * math.sin(az_r) + lx
        dm_cy =  dist * math.sin(el_r)                  + ly
        dm_cz = -dist * math.cos(el_r) * math.cos(az_r) + lz

    # Camera: +dm_cx places Blender camera on the correct side to match native renderer.
    # glTF Y-up convention: X=right, Y=up, Z=toward-viewer.
    # DM world: X=right, Y=up, Z=away-from-viewer. So negate Z for glTF.
    gcx =  dm_cx
    gcy =  dm_cy
    gcz = -dm_cz   # DM Z-away -> glTF Z-toward
    glz = -lz      # same for look-at Z

    # Camera rotation: in glTF Y-up space, camera looks along its local -Z.
    # Camera is at (gcx,gcy,gcz) looking at (lx,gcy_la,glz).
    def _n(v):
        m = math.sqrt(sum(x*x for x in v)); return tuple(x/m for x in v) if m>1e-10 else (0,0,1)
    def _cr(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

    fwd   = _n((lx-gcx, ly-gcy, glz-gcz))     # toward target
    right = _n(_cr((0,1,0), fwd)) if abs(fwd[1])<0.99 else _n(_cr((0,0,1), fwd))
    up    = _cr(fwd, right)
    # Camera basis: right=+X, up=+Y, back=-fwd=+Z (glTF camera looks along -Z)
    bk    = (-fwd[0], -fwd[1], -fwd[2])
    # Rotation matrix (column-major: right, up, back)
    m = [[right[0], up[0], bk[0]],
         [right[1], up[1], bk[1]],
         [right[2], up[2], bk[2]]]
    # Matrix to quaternion
    tr = m[0][0]+m[1][1]+m[2][2]
    if tr > 0:
        s = 0.5/math.sqrt(tr+1); qw=0.25/s
        qx=(m[2][1]-m[1][2])*s; qy=(m[0][2]-m[2][0])*s; qz=(m[1][0]-m[0][1])*s
    elif m[0][0]>m[1][1] and m[0][0]>m[2][2]:
        s=2*math.sqrt(1+m[0][0]-m[1][1]-m[2][2])
        qw=(m[2][1]-m[1][2])/s; qx=0.25*s; qy=(m[0][1]+m[1][0])/s; qz=(m[0][2]+m[2][0])/s
    elif m[1][1]>m[2][2]:
        s=2*math.sqrt(1+m[1][1]-m[0][0]-m[2][2])
        qw=(m[0][2]-m[2][0])/s; qx=(m[0][1]+m[1][0])/s; qy=0.25*s; qz=(m[1][2]+m[2][1])/s
    else:
        s=2*math.sqrt(1+m[2][2]-m[0][0]-m[1][1])
        qw=(m[1][0]-m[0][1])/s; qx=(m[0][2]+m[2][0])/s; qy=(m[1][2]+m[2][1])/s; qz=0.25*s

    gltf['cameras'].append({'type':'perspective',
                             'perspective':{'yfov':0.698,'aspectRatio':1.0,
                                            'znear':0.1,'zfar':1000.0}})
    cam_node_idx = len(gltf['nodes'])
    gltf['nodes'].append({
        'name': 'DwarvenCamera',
        'camera': 0,
        'translation': [round(gcx,4), round(gcy,4), round(gcz,4)],
        'rotation':    [round(qx,6),  round(qy,6),  round(qz,6), round(qw,6)],
        'extras':      {'look_at': [lx, ly, -lz]},
    })
    gltf['scenes'][0]['nodes'] = [i for i in gltf['scenes'][0]['nodes'] if i != -2] + [cam_node_idx]

    b64=base64.b64encode(bytes(bin_data)).decode('ascii')
    gltf['buffers']=[{'byteLength':len(bin_data),
                      'uri':f'data:application/octet-stream;base64,{b64}'}]

    if out_path.lower().endswith('.glb'):
        # GLB binary container format
        import struct as _struct
        json_bytes = _json.dumps(gltf, separators=(',',':')).encode('utf-8')
        # Pad JSON chunk to 4-byte boundary with spaces
        while len(json_bytes) % 4: json_bytes += b' '
        # GLB header: magic(4) + version(4) + total_length(4)
        # JSON chunk: length(4) + type(4=0x4E4F534A "JSON") + data
        # BIN chunk:  length(4) + type(4=0x004E4942 "BIN\0") + data
        # For self-contained GLB with base64 buffer, just write JSON chunk only
        chunk_json = _struct.pack('<II', len(json_bytes), 0x4E4F534A) + json_bytes
        total_len  = 12 + len(chunk_json)
        header     = _struct.pack('<III', 0x46546C67, 2, total_len)
        with open(out_path, 'wb') as f: f.write(header + chunk_json)
    else:
        with open(out_path, 'w', encoding='utf-8') as f: _json.dump(gltf, f, indent=2)
    n=len([p for p in pairs if p[0]])
    return f"Exported glTF: {out_path} ({n} meshes, {sum(len(t) for t,_ in pairs)} triangles)."


# -- CSS 3D ------------------------------------------------------------------─

def export_css3d(scene, out_path, size=600):
    """
    Export scene as HTML/CSS 3D. Sphere → border-radius:50% div.
    Renders in any browser with zero dependencies.
    """
    vp       = scene.active_viewpoint()
    all_objs = scene.all_objects()
    if not all_objs: return "Scene is empty."
    positions = [scene.world_pos(o) for o in all_objs]
    cx=sum(p.x for p in positions)/len(positions)
    cy=sum(p.y for p in positions)/len(positions)
    cz=sum(p.z for p in positions)/len(positions)
    radii = [scene.world_radius(o) for o in all_objs]
    max_r = max((abs(p.x-cx)+r for p,r in zip(positions,radii)), default=1)
    scale = (size*0.4)/max(max_r,1)

    html = [
        '<!DOCTYPE html><html>',
        '<head><meta charset="UTF-8">',
        f'<title>{os.path.basename(out_path)} - DwarvenModeller CSS 3D</title>',
        '<style>',
        'body{margin:0;background:#1a1a2e;display:flex;justify-content:center;align-items:center;height:100vh}',
        f'.scene{{width:{size}px;height:{size}px;perspective:800px;perspective-origin:50% 50%}}',
        f'.world{{width:{size}px;height:{size}px;position:relative;transform-style:preserve-3d;',
        f'        transform:rotateX({-vp.el:.1f}deg) rotateY({-(vp.az+45):.1f}deg)}}',
        '.obj{position:absolute;transform-style:preserve-3d;transform-origin:center center}',
        '.sphere{border-radius:50%}',
        '</style></head><body>',
        '<div class="scene"><div class="world">',
    ]

    for obj in all_objs:
        if _should_skip(obj): continue
        wp  = scene.world_pos(obj)
        r   = scene.world_radius(obj)
        sc  = obj.transform.scale
        mat = obj.material
        tx  =  (wp.x-cx)*scale
        ty  = -(wp.y-cy)*scale
        tz  = -(wp.z-cz)*scale
        sw  = r*2*scale*sc.x; sh=r*2*scale*sc.y
        shape = 'sphere' if obj.type in ('sphere','icosahedron','octahedron',
                                          'tetrahedron','dodecahedron') else 'obj'
        op_s  = f'opacity:{mat.opacity};' if mat.opacity<1 else ''
        html.append(
            f'  <div class="obj {shape}" title="{obj.id}" style="'
            f'width:{sw:.1f}px;height:{sh:.1f}px;background:{mat.fill};'
            f'border:1px solid {mat.stroke};{op_s}'
            f'transform:translate3d({tx-sw/2:.1f}px,{ty-sh/2:.1f}px,{tz:.1f}px) '
            f'rotateX({obj.transform.rotate.x:.1f}deg) '
            f'rotateY({obj.transform.rotate.y:.1f}deg) '
            f'rotateZ({obj.transform.rotate.z:.1f}deg);"></div>')

    html += ['</div></div></body></html>']
    with open(out_path,'w',encoding='utf-8') as f: f.write('\n'.join(html))
    n = len([o for o in all_objs if not _should_skip(o)])
    return f"Exported CSS 3D: {out_path} ({n} elements). Open in any browser."


# -- Spatial text (Braille / screen reader) ----------------------------------─

def export_spatial_text(scene, out_path):
    """
    Export a structured prose spatial description.
    No visual output - designed for screen readers, Braille displays, JAWS, NVDA.
    Pipe to any text-to-speech system or Braille terminal.
    """
    all_objs = scene.all_objects()
    lines    = [
        'DWARVEN MODELLER - SPATIAL SCENE DESCRIPTION',
        '=' * 50, '',
        f'Scene contains {len(all_objs)} objects.', '',
    ]
    if all_objs:
        positions=[scene.world_pos(o) for o in all_objs]
        radii    =[scene.world_radius(o) for o in all_objs]
        min_x=min(p.x-r for p,r in zip(positions,radii)); max_x=max(p.x+r for p,r in zip(positions,radii))
        min_y=min(p.y-r for p,r in zip(positions,radii)); max_y=max(p.y+r for p,r in zip(positions,radii))
        min_z=min(p.z-r for p,r in zip(positions,radii)); max_z=max(p.z+r for p,r in zip(positions,radii))
        lines.append(f'Dimensions: {max_x-min_x:.1f} wide, {max_y-min_y:.1f} tall, {max_z-min_z:.1f} deep.')
        lines.append('')

    TYPE_NAMES = {
        'sphere':'smooth sphere','icosahedron':'sphere (icosahedron)',
        'cube':'box','cylinder':'cylinder','tetrahedron':'tetrahedron (4-sided pyramid)',
        'octahedron':'octahedron (8-faced diamond)','dodecahedron':'dodecahedron (12 faces)',
        'plane':'flat plane','torus':'torus (ring)','null':'container (invisible)',
        'cone':'cone (tapered cylinder)','capsule':'capsule (cylinder with rounded caps)',
    }
    lines += ['OBJECTS', '-'*30, '']

    def describe(obj, depth=0, parent_M=None):
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M
        wp  = world_M * Vec3(0,0,0)
        sc  = obj.transform.scale
        r   = obj.get_param('radius', obj.get_param('width', 1.0))
        eff_r = scene.world_radius(obj)
        mat = obj.material
        ind = '  '*depth
        lines.append(f'{ind}Object: {obj.id}')
        lines.append(f'{ind}  Type: {TYPE_NAMES.get(obj.type, obj.type)}')
        if sc.x==sc.y==sc.z:
            lines.append(f'{ind}  Size: radius {eff_r:.2f} units ({_size_description(eff_r)}).')
        else:
            lines.append(f'{ind}  Size: base radius {r:.2f}, stretched x={sc.x:.2f} y={sc.y:.2f} z={sc.z:.2f}.')
        lines.append(f'{ind}  Position: {wp.x:.2f} right, {wp.y:.2f} up, {wp.z:.2f} forward.')
        rr,gg,bb=_hex_to_rgb(mat.fill)
        op_s=f', {int(mat.opacity*100)}% opaque' if mat.opacity<1 else ''
        lines.append(f'{ind}  Color: {_approximate_colour_name(rr,gg,bb)} ({mat.fill}){op_s}.')
        rot=obj.transform.rotate
        if rot.x or rot.y or rot.z:
            lines.append(f'{ind}  Rotated: x={Transform.display_angle(rot.x):.1f}° y={Transform.display_angle(rot.y):.1f}° z={Transform.display_angle(rot.z):.1f}°.')
        if obj.attach_point:
            ap=obj.attach_point
            lines.append(f'{ind}  Attached at local ({ap.x:.2f}, {ap.y:.2f}, {ap.z:.2f}).')
        if obj.tags: lines.append(f'{ind}  Tags: {", ".join(obj.tags)}.')
        lines.append('')
        for child in obj.children: describe(child, depth+1, world_M)

    for obj in scene.objects: describe(obj)

    lines += ['SPATIAL RELATIONSHIPS', '-'*30, '']
    flat = scene.all_objects()
    for i,a in enumerate(flat):
        for b in flat[i+1:]:
            pa=scene.world_pos(a); pb=scene.world_pos(b)
            d=_dist(pa,pb); off=Vec3(pb.x-pa.x,pb.y-pa.y,pb.z-pa.z)
            lines.append(f'  {b.id} is {d:.1f} units from {a.id} ({_direction_name(off)} {a.id}).')
    lines += ['', 'END OF SCENE DESCRIPTION', '='*50]

    with open(out_path,'w',encoding='utf-8') as f: f.write('\n'.join(lines))
    return f"Exported spatial text: {out_path} ({len(flat)} objects described)."


# -- SVG via POV-Ray (opt 4) --------------------------------------------------─

def export_svg_povray(scene, out_path, size=512):
    """Export scene as SVG by rendering via POV-Ray and embedding the PNG.
    Correct for ALL geometry including interpenetrating objects.
    The SVG is a standards-compliant wrapper; the image is base64-embedded.
    """
    import tempfile, subprocess, os, base64 as _b64

    # Write POV file to temp location
    with tempfile.NamedTemporaryFile(suffix='.pov', delete=False) as pf:
        pov_path = pf.name
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as imgf:
        png_path = imgf.name

    try:
        result = export_povray(scene, pov_path)
        if 'Error' in result or 'error' in result:
            return f"SVG(POV) failed at POV export: {result}"

        # Render with POV-Ray
        cmd = [
            'povray',
            f'+I{pov_path}',
            f'+O{png_path}',
            f'+W{size}', f'+H{size}',
            '+Q9',        # quality 9
            '+A0.3',      # antialiasing
            '-D',         # no display
            '+UA',        # alpha background
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if not os.path.exists(png_path) or os.path.getsize(png_path) == 0:
            return f"SVG(POV) failed: POV-Ray render error. {proc.stderr.decode()[:200]}"

        # Embed PNG as base64 in SVG
        with open(png_path, 'rb') as f:
            png_b64 = _b64.b64encode(f.read()).decode('ascii')

        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">\n'
            f'  <image x="0" y="0" width="{size}" height="{size}" '
            f'xlink:href="data:image/png;base64,{png_b64}"/>\n'
            '</svg>\n'
        )

        with open(out_path, 'w') as f:
            f.write(svg)

        kb = len(svg) // 1024
        return f"Exported SVG(POV): {out_path} ({size}×{size}px, {kb}KB)."

    finally:
        for p in [pov_path, png_path]:
            try: os.unlink(p)
            except: pass


def export_svg_trace(scene, out_path, size=512):
    """Export scene as TRUE VECTOR SVG via POV-Ray render + vtracer polygon trace.
    Pipeline: scene → POV-Ray render → PNG → vtracer → vector SVG paths.
    Result is fully scalable with no embedded raster. Works for ALL geometry.
    Requires: povray, vtracer (pip install vtracer)
    """
    import tempfile, subprocess, os

    with tempfile.NamedTemporaryFile(suffix='.pov', delete=False) as pf:
        pov_path = pf.name
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as imgf:
        png_path = imgf.name

    try:
        # Step 1: POV-Ray render
        result = export_povray(scene, pov_path)
        if 'Error' in result or 'error' in result:
            return f"SVG(trace) failed at POV stage: {result}"

        cmd = ['povray', f'+I{pov_path}', f'+O{png_path}',
               f'+W{size}', f'+H{size}', '+Q9', '+A0.3', '-D', '+UA']
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if not os.path.exists(png_path) or os.path.getsize(png_path) == 0:
            return f"SVG(trace) failed at POV render: {proc.stderr.decode()[:200]}"

        # Step 2: vtracer - PNG → vector SVG paths
        try:
            import vtracer
        except ImportError:
            return "SVG(trace) failed: vtracer not installed. Run: pip install vtracer"

        vtracer.convert_image_to_svg_py(
            png_path,
            out_path,
            colormode='color',
            hierarchical='stacked',
            mode='spline',
            filter_speckle=4,
            color_precision=6,
            layer_difference=16,
            corner_threshold=60,
            length_threshold=4.0,
            max_iterations=10,
            splice_threshold=45,
            path_precision=3,
        )

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            return "SVG(trace) failed: vtracer produced no output."

        import re
        content = open(out_path).read()
        n_paths = len(re.findall('<path', content))
        kb = os.path.getsize(out_path) // 1024
        return f"Exported SVG(trace): {out_path} ({n_paths} paths, {kb}KB, true vector)."

    finally:
        for p in [pov_path, png_path]:
            try: os.unlink(p)
            except: pass


def export_png_native(scene, out_path, size=512):
    """Export scene as PNG using Pillow -- no POV-Ray required.

    Uses IDENTICAL projection to ansi_render so the output is guaranteed
    to match the ANSI feedback view exactly. Sphere-based rasteriser with
    per-pixel z-buffer and simple diffuse+ambient lighting.

    Supports all primitive types (spheres, cubes, cylinders, etc.) via
    bounding-sphere approximation for non-sphere shapes. Not as
    photorealistic as POV-Ray but dependency-free and orientation-correct.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return "PNG native export requires Pillow: pip install Pillow"

    import math as _math

    vp       = scene.active_viewpoint()
    all_objs = scene.all_objects()
    if not all_objs:
        img = Image.new('RGBA', (size, size), (0,0,0,0))
        img.save(out_path)
        return f"Exported PNG (native): {out_path} ({size}x{size}px, empty scene)."

    az_r = _math.radians(vp.az)
    el_r = _math.radians(-vp.el if PITCH_INVERSION else vp.el)
    sc   = vp.scale
    _lx  = vp.look_at.x if vp.look_at else 0.0
    _ly  = vp.look_at.y if vp.look_at else 0.0
    _lz  = vp.look_at.z if vp.look_at else 0.0

    # Identical projection to ansi_render._view (our verified source of truth)
    def _view(x, y, z):
        x -= _lx; y -= _ly; z -= _lz
        rx  =  x*_math.cos(az_r) + z*_math.sin(az_r)
        rz  = -x*_math.sin(az_r) + z*_math.cos(az_r)
        ry2 =  y*_math.cos(el_r) - rz*_math.sin(el_r)
        rz2 =  y*_math.sin(el_r) + rz*_math.cos(el_r)
        depth = rz2
        if vp.roll:
            _rr = _math.radians(vp.roll)
            _cr, _sr = _math.cos(_rr), _math.sin(_rr)
            _sx, _sy = rx*sc, -ry2*sc
            return _sx*_cr - _sy*_sr, _sx*_sr + _sy*_cr, depth
        return rx*sc, -ry2*sc, depth

    def _hex_rgb(h):
        h = h.lstrip('#')
        return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))

    def _shade(rgb, normal_z, ambient=0.6, diffuse=0.4):
        """Simple lighting: ambient + diffuse from camera direction."""
        t = max(0.0, normal_z)
        r = int(min(255, rgb[0] * (ambient + diffuse*t)))
        g = int(min(255, rgb[1] * (ambient + diffuse*t)))
        b = int(min(255, rgb[2] * (ambient + diffuse*t)))
        return (r, g, b)

    # Project all objects
    projected = []
    for obj in all_objs:
        if _should_skip(obj): continue
        wp  = scene.world_pos(obj)
        sx, sy, depth = _view(wp.x, wp.y, wp.z)
        world_r = max(0.1, scene.world_radius(obj))
        r   = max(0.5, world_r * sc)
        rgb = _hex_rgb(obj.material.fill)
        projected.append({
            'sx': sx, 'sy': sy, 'depth': depth,
            'r': r, 'world_r': world_r, 'rgb': rgb,
            'opacity': obj.material.opacity,
            'id': obj.id,
            'type': obj.type,
            'label': obj.params.get('content') if obj.type == 'text' else None,
            'font_size': float(obj.params.get('size', 5.0)) if obj.type == 'text' else None,
        })

    if not projected:
        img = Image.new('RGBA', (size, size), (0,0,0,0))
        img.save(out_path)
        return f"Exported PNG (native): {out_path} ({size}x{size}px, no visible objects)."

    # Fixed canvas centred on look_at (which _view() maps to screen origin 0,0).
    # Use scene extent to determine scale, same as POV's angle-45 camera.
    # This matches POV framing: look_at is always at image centre.
    all_r = [p['r'] for p in projected]
    all_sx = [p['sx'] for p in projected]
    all_sy = [p['sy'] for p in projected]
    # Extent: furthest object edge from screen origin
    extent = max(
        max(abs(sx)+r for sx,r in zip(all_sx,all_r)),
        max(abs(sy)+r for sy,r in zip(all_sy,all_r)),
        1.0
    )
    pad_frac = 1.08   # 8% padding each side
    half = extent * pad_frac
    # half maps to size/2 pixels
    rw = rh = half * 2

    def to_px(sx, sy):
        x = (sx + half) / rw * size
        y = (sy + half) / rh * size
        return x, y

    def r_px(r):
        return max(2, int(r / rw * size))

    # Build image -- pure painter's algorithm (back-to-front)
    W = H = size
    img = Image.new('RGBA', (W, H), (0,0,0,0))
    draw_img = ImageDraw.Draw(img)

    # Sort back-to-front: largest depth painted first
    projected.sort(key=lambda p: p['depth'], reverse=True)

    # Z-buffer for tessellated geometry (cubes etc)
    import numpy as _np
    zbuf   = _np.full((H, W), _math.inf)
    pixels = _np.zeros((H, W, 4), dtype=_np.uint8)

    # -- Tessellated pass: cubes and other non-sphere primitives --
    # -- Tessellated pass: all geometry types except null/text --
    # Collect all triangles across all objects, project to screen, sort back-to-front
    _do_tess = size >= 128

    if _do_tess:
        # Build flat list of (d_avg, ax,ay, bx,by, cx,cy, r,g,b,a) for all front-facing tris
        tri_data = []
        for obj in all_objs:
            if obj.type in ('null', 'text'): continue
            parent  = scene.find_parent(obj.id)
            parent_M = scene.world_matrix_of(parent.id) if parent else None
            tris = tessellate_object(_obj_no_children(obj), parent_M, subdivisions=1)
            if not tris: continue
            mat  = obj.material
            rgb  = _hex_to_rgb(mat.fill) if mat.fill else (128,128,128)
            alpha = int(mat.opacity * 255)
            for tri in tris:
                # Project vertices
                pts = [_view(v[0], v[1], v[2]) for v in tri]
                ax,ay = to_px(pts[0][0], pts[0][1])
                bx,by = to_px(pts[1][0], pts[1][1])
                cx2,cy2 = to_px(pts[2][0], pts[2][1])
                # Back-face cull
                if (bx-ax)*(cy2-ay) - (by-ay)*(cx2-ax) >= 0: continue
                d_avg = (pts[0][2] + pts[1][2] + pts[2][2]) / 3
                # Face normal shading
                v0,v1,v2 = tri
                ex,ey,ez = v1[0]-v0[0],v1[1]-v0[1],v1[2]-v0[2]
                fx,fy,fz = v2[0]-v0[0],v2[1]-v0[1],v2[2]-v0[2]
                nx=ey*fz-ez*fy; ny=ez*fx-ex*fz; nz_w=ex*fy-ey*fx
                nm=_math.sqrt(nx*nx+ny*ny+nz_w*nz_w)
                if nm < 1e-10: continue
                nx,ny,nz_w = nx/nm, ny/nm, nz_w/nm
                rnx =  nx*_math.cos(az_r) + nz_w*_math.sin(az_r)
                rnz = -nx*_math.sin(az_r) + nz_w*_math.cos(az_r)
                rny2=  ny*_math.cos(el_r) - rnz*_math.sin(el_r)
                rnz2=  ny*_math.sin(el_r) + rnz*_math.cos(el_r)
                sr,sg,sb = _shade(rgb, -rnz2)
                tri_data.append((d_avg, ax,ay, bx,by, cx2,cy2, sr,sg,sb,alpha))

        # Sort back-to-front (painter's order -- larger depth = further away)
        tri_data.sort(key=lambda t: -t[0])

        # Rasterise all tris -- one meshgrid call per tri (fast at 256px, ok at 512px)
        for d_avg, ax,ay, bx,by, cx2,cy2, sr,sg,sb,alpha in tri_data:
            minx = max(0, int(min(ax,bx,cx2)))
            maxx = min(W-1, int(max(ax,bx,cx2))+1)
            miny = max(0, int(min(ay,by,cy2)))
            maxy = min(H-1, int(max(ay,by,cy2))+1)
            if minx > maxx or miny > maxy: continue
            denom = (by-cy2)*(ax-cx2) + (cx2-bx)*(ay-cy2)
            if abs(denom) < 1e-10: continue
            pxs = _np.arange(minx, maxx+1)
            pys = _np.arange(miny, maxy+1)
            gx, gy = _np.meshgrid(pxs, pys)
            w1 = ((by-cy2)*(gx-cx2) + (cx2-bx)*(gy-cy2)) / denom
            w2 = ((cy2-ay)*(gx-cx2) + (ax-cx2)*(gy-cy2)) / denom
            inside = (w1>=0) & (w2>=0) & (w1+w2<=1)
            closer = d_avg < zbuf[miny:maxy+1, minx:maxx+1]
            mask   = inside & closer
            if not mask.any(): continue
            zbuf  [miny:maxy+1, minx:maxx+1][mask] = d_avg
            pixels[miny:maxy+1, minx:maxx+1][mask] = (sr, sg, sb, alpha)

    # Composite tessellated geometry onto image
    tess_mask = zbuf < _math.inf
    if _do_tess and tess_mask.any():
        img_arr = _np.array(img)
        img_arr[tess_mask] = pixels[tess_mask]
        img = Image.fromarray(img_arr, 'RGBA')

    # -- Sphere pass: text labels only (everything else tessellated) --
    for p in projected:
        if _do_tess and p.get('type') != 'text': continue
        cx, cy = to_px(p['sx'], p['sy'])
        rp = r_px(p['r'])
        rgb = p['rgb']
        alpha = int(p['opacity'] * 255)
        rgba = (rgb[0], rgb[1], rgb[2], alpha)

        if p['label'] is not None:
            # Text primitive -- render as label with background rect
            label = p['label']
            font_px = max(10, int(p['font_size'] / rw * size * 8))
            try:
                from PIL import ImageFont
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', font_px)
            except Exception:
                try:
                    font = ImageFont.load_default()
                except Exception:
                    font = None
            if font:
                bbox = draw_img.textbbox((0,0), label, font=font)
            else:
                bbox = (0, 0, len(label)*font_px//2, font_px)
            tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
            tx = int(cx) - tw//2; ty = int(cy) - th//2
            pad2 = 3
            draw_img.rectangle([tx-pad2, ty-pad2, tx+tw+pad2, ty+th+pad2], fill=rgba)
            lum = 0.299*rgb[0] + 0.587*rgb[1] + 0.114*rgb[2]
            text_col = (0,0,0,255) if lum > 128 else (255,255,255,255)
            draw_img.text((tx, ty), label, font=font, fill=text_col)
        else:
            # Sphere primitive -- draw pixel by pixel
            x0 = max(0, int(cx - rp))
            x1 = min(W, int(cx + rp) + 1)
            y0 = max(0, int(cy - rp))
            y1 = min(H, int(cy + rp) + 1)
            for py in range(y0, y1):
                for px in range(x0, x1):
                    dx = px - cx; dy = py - cy
                    dist2 = dx*dx + dy*dy
                    if dist2 > rp*rp: continue
                    nz = _math.sqrt(max(0.0, 1.0 - dist2/(rp*rp)))
                    col = _shade(rgb, nz)
                    img.putpixel((px, py), (col[0], col[1], col[2], alpha))

    img.save(out_path)

    import os
    kb = os.path.getsize(out_path) // 1024
    return f"Exported PNG (native/Pillow): {out_path} ({size}x{size}px, {kb}KB)."


def export_png(scene, out_path, size=512):
    """Export scene as PNG.
    Uses POV-Ray if available for photorealistic output.
    Falls back to native Pillow renderer (no external dependencies).
    """
    import shutil
    if shutil.which('povray'):
        return _export_png_povray(scene, out_path, size)
    return export_png_native(scene, out_path, size)


def _export_png_povray(scene, out_path, size=512):
    """Export scene as PNG via POV-Ray (photorealistic, requires povray)."""
    import tempfile, subprocess, os
    with tempfile.NamedTemporaryFile(suffix='.pov', delete=False) as pf:
        pov_path = pf.name
    try:
        result = export_povray(scene, pov_path)
        if 'Error' in result or 'error' in result:
            return f"PNG export failed at POV stage: {result}"
        cmd = ['povray', f'+I{pov_path}', f'+O{out_path}',
               f'+W{size}', f'+H{size}', '+Q9', '+A0.3', '-D', '+UA']
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            return f"PNG export failed: POV-Ray error. {proc.stderr.decode()[:200]}"
        kb = os.path.getsize(out_path) // 1024
        return f"Exported PNG: {out_path} ({size}x{size}px, {kb}KB)."
    finally:
        try: os.unlink(pov_path)
        except: pass


# -- Export dispatcher --------------------------------------------------------─

def _export_disabled(scene, out_path, **kwargs):
    """Stub for not-yet-implemented exporters."""
    fmt = out_path.rsplit('.', 1)[-1].upper() if '.' in out_path else '?'
    return (f"Export '{fmt}' is not yet implemented. "
            f"Use an invalid format name to see all available formats.")


# -- BRAILLE ------------------------------------------------------------------

# Grade 1 (uncontracted) English Braille -- Unicode cell mapping.
# Each character maps to its Unicode Braille equivalent (U+2800-U+28FF).
# Compatible with all modern Braille displays and screen readers.
_BRAILLE_MAP = {
    'a':'\u2801','b':'\u2803','c':'\u2809','d':'\u2819','e':'\u2811',
    'f':'\u280b','g':'\u281b','h':'\u2813','i':'\u280a','j':'\u281a',
    'k':'\u2805','l':'\u2807','m':'\u280d','n':'\u281d','o':'\u2815',
    'p':'\u280f','q':'\u281f','r':'\u2817','s':'\u280e','t':'\u281e',
    'u':'\u2825','v':'\u2827','w':'\u283a','x':'\u282d','y':'\u283d',
    'z':'\u2835',
    ' ':'\u2800', '\n':'\u2800\n', '\t':'\u2800\u2800',
    '.':'\u2832', ',':'\u2802', ':':'\u2812', ';':'\u2806',
    '!':'\u2816', '?':'\u2826', '-':'\u2824', '/':'\u280c',
    '(':'\u2836', ')':'\u2836', '\'':'\u2804', '"':'\u2804',
    '=':'\u2836', '+':'\u2816', '*':'\u2814', '#':'\u283c', '@':'\u2801',
    '0':'\u281a','1':'\u2802','2':'\u2806','3':'\u2812','4':'\u2832',
    '5':'\u2822','6':'\u2816','7':'\u2836','8':'\u2826','9':'\u2814',
}
_BRAILLE_NUM_IND = '\u283c'   # number indicator

def _text_to_braille(text):
    """Convert plain text to Unicode Grade 1 Braille."""
    out = []; in_num = False
    for ch in text:
        if ch.isdigit():
            if not in_num:
                out.append(_BRAILLE_NUM_IND); in_num = True
            out.append(_BRAILLE_MAP.get(ch, ch))
        else:
            in_num = False
            out.append(_BRAILLE_MAP.get(ch.lower(), ch))
    return ''.join(out)


def _build_scene_text(scene):
    """Build plain-text scene description (shared by txt and braille exporters)."""
    all_objs = scene.all_objects()
    lines = [
        'DWARVEN MODELLER - SPATIAL SCENE DESCRIPTION',
        '=' * 50, '',
        f'Scene contains {len(all_objs)} objects.', '',
    ]
    if all_objs:
        positions=[scene.world_pos(o) for o in all_objs]
        radii    =[scene.world_radius(o) for o in all_objs]
        min_x=min(p.x-r for p,r in zip(positions,radii)); max_x=max(p.x+r for p,r in zip(positions,radii))
        min_y=min(p.y-r for p,r in zip(positions,radii)); max_y=max(p.y+r for p,r in zip(positions,radii))
        min_z=min(p.z-r for p,r in zip(positions,radii)); max_z=max(p.z+r for p,r in zip(positions,radii))
        lines.append(f'Dimensions: {max_x-min_x:.1f} wide, {max_y-min_y:.1f} tall, {max_z-min_z:.1f} deep.')
        lines.append('')
    lines += ['OBJECTS', '-'*30, '']
    for obj in all_objs:
        wp    = scene.world_pos(obj)
        eff_r = scene.world_radius(obj)
        lines.append(f'Object: {obj.id}')
        lines.append(f'  Type: {obj.type}')
        lines.append(f'  Size: radius {eff_r:.2f} units.')
        lines.append(f'  Position: {wp.x:.2f} right, {wp.y:.2f} up, {wp.z:.2f} forward.')
        if obj.material.fill:
            lines.append(f'  Color: {obj.material.fill}.')
        lines.append('')
    return all_objs, '\n'.join(lines)


def export_braille_text(scene, out_path):
    """Export scene description as Unicode Braille.
    Uses touchmap (Grade 2 contracted) if available, else Grade 1 fallback.
    Output uses Unicode Braille cells (U+2800-U+28FF).
    Compatible with all modern Braille displays and screen readers.
    """
    all_objs, plain_text = _build_scene_text(scene)

    # Try Grade 2 (contracted) via touchmap first -- preferred for readability
    try:
        from touchmap.encoder import text_to_braille as _t2b
        braille_text = _t2b(plain_text, grade=2, characterError=False)
        grade_note = 'Grade 2 contracted via touchmap'
    except ImportError:
        import sys
        print("WARNING: touchmap not installed -- falling back to Grade 1 uncontracted Braille.\n"
              "         For Grade 2 contracted Braille: pip install touchmap", file=sys.stderr)
        braille_text = _text_to_braille(plain_text)
        grade_note = 'Grade 1 uncontracted (install touchmap for Grade 2)'

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(braille_text)
    return f"Exported Braille ({grade_note}): {out_path} ({len(all_objs)} objects)."


def export_braille_render(scene, out_path, size=512):
    """Export scene as Braille dot-matrix art -- a tactile render for terminal/Braille display.
    Renders the scene to PNG via the native renderer, then converts to Braille cells
    using brailleart. Each 2x4 pixel block maps to one Braille cell.
    Useful for blind users: the Braille cell pattern approximates the visual scene layout.
    """
    import tempfile, os
    try:
        from brailleart.converter import convert as _ba_convert
    except ImportError:
        return "Braille render requires brailleart: pip install braille-art"

    # Render to temp PNG first
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        export_png_native(scene, tmp_path, size=size)
        braille_art = _ba_convert(tmp_path, width=80)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(braille_art)
        lines = braille_art.count('\n')
        return f"Exported Braille render: {out_path} ({lines} lines, 80 cols)."
    finally:
        os.unlink(tmp_path)


EXPORT_FORMATS = {
    # -- ACTIVE --
    'povray': export_povray, 'pov': export_povray,
    'png':        export_png,
    'png_native': export_png_native,
    # -- SVG (true vector via POV+vtracer, requires povray+vtracer) --
    'svg':        export_svg_trace,
    'svg_trace':  export_svg_trace,
    'obj':        export_obj,
    'stl':        export_stl,
    'x3d':        export_x3d,
    'gltf':       export_gltf,     'glb':    export_gltf,
    'txt':        export_spatial_text, 'text': export_spatial_text,
    'spatial':    export_spatial_text,
    'braille':    export_braille_text,
    'braille_render': export_braille_render,
}

def run_export(scene, fmt, out_path, size=512, subdivisions=None):
    """Dispatch to the correct exporter. Returns result string."""
    fn = EXPORT_FORMATS.get(fmt.lower())
    if not fn:
        known = ', '.join(sorted(set(EXPORT_FORMATS.keys())))
        raise ValueError(f"Unknown export format '{fmt}'. Use: {known}")
    # Pass size/subdivisions only to functions that accept them
    import inspect
    sig = inspect.signature(fn)
    kwargs = {}
    if 'size'         in sig.parameters and size is not None:         kwargs['size']         = size
    if 'subdivisions' in sig.parameters and subdivisions is not None: kwargs['subdivisions'] = subdivisions
    return fn(scene, out_path, **kwargs)


# ═════════════════════════════════════════════════════════════════════════════


def ansi_render(scene, char_w=72, char_h=32):
    """ANSI truecolour half-block render. Delegates to export_png_native
    at 256px then resizes to char_w x char_h*2 and converts to half-blocks.
    Guarantees ANSI and PNG renders are identical in content.
    """
    import tempfile as _tf, os as _os
    from PIL import Image as _PILImage
    pw, ph = char_w, char_h * 2
    with _tf.NamedTemporaryFile(suffix='.png', delete=False) as _tmp:
        tmp_path = _tmp.name
    try:
        export_png_native(scene, tmp_path, size=256)
        img = _PILImage.open(tmp_path).convert('RGBA').resize((pw, ph), _PILImage.LANCZOS)
    finally:
        _os.unlink(tmp_path)

    pixels = list(img.getdata())
    BG = (18, 18, 18)
    def fg(r,g,b): return f'\033[38;2;{r};{g};{b}m'
    def bg(r,g,b): return f'\033[48;2;{r};{g};{b}m'
    RST = '\033[0m'
    out = []
    for cy in range(char_h):
        line = ''
        for cx in range(pw):
            ur,ug,ub,ua = pixels[cy*2*pw + cx]
            lr,lg,lb,la = pixels[(cy*2+1)*pw + cx]
            if ua < 10: ur,ug,ub = BG
            if la < 10: lr,lg,lb = BG
            line += fg(ur,ug,ub) + bg(lr,lg,lb) + '▀'
        out.append(line + RST)
    seen = {}
    for obj in scene.all_objects():
        if obj.id not in seen and obj.material.fill:
            r,g,b = _hex_to_rgb(obj.material.fill)
            seen[obj.id] = (r,g,b)
    legend = '  ' + ' '.join(f'\033[38;2;{r};{g};{b}m●\033[0m {oid}'
                               for oid,(r,g,b) in list(seen.items())[:10])
    out.append(legend)
    return '\n'.join(out)


# ═════════════════════════════════════════════════════════════════════════════
# § EXPORTERS

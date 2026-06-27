"""DwarvenModeller -- tessellation: all shape geometry."""
from __future__ import annotations
import math
from .constants import *
from .math_utils import *
from .scene import *
# ═════════════════════════════════════════════════════════════════════════════



__all__ = ['_sphere_tris', '_dodecahedron_tris', 'tessellate_object', 'tessellate_scene', '_obj_no_children']

def _sphere_tris(r, subdivisions=3):
    """
    Tessellate a unit sphere by icosahedron subdivision.
    Returns triangles in LOCAL space (centred at origin, radius r).
    """
    phi = (1 + math.sqrt(5)) / 2
    base = []
    for v in [(-1,phi,0),(1,phi,0),(-1,-phi,0),(1,-phi,0),
              (0,-1,phi),(0,1,phi),(0,-1,-phi),(0,1,-phi),
              (phi,0,-1),(phi,0,1),(-phi,0,-1),(-phi,0,1)]:
        l = math.sqrt(sum(x*x for x in v))
        base.append(tuple(x/l for x in v))
    faces = [(0,11,5),(0,5,1),(0,1,7),(0,7,10),(0,10,11),
             (1,5,9),(5,11,4),(11,10,2),(10,7,6),(7,1,8),
             (3,9,4),(3,4,2),(3,2,6),(3,6,8),(3,8,9),
             (4,9,5),(2,4,11),(6,2,10),(8,6,7),(9,8,1)]
    verts = list(base); cache = {}
    def mid(i, j):
        key = (min(i,j), max(i,j))
        if key in cache: return cache[key]
        v1, v2 = verts[i], verts[j]
        m = tuple((a+b)/2 for a,b in zip(v1,v2))
        l = math.sqrt(sum(x*x for x in m))
        verts.append(tuple(x/l for x in m))
        cache[key] = len(verts)-1; return cache[key]
    for _ in range(subdivisions):
        nf = []
        for a,b,c in faces:
            ab=mid(a,b); bc=mid(b,c); ca=mid(c,a)
            nf += [(a,ab,ca),(b,bc,ab),(c,ca,bc),(ab,bc,ca)]
        faces = nf
    return [((verts[a][0]*r, verts[a][1]*r, verts[a][2]*r),
             (verts[b][0]*r, verts[b][1]*r, verts[b][2]*r),
             (verts[c][0]*r, verts[c][1]*r, verts[c][2]*r))
            for a,b,c in faces]


def _dodecahedron_tris(r):
    """
    Tessellate a dodecahedron by finding pentagonal face centres and
    fan-triangulating each pentagon. Returns triangles in LOCAL space.
    """
    phi = (1 + math.sqrt(5)) / 2
    raw = []
    for s1 in (1,-1):
        for s2 in (1,-1):
            for s3 in (1,-1): raw.append((s1,s2,s3))
    for s1 in (1,-1):
        for s2 in (1,-1):
            raw += [(0,s1*phi,s2/phi),(s1/phi,0,s2*phi),(s1*phi,s2/phi,0)]
    norm = math.sqrt(3)
    verts = [(x/norm*r, y/norm*r, z/norm*r) for x,y,z in raw]
    vc    = [(x/norm, y/norm, z/norm) for x,y,z in raw]
    face_centres = [
        (1,1,1),(1,1,-1),(1,-1,1),(1,-1,-1),
        (-1,1,1),(-1,1,-1),(-1,-1,1),(-1,-1,-1),
        (0,phi,1/phi),(0,-phi,1/phi),(0,phi,-1/phi),(0,-phi,-1/phi),
    ]
    tris = []
    for fc in face_centres:
        fl = math.sqrt(sum(x*x for x in fc))
        fd = tuple(x/fl for x in fc)
        dots = [(sum(vc[i][k]*fd[k] for k in range(3)), i) for i in range(len(vc))]
        dots.sort(reverse=True)
        pent = [i for _, i in dots[:5]]
        centre = tuple(sum(vc[i][k] for i in pent)/5 for k in range(3))
        tang_raw = (fd[1]-fd[2], fd[2]-fd[0], fd[0]-fd[1])
        tl = math.sqrt(sum(x*x for x in tang_raw)) or 1
        tang = tuple(x/tl for x in tang_raw)
        def angle(idx):
            v  = vc[idx]
            dv = tuple(v[k]-centre[k] for k in range(3))
            cos_t = sum(dv[k]*tang[k] for k in range(3))
            cross = (dv[1]*fd[2]-dv[2]*fd[1],
                     dv[2]*fd[0]-dv[0]*fd[2],
                     dv[0]*fd[1]-dv[1]*fd[0])
            sin_t = math.sqrt(sum(x*x for x in cross))
            if sum(cross[k]*fd[k] for k in range(3)) < 0: sin_t = -sin_t
            return math.atan2(sin_t, cos_t)
        pent.sort(key=angle)
        v0 = verts[pent[0]]
        for i in range(1, 3):
            tris.append((v0, verts[pent[i]], verts[pent[i+1]]))
    return tris


def tessellate_object(obj, world_matrix=None, subdivisions=None):
    """
    Tessellate a SceneObject into world-space triangles.

    world_matrix: accumulated parent world matrix (Mat4) or None for root.
    Returns list of ((x,y,z),(x,y,z),(x,y,z)) tuples.

    null primitives produce no triangles.
    Children are tessellated recursively with the updated world matrix.
    """
    local_M = obj.transform.matrix()
    M = (world_matrix * local_M) if world_matrix else local_M

    def tv(x, y, z):
        p = M * Vec3(x, y, z); return (p.x, p.y, p.z)

    t    = obj.type
    p    = obj.params
    subs = int(subdivisions or float(p.get('subdivisions', 3)))
    tris = []

    if t == 'null':
        pass   # no geometry

    elif t in ('sphere', 'icosahedron'):
        r = float(p.get('radius', 1.0))
        for a,b,c in _sphere_tris(r, subs):
            tris.append((tv(*a), tv(*b), tv(*c)))

    elif t == 'cube':
        w=float(p.get('width',1.0)); h=float(p.get('height',1.0)); d=float(p.get('depth',1.0))
        hw=w/2; hh=h/2; hd=d/2
        quads = [
            ((-hw,-hh, hd),( hw,-hh, hd),( hw, hh, hd),(-hw, hh, hd)),
            (( hw,-hh,-hd),(-hw,-hh,-hd),(-hw, hh,-hd),( hw, hh,-hd)),
            ((-hw,-hh,-hd),( hw,-hh,-hd),( hw,-hh, hd),(-hw,-hh, hd)),
            ((-hw, hh, hd),( hw, hh, hd),( hw, hh,-hd),(-hw, hh,-hd)),
            ((-hw,-hh,-hd),(-hw,-hh, hd),(-hw, hh, hd),(-hw, hh,-hd)),
            (( hw,-hh, hd),( hw,-hh,-hd),( hw, hh,-hd),( hw, hh, hd)),
        ]
        for a,b,c,d_ in quads:
            tris.append((tv(*a),tv(*b),tv(*c)))
            tris.append((tv(*a),tv(*c),tv(*d_)))

    elif t == 'tetrahedron':
        r = float(p.get('radius', 1.0))
        v0=(0,r,0)
        v1=(r*math.sqrt(8/9), -r/3, 0)
        v2=(-r*math.sqrt(2/9), -r/3,  r*math.sqrt(2/3))
        v3=(-r*math.sqrt(2/9), -r/3, -r*math.sqrt(2/3))
        for face in [(v0,v1,v2),(v0,v2,v3),(v0,v3,v1),(v1,v3,v2)]:
            tris.append(tuple(tv(*v) for v in face))

    elif t == 'octahedron':
        r = float(p.get('radius', 1.0))
        top=(0,r,0); bot=(0,-r,0); f=(r,0,0); bk=(-r,0,0); rt=(0,0,r); lt=(0,0,-r)
        for face in [(top,f,rt),(top,rt,bk),(top,bk,lt),(top,lt,f),
                     (bot,rt,f),(bot,bk,rt),(bot,lt,bk),(bot,f,lt)]:
            tris.append(tuple(tv(*v) for v in face))

    elif t == 'dodecahedron':
        r = float(p.get('radius', 1.0))
        for a,b,c in _dodecahedron_tris(r):
            tris.append((tv(*a), tv(*b), tv(*c)))

    elif t == 'cylinder':
        r    = float(p.get('radius', 1.0))
        h    = float(p.get('height', 2.0))
        segs = int(float(p.get('segments', 32)))  # B8: 32 default for smooth renders
        for i in range(segs):
            a0=2*math.pi*i/segs; a1=2*math.pi*(i+1)/segs
            x0=r*math.cos(a0); z0=r*math.sin(a0)
            x1=r*math.cos(a1); z1=r*math.sin(a1)
            yb=-h/2; yt=h/2
            tris += [(tv(x0,yb,z0),tv(x1,yb,z1),tv(x1,yt,z1)),
                     (tv(x0,yb,z0),tv(x1,yt,z1),tv(x0,yt,z0)),
                     (tv(0,yb,0),  tv(x1,yb,z1),tv(x0,yb,z0)),
                     (tv(0,yt,0),  tv(x0,yt,z0),tv(x1,yt,z1))]

    elif t == 'cone':
        # Truncated cone: base_radius at bottom, top_radius at top, height
        # top_radius=0 gives a true cone; top_radius>0 gives a frustum
        rb   = float(p.get('base_radius', 1.0))
        rt   = float(p.get('top_radius',  0.0))
        h    = float(p.get('height', 2.0))
        segs = int(float(p.get('segments', 16)))
        yb   = -h/2; yt = h/2
        for i in range(segs):
            a0=2*math.pi*i/segs; a1=2*math.pi*(i+1)/segs
            xb0=rb*math.cos(a0); zb0=rb*math.sin(a0)
            xb1=rb*math.cos(a1); zb1=rb*math.sin(a1)
            xt0=rt*math.cos(a0); zt0=rt*math.sin(a0)
            xt1=rt*math.cos(a1); zt1=rt*math.sin(a1)
            # Side faces
            tris += [(tv(xb0,yb,zb0),tv(xb1,yb,zb1),tv(xt1,yt,zt1)),
                     (tv(xb0,yb,zb0),tv(xt1,yt,zt1),tv(xt0,yt,zt0))]
            # Bottom cap
            tris.append((tv(0,yb,0), tv(xb1,yb,zb1), tv(xb0,yb,zb0)))
            # Top cap (only if top_radius > 0)
            if rt > 1e-6:
                tris.append((tv(0,yt,0), tv(xt0,yt,zt0), tv(xt1,yt,zt1)))

    elif t == 'capsule':
        # Cylinder with hemispherical end caps
        # Total height = cylinder height + 2 * radius (caps add one radius each end)
        r    = float(p.get('radius', 1.0))
        h    = float(p.get('height', 2.0))  # cylinder shaft height only
        segs = int(float(p.get('segments', 16)))
        half = segs // 2  # latitude segments per hemisphere
        yb   = -h/2; yt = h/2
        # Cylinder barrel
        for i in range(segs):
            a0=2*math.pi*i/segs; a1=2*math.pi*(i+1)/segs
            x0=r*math.cos(a0); z0=r*math.sin(a0)
            x1=r*math.cos(a1); z1=r*math.sin(a1)
            tris += [(tv(x0,yb,z0),tv(x1,yb,z1),tv(x1,yt,z1)),
                     (tv(x0,yb,z0),tv(x1,yt,z1),tv(x0,yt,z0))]
        # Hemispherical caps: latitude sweep from equator to pole
        for cap_sign in (+1, -1):  # +1 = top cap, -1 = bottom cap
            pole_y = yt + r if cap_sign > 0 else yb - r
            base_y = yt if cap_sign > 0 else yb
            for j in range(half):
                el0 = math.pi/2 * j     / half        # 0 at equator
                el1 = math.pi/2 * (j+1) / half        # pi/2 at pole
                if cap_sign < 0:
                    el0, el1 = -el0, -el1              # flip for bottom
                for i in range(segs):
                    a0=2*math.pi*i/segs; a1=2*math.pi*(i+1)/segs
                    # Ring at el0 (closer to equator)
                    r0=r*math.cos(el0); y0=base_y+r*math.sin(el0)*cap_sign
                    # Ring at el1 (closer to pole)
                    r1=r*math.cos(el1); y1=base_y+r*math.sin(el1)*cap_sign
                    x00=r0*math.cos(a0); z00=r0*math.sin(a0)
                    x01=r0*math.cos(a1); z01=r0*math.sin(a1)
                    x10=r1*math.cos(a0); z10=r1*math.sin(a0)
                    x11=r1*math.cos(a1); z11=r1*math.sin(a1)
                    tris += [(tv(x00,y0,z00),tv(x01,y0,z01),tv(x11,y1,z11)),
                             (tv(x00,y0,z00),tv(x11,y1,z11),tv(x10,y1,z10))]

    elif t == 'plane':
        w=float(p.get('width',10.0)); d=float(p.get('depth',10.0))
        hw=w/2; hd=d/2
        a=(-hw,0,-hd); b=(hw,0,-hd); c=(hw,0,hd); d_=(-hw,0,hd)
        tris = [(tv(*a),tv(*b),tv(*c)),(tv(*a),tv(*c),tv(*d_))]

    elif t == 'text':
        # Text has no triangle tessellation -- rendered via POV-Ray text{} primitive.
        # ANSI feedback shows the content string at projected position.
        tris = []

    elif t == 'torus':
        R    = float(p.get('outer_radius', 2.0))
        r    = float(p.get('inner_radius', 0.5))
        segs = int(float(p.get('segments', 16)))
        for i in range(segs):
            for j in range(segs):
                u0=2*math.pi*i/segs; u1=2*math.pi*(i+1)/segs
                v0=2*math.pi*j/segs; v1=2*math.pi*(j+1)/segs
                def tp(u, v):
                    return ((R+r*math.cos(v))*math.cos(u),
                             r*math.sin(v),
                            (R+r*math.cos(v))*math.sin(u))
                a_=tp(u0,v0); b_=tp(u1,v0); c_=tp(u1,v1); d__=tp(u0,v1)
                tris += [(tv(*a_),tv(*b_),tv(*c_)),(tv(*a_),tv(*c_),tv(*d__))]

    # Recurse into children with updated world matrix
    for child in obj.children:
        tris.extend(tessellate_object(child, M, subdivisions))

    return tris


def tessellate_scene(scene, subdivisions=None):
    """
    Tessellate all objects in scene, returning (triangles, material) pairs.
    Each pair covers one object's own geometry (not its children).
    null primitives and group containers are skipped.
    """
    result = []

    def collect(obj, parent_M=None):
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M
        if not _should_skip(obj):
            own_tris = tessellate_object(_obj_no_children(obj), parent_M, subdivisions)
            if own_tris:
                result.append((own_tris, obj.material))
        for child in obj.children:
            collect(child, world_M)

    for obj in scene.objects:
        collect(obj)
    return result


def _obj_no_children(obj):
    """Shallow copy of obj with no children - for per-object tessellation."""
    c = SceneObject(obj.id, obj.type)
    c.transform = obj.transform
    c.material  = obj.material
    c.params    = obj.params
    return c


# ═════════════════════════════════════════════════════════════════════════════

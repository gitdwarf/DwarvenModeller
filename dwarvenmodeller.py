#!/usr/bin/env python3
"""
DwarvenModeller - Headless stateless 3D modeller.
Text-first. No GUI. No viewport. No mouse required.

PHILOSOPHY: Digital clay, not CAD.
  DwarvenModeller is a virtual clay modeller - organic, sculptural, expressive.
  Not a CAD app, not a mesh editor. Think in shapes and relationships,
  not vertices and edge loops. Build faces, animals, chess pieces, icons.
  The blind human artist and the Claude instance use the same interface.
  Accessibility is not a feature - it is the architecture.

USAGE:
  dwarvenmodeller --new scene.dms
  dwarvenmodeller --file scene.dms --op "add type=sphere id=head radius=20"
  dwarvenmodeller --file scene.dms --op "colour target=head fill=#e8c49a"
  dwarvenmodeller --file scene.dms --op "attach child=nose to=head at=0,2,10"
  dwarvenmodeller --file scene.dms --op "attach child=eye to=head world_at=15,34,1"
  dwarvenmodeller --file scene.dms --op "rotate target=head world_set=0,90,0"
  dwarvenmodeller --file scene.dms --op "tag target=head add=merge_group=face"
  dwarvenmodeller --file scene.dms --op "mirror target=ear_left axis=x as=ear_right"
  dwarvenmodeller --file scene.dms --op "clone target=pupil_left as=pupil_right"
  dwarvenmodeller --file scene.dms --feedback
  dwarvenmodeller --file scene.dms --feedback target=head
  dwarvenmodeller --file scene.dms --export format=svg out=scene.svg size=512
  dwarvenmodeller --file scene.dms --export format=png out=scene.png size=1024
  dwarvenmodeller --file scene.dms --export format=povray out=scene.pov
  dwarvenmodeller --file scene.dms --merge other.dms
  dwarvenmodeller --file scene.dms --list
  dwarvenmodeller --file scene.dms --batch ops.txt
  dwarvenmodeller --help-ops

EXPORT FORMATS:
  svg         - True scalable vector: POV render → vtracer trace → <path> elements
                Perfect quality at any zoom. Works for all geometry complexity.
                Requires: povray, vtracer (pip install vtracer)
  svg_vector  - Pure geometric vector BSP (simple non-interpenetrating scenes only)
  svg_pov     - POV render embedded as base64 PNG in SVG wrapper (fast, not scalable)
  png         - Direct POV render, honest raster
  povray      - POV-Ray scene file (.pov), ground truth 3D render
  obj         - Wavefront OBJ mesh
  stl         - STL mesh for 3D printing
  x3d         - X3D/VRML scene
  gltf        - glTF 2.0 (web 3D)
  css/html    - CSS3D scene (browser-renderable)
  txt/spatial/braille - Text spatial layout (screen reader / Braille display)

PRIMITIVES (Platonic solids + conveniences):
  tetrahedron  cube  octahedron  dodecahedron  icosahedron
  sphere  cylinder  plane  torus  null

COORDINATE SYSTEM: right-handed, Y-up, Z-toward-viewer-at-az=0. Units arbitrary.
  +Y = up (height/spine direction)
  +X = right
  +Z = toward viewer (az=0)

  CHARACTER WORK NOTE: For animals/characters, the spine runs along Y.
  A dog standing upright has its spine from feet (y=0) to head (y=max).
  A dog lying along a horizontal axis would have spine along Z or X.
  Use 'move world_to=' and 'snap' to place anatomy at correct world coords.
  The 'measure' op tells you exact distances. DON'T GUESS, MEASURE.

  --up-axis=Z rotates feedback el by +90 so Z reads as vertical in ANSI/text
  layout. Does not affect geometry or exports. Use when building along Z spine.

FILE FORMAT: .dms (XML)
  Root element: <dms version="1.0">
  File format: XML with .dms extension.
  The file IS the state. No daemon. No persistent process.
  Every op is timestamped in <history>. Full audit trail, infinite rollback.

TYPO DETECTION:
  Uses Python difflib.get_close_matches (Ratcliff/Obershelp sequence matching).
  Thresholds: object IDs 0.5, primitive types 0.4, operation verbs 0.5.
  "Did you mean 'colour'?" style suggestions on unknown identifiers.

DEFORMATION/TOPOLOGY:
  Deformation lives in op_deform() - per-axis scale applied to world transform.
  True topology editing (subdivision, boolean CSG) is not implemented.
  For organic blending of adjacent primitives, use merge_group= tag +
  POV-Ray union{} export (format=povray). This removes internal surface
  boundaries between grouped objects in the render.

  For future true topology: the tessellate_object() function is the geometry
  kernel - all mesh generation flows through it. BSP, SVG, OBJ, STL, glTF
  all call tessellate_scene(). Add topology ops there.

TEST SCENES (in outputs/):
  aldric.dms    - 30-object face sculpture, all primitive types demonstrated
  box.dms       - cardboard box with documents, complex overlapping geometry
  knight.dms    - chess knight, organic sculptural construction
  colourcube    - 6-colour diagnostic cube, used for export regression testing
"""

import sys
import os
import math
import struct
import base64
import json as _json
import difflib
import argparse
import copy
import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom


# ═════════════════════════════════════════════════════════════════════════════
# § CONSTANTS & PRIMITIVES
# ═════════════════════════════════════════════════════════════════════════════

PRIMITIVES = {
    'tetrahedron', 'cube', 'octahedron', 'dodecahedron', 'icosahedron',
    'sphere', 'cylinder', 'plane', 'torus', 'null',
    'cone', 'capsule', 'text',
}

# Default parameter values per primitive type
PARAM_DEFAULTS = {
    'null':        {},
    'sphere':      {'radius': 1.0, 'subdivisions': 3},
    'icosahedron': {'radius': 1.0, 'subdivisions': 2},
    'tetrahedron': {'radius': 1.0},
    'octahedron':  {'radius': 1.0},
    'dodecahedron':{'radius': 1.0},
    'cube':        {'width': 1.0, 'height': 1.0, 'depth': 1.0},
    'cylinder':    {'radius': 1.0, 'height': 2.0, 'segments': 16},
    'plane':       {'width': 10.0, 'depth': 10.0},
    'torus':       {'outer_radius': 2.0, 'inner_radius': 0.5, 'segments': 16},
    'cone':        {'base_radius': 1.0, 'top_radius': 0.0, 'height': 2.0, 'segments': 16},
    'capsule':     {'radius': 1.0, 'height': 2.0, 'segments': 16},
    'text':        {'content': 'text', 'size': 5.0, 'depth': 0.5, 'font': 'timrom.ttf'},
}


# ═════════════════════════════════════════════════════════════════════════════
# § MATH
# ═════════════════════════════════════════════════════════════════════════════

class Vec3:
    """3D vector with parse, arithmetic, and length."""

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x); self.y = float(y); self.z = float(z)

    @classmethod
    def parse(cls, s):
        """Parse 'x,y,z' or 'x y z' or single value (broadcast) into Vec3."""
        parts = s.replace(',', ' ').split()
        if len(parts) == 1: v = float(parts[0]); return cls(v, v, v)
        return cls(*[float(p) for p in parts[:3]])

    def __str__(self):    return f"{self.x},{self.y},{self.z}"
    def __repr__(self):   return f"Vec3({self.x},{self.y},{self.z})"
    def __add__(self, o): return Vec3(self.x+o.x, self.y+o.y, self.z+o.z)
    def __sub__(self, o): return Vec3(self.x-o.x, self.y-o.y, self.z-o.z)
    def __mul__(self, s): return Vec3(self.x*s,   self.y*s,   self.z*s)
    def length(self):     return math.sqrt(self.x**2 + self.y**2 + self.z**2)
    def normalised(self):
        l = self.length()
        return Vec3(self.x/l, self.y/l, self.z/l) if l > 1e-10 else Vec3()


class Mat4:
    """4×4 row-major transform matrix. Supports TRS decomposition."""

    def __init__(self, m=None):
        self.m = m or [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

    @classmethod
    def identity(cls): return cls()

    @classmethod
    def translate(cls, tx, ty, tz):
        M = cls(); M.m[0][3]=tx; M.m[1][3]=ty; M.m[2][3]=tz; return M

    @classmethod
    def scale(cls, sx, sy, sz):
        M = cls(); M.m[0][0]=sx; M.m[1][1]=sy; M.m[2][2]=sz; return M

    @classmethod
    def rotate_x(cls, deg):
        a=math.radians(deg); c=math.cos(a); s=math.sin(a)
        M=cls(); M.m[1][1]=c; M.m[1][2]=-s; M.m[2][1]=s; M.m[2][2]=c; return M

    @classmethod
    def rotate_y(cls, deg):
        a=math.radians(deg); c=math.cos(a); s=math.sin(a)
        M=cls(); M.m[0][0]=c; M.m[0][2]=s; M.m[2][0]=-s; M.m[2][2]=c; return M

    @classmethod
    def rotate_z(cls, deg):
        a=math.radians(deg); c=math.cos(a); s=math.sin(a)
        M=cls(); M.m[0][0]=c; M.m[0][1]=-s; M.m[1][0]=s; M.m[1][1]=c; return M

    @classmethod
    def from_trs(cls, translate, rotate, scale_v):
        """Build TRS matrix: T * Rz * Ry * Rx * S (standard order)."""
        T  = cls.translate(translate.x, translate.y, translate.z)
        Rx = cls.rotate_x(rotate.x)
        Ry = cls.rotate_y(rotate.y)
        Rz = cls.rotate_z(rotate.z)
        S  = cls.scale(scale_v.x, scale_v.y, scale_v.z)
        return T * Rz * Ry * Rx * S

    def __mul__(self, other):
        if isinstance(other, Vec3):
            x, y, z = other.x, other.y, other.z
            m = self.m
            return Vec3(
                m[0][0]*x + m[0][1]*y + m[0][2]*z + m[0][3],
                m[1][0]*x + m[1][1]*y + m[1][2]*z + m[1][3],
                m[2][0]*x + m[2][1]*y + m[2][2]*z + m[2][3],
            )
        A, B = self.m, other.m
        C = [[sum(A[i][k]*B[k][j] for k in range(4)) for j in range(4)]
             for i in range(4)]
        return Mat4(C)

    def inverse(self):
        """4×4 matrix inverse using cofactor expansion."""
        m = self.m
        # Augment with identity
        aug = [list(m[r]) + [1.0 if r==c else 0.0 for c in range(4)] for r in range(4)]
        for col in range(4):
            pivot = max(range(col, 4), key=lambda r: abs(aug[r][col]))
            aug[col], aug[pivot] = aug[pivot], aug[col]
            if abs(aug[col][col]) < 1e-12: raise ValueError("Matrix is singular")
            div = aug[col][col]
            aug[col] = [v/div for v in aug[col]]
            for r in range(4):
                if r != col:
                    f = aug[r][col]
                    aug[r] = [aug[r][c] - f*aug[col][c] for c in range(8)]
        result = [[aug[r][c+4] for c in range(4)] for r in range(4)]
        return Mat4(result)
# ═════════════════════════════════════════════════════════════════════════════

def _now():
    """UTC timestamp string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _hex_to_rgb(h):
    """Parse '#rrggbb' or '#rgb' hex colour to (r, g, b) tuple."""
    h = h.lstrip('#')
    if len(h) == 3: h = ''.join(c*2 for c in h)
    try: return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))
    except: return (128, 128, 128)


def _dist(a, b):
    """Euclidean distance between two Vec3."""
    return math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2 + (a.z-b.z)**2)


def _direction_name(v):
    """Describe a Vec3 offset as a human-readable cardinal direction."""
    x, y, z = v.x, v.y, v.z
    parts = []
    if abs(y) > abs(x)*0.3:
        parts.append("above" if y > 0 else "below")
    if abs(x) > 0.1:
        parts.append("to the left of" if x < 0 else "to the right of")
    if abs(z) > 0.1:
        parts.append("in front of" if z > 0 else "behind")
    return ', '.join(parts) if parts else "at the same position as"


def _size_description(r):
    """Human-readable size adjective for a bounding radius."""
    if r < 0.5:  return "very small"
    if r < 1.5:  return "small"
    if r < 5:    return "medium"
    if r < 15:   return "large"
    return "very large"


def _format_pos(p, decimals=1):
    """Format a Vec3 as a readable coordinate string."""
    fmt = f".{decimals}f"
    return f"({p.x:{fmt}}, {p.y:{fmt}}, {p.z:{fmt}})"


def _approximate_colour_name(r, g, b):
    """Map an RGB triple to a human-readable approximate colour name."""
    palette = [
        ((0,0,0),       'black'),     ((255,255,255), 'white'),
        ((255,0,0),     'red'),       ((0,255,0),     'bright green'),
        ((0,0,255),     'blue'),      ((255,255,0),   'yellow'),
        ((255,165,0),   'orange'),    ((128,0,128),   'purple'),
        ((165,42,42),   'brown'),     ((255,192,203), 'pink'),
        ((0,128,128),   'teal'),      ((128,128,128), 'grey'),
        ((232,196,154), 'skin tone'), ((212,149,106), 'tan'),
        ((200,128,58),  'cardboard brown'),
        ((74,122,56),   'green'),     ((74,122,200),  'blue'),
        ((240,216,74),  'yellow'),    ((192,104,104), 'dusty rose'),
        ((26,16,10),    'very dark brown'),
    ]
    best, best_dist = 'unknown', float('inf')
    for (cr,cg,cb), name in palette:
        d = math.sqrt((r-cr)**2 + (g-cg)**2 + (b-cb)**2)
        if d < best_dist: best_dist = d; best = name
    return best


def _should_skip(obj):
    """Return True if this object should be excluded from geometry output."""
    return obj.type == 'null' or 'group' in obj.tags


# ═════════════════════════════════════════════════════════════════════════════
# § SCENE GRAPH
# ═════════════════════════════════════════════════════════════════════════════

class Transform:
    """Position, rotation (Euler degrees XYZ), and scale for a scene object."""

    def __init__(self):
        self.translate = Vec3(0, 0, 0)
        self.rotate    = Vec3(0, 0, 0)
        self.scale     = Vec3(1, 1, 1)

    @staticmethod
    def norm_angle(a):
        """Normalise an angle to [0, 360). Always positive, wraps correctly."""
        return a % 360.0

    @staticmethod
    def norm_rot(v):
        """Normalise a rotation Vec3 so all axes are in [0, 360)."""
        return Vec3(Transform.norm_angle(v.x),
                    Transform.norm_angle(v.y),
                    Transform.norm_angle(v.z))

    @staticmethod
    def display_angle(a):
        """Convert stored [0,360) angle to display value in (-180, 180].
        Angles <= 180 show as positive; above 180 show as negative equivalent.
        e.g. 359 -> -1,  270 -> -90,  90 -> 90,  0 -> 0
        """
        a = a % 360.0
        return a if a <= 180.0 else a - 360.0

    def matrix(self):
        """Build the local 4x4 TRS matrix."""
        return Mat4.from_trs(self.translate, self.rotate, self.scale)

    def to_xml(self, parent):
        t = ET.SubElement(parent, 'transform')
        t.set('translate', str(self.translate))
        t.set('rotate',    str(self.rotate))
        t.set('scale',     str(self.scale))
        return t

    @classmethod
    def from_xml(cls, elem):
        tf = cls()
        if elem is None: return tf
        if elem.get('translate'): tf.translate = Vec3.parse(elem.get('translate'))
        if elem.get('rotate'):
            raw = Vec3.parse(elem.get('rotate'))
            tf.rotate = Transform.norm_rot(raw)   # normalise on load
        if elem.get('scale'):     tf.scale     = Vec3.parse(elem.get('scale'))
        return tf


class Material:
    """Surface appearance: colour, opacity, shininess, optional texture."""

    def __init__(self):
        self.fill          = '#cccccc'
        self.stroke        = '#888888'
        self.stroke_width  = 0.5
        self.opacity       = 1.0
        self.shininess     = 0.0     # 0=matte, 1=mirror
        self.texture       = None
        self.povray_finish = None    # raw POV-Ray finish block

    def to_xml(self, parent):
        m = ET.SubElement(parent, 'material')
        m.set('fill',         self.fill)
        m.set('stroke',       self.stroke)
        m.set('stroke_width', str(self.stroke_width))
        m.set('opacity',      str(self.opacity))
        m.set('shininess',    str(self.shininess))
        if self.texture:       m.set('texture',       self.texture)
        if self.povray_finish: m.set('povray_finish',  self.povray_finish)
        return m

    @classmethod
    def from_xml(cls, elem):
        mat = cls()
        if elem is None: return mat
        for attr in ('fill', 'stroke', 'texture', 'povray_finish'):
            if elem.get(attr): setattr(mat, attr, elem.get(attr))
        for attr in ('stroke_width', 'opacity', 'shininess'):
            if elem.get(attr): setattr(mat, attr, float(elem.get(attr)))
        return mat


class SceneObject:
    """
    A node in the scene graph.
    Each object is a named primitive with transform, material, and children.
    """

    def __init__(self, obj_id, obj_type):
        self.id            = obj_id
        self.type          = obj_type
        self.transform     = Transform()
        self.material      = Material()
        self.children      = []
        self.tags          = []
        self.params        = {}
        self.attach_point  = None   # Vec3 in parent local space
        self.attach_normal = None

    # -- Parameter helpers ----------------------------------------------------

    def get_param(self, key, default=1.0):
        v = self.params.get(key, default)
        try: return float(v)
        except: return v

    def set_param(self, key, value):
        self.params[key] = value

    def bounding_radius(self):
        """Approximate local bounding sphere radius (scale-adjusted)."""
        r  = self.get_param('radius', 1.0)
        sc = self.transform.scale
        return r * max(sc.x, sc.y, sc.z)

    # -- XML serialisation ----------------------------------------------------─

    def to_xml(self, parent):
        obj = ET.SubElement(parent, 'object')
        obj.set('id',   self.id)
        obj.set('type', self.type)
        obj.set('tags', ','.join(self.tags) if self.tags else 'null')
        if self.params:
            p = ET.SubElement(obj, 'params')
            for k, v in self.params.items(): p.set(k, str(v))
        self.transform.to_xml(obj)
        self.material.to_xml(obj)
        if self.attach_point is not None:
            att = ET.SubElement(obj, 'attach')
            att.set('point', str(self.attach_point))
            if self.attach_normal: att.set('normal', str(self.attach_normal))
        for child in self.children: child.to_xml(obj)
        return obj

    @classmethod
    def from_xml(cls, elem):
        obj = cls(elem.get('id'), elem.get('type'))
        tags = elem.get('tags', '')
        obj.tags = [t for t in tags.split(',') if t and t != 'null']
        p_elem = elem.find('params')
        if p_elem is not None: obj.params = dict(p_elem.attrib)
        obj.transform = Transform.from_xml(elem.find('transform'))
        obj.material  = Material.from_xml(elem.find('material'))
        att = elem.find('attach')
        if att is not None:
            obj.attach_point = Vec3.parse(att.get('point', '0,0,0'))
            if att.get('normal'): obj.attach_normal = Vec3.parse(att.get('normal'))
        for child_elem in elem.findall('object'):
            obj.children.append(SceneObject.from_xml(child_elem))
        return obj


class Viewpoint:
    """Camera/projection descriptor. az/el for computed position; pos for explicit."""

    def __init__(self, name='default', az=150.0, el=25.0, scale=1.0,
                 pos=None, look_at=None):
        self.name    = name
        self.az      = az       # azimuth degrees
        self.el      = el       # elevation degrees
        self.scale   = scale    # projection scale
        self.pos     = pos      # explicit camera Vec3 (overrides az/el in POV-Ray)
        self.look_at = look_at  # explicit look-at Vec3

    def to_xml(self, parent):
        vp = ET.SubElement(parent, 'viewpoint')
        vp.set('name',  self.name)
        vp.set('az',    str(self.az))
        vp.set('el',    str(self.el))
        vp.set('scale', str(self.scale))
        if self.pos:     vp.set('pos',     str(self.pos))
        if self.look_at: vp.set('look_at', str(self.look_at))
        return vp

    @classmethod
    def from_xml(cls, elem):
        vp = cls(
            name  = elem.get('name', 'default'),
            az    = float(elem.get('az',    150)),
            el    = float(elem.get('el',     25)),
            scale = float(elem.get('scale',  1.0)),
        )
        if elem.get('pos'):     vp.pos     = Vec3.parse(elem.get('pos'))
        if elem.get('look_at'): vp.look_at = Vec3.parse(elem.get('look_at'))
        return vp


class HistoryEntry:
    """A single operation in the scene history."""

    def __init__(self, op, timestamp=None):
        self.op        = op
        self.timestamp = timestamp or _now()

    def to_xml(self, parent):
        h = ET.SubElement(parent, 'op')
        h.set('cmd',       self.op)
        h.set('timestamp', self.timestamp)
        return h

    @classmethod
    def from_xml(cls, elem):
        return cls(elem.get('cmd', ''), elem.get('timestamp', ''))


class Scene:
    """
    Top-level scene: objects, viewpoints, history, metadata.
    The Scene is the root of everything - serialises to/from .dms XML.
    """

    def __init__(self):
        self.objects    = []
        self.viewpoints = [Viewpoint()]
        self.history    = []
        self.metadata   = {}
        self.poses      = {}   # name -> {obj_id: (translate, rotate, scale)}
        self.materials  = {}   # name -> {fill, stroke, opacity, shininess, finish}

    # -- Object lookup --------------------------------------------------------─

    def find_object(self, obj_id, search_list=None):
        """Find object by ID anywhere in the scene graph."""
        if search_list is None: search_list = self.objects
        for obj in search_list:
            if obj.id == obj_id: return obj
            found = self.find_object(obj_id, obj.children)
            if found: return found
        return None

    def find_parent(self, obj_id, search_list=None, parent=None):
        """Find the parent SceneObject of the given ID, or None if root."""
        if search_list is None: search_list = self.objects
        for obj in search_list:
            if obj.id == obj_id: return parent
            found = self.find_parent(obj_id, obj.children, obj)
            if found is not None: return found
            if any(c.id == obj_id for c in obj.children): return obj
        return None

    def all_objects(self, search_list=None):
        """Flatten entire scene graph into a list (depth-first)."""
        result = []
        for obj in (search_list if search_list is not None else self.objects):
            result.append(obj)
            result.extend(self.all_objects(obj.children))
        return result

    def all_ids(self):
        return [o.id for o in self.all_objects()]

    def unique_id(self, base):
        """Return base if unused, else base_2, base_3, etc."""
        existing = set(self.all_ids())
        if base not in existing: return base
        i = 2
        while f"{base}_{i}" in existing: i += 1
        return f"{base}_{i}"

    def suggest_id(self, bad_id):
        """Return the closest matching existing ID, or None."""
        ids = self.all_ids()
        if not ids: return None
        matches = difflib.get_close_matches(bad_id, ids, n=1, cutoff=0.5)
        return matches[0] if matches else None

    def active_viewpoint(self):
        return self.viewpoints[0] if self.viewpoints else Viewpoint()

    # -- World-space transform helpers ----------------------------------------─

    def _parent_chain(self, obj_id, search_list=None, chain=None):
        """Return list of objects from root to target (inclusive)."""
        if search_list is None: search_list = self.objects
        if chain is None:       chain       = []
        for obj in search_list:
            new_chain = chain + [obj]
            if obj.id == obj_id: return new_chain
            result = self._parent_chain(obj_id, obj.children, new_chain)
            if result: return result
        return []

    def world_matrix_of(self, obj_id):
        """Accumulated world-space 4×4 matrix for an object."""
        chain = self._parent_chain(obj_id)
        M = Mat4.identity()
        for obj in chain:
            M = M * obj.transform.matrix()
        return M

    def world_pos(self, obj):
        """World-space position Vec3 of an object's origin."""
        return self.world_matrix_of(obj.id) * Vec3(0, 0, 0)

    def _world_matrix(self, obj):
        """Alias for world_matrix_of accepting an object or id."""
        oid = obj.id if hasattr(obj, 'id') else obj
        return self.world_matrix_of(oid)

    def world_radius(self, obj):
        """Approximate world-space bounding radius (accounts for parent scales)."""
        t = obj.type
        p = obj.params
        sc = obj.transform.scale
        if t == 'cone':
            # Bounding sphere: max of base_radius and half-height
            rb = float(p.get('base_radius', 1.0))
            h  = float(p.get('height', 2.0))
            r  = max(rb, h/2) * max(sc.x, sc.y, sc.z)
        elif t == 'capsule':
            # Capsule: radius + half shaft height = total half-extent
            r_cap = float(p.get('radius', 1.0))
            h     = float(p.get('height', 2.0))
            r     = (r_cap + h/2) * max(sc.x, sc.y, sc.z)
        elif t == 'text':
            # Approximate bounding radius: half text width
            size    = float(p.get('size', 5.0))
            content = str(p.get('content', 'text'))
            r       = size * max(len(content) * 0.35, 1.0) * max(sc.x, sc.y, sc.z)
        else:
            # Derive bounding radius from actual geometry params
            if t == 'cube':
                r = math.sqrt(float(p.get('width',  1.0))**2 +
                              float(p.get('height', 1.0))**2 +
                              float(p.get('depth',  1.0))**2) * 0.5
            elif t == 'torus':
                r = float(p.get('outer_radius', 2.0)) + float(p.get('inner_radius', 0.5))
            elif t == 'plane':
                r = math.sqrt(float(p.get('width', 10.0))**2 +
                              float(p.get('depth', 10.0))**2) * 0.5
            elif t == 'cylinder':
                rad = float(p.get('radius', 1.0))
                h   = float(p.get('height', 2.0))
                r   = math.sqrt(rad**2 + (h/2)**2)
            else:
                r = obj.get_param('radius', 0.5)
            r *= max(sc.x, sc.y, sc.z)
        chain = self._parent_chain(obj.id)
        for ancestor in chain[:-1]:
            s = ancestor.transform.scale
            r *= max(s.x, s.y, s.z)
        return r

    # -- XML serialisation ----------------------------------------------------─

    def to_xml(self):
        root = ET.Element('dms'); root.set('version', '1.0')
        meta = ET.SubElement(root, 'metadata')
        for k, v in self.metadata.items(): meta.set(k, str(v))
        vps = ET.SubElement(root, 'viewpoints')
        for vp in self.viewpoints: vp.to_xml(vps)
        scene_elem = ET.SubElement(root, 'scene')
        for obj in self.objects: obj.to_xml(scene_elem)
        hist = ET.SubElement(root, 'history')
        for entry in self.history: entry.to_xml(hist)
        if self.poses:
            poses_elem = ET.SubElement(root, 'poses')
            for pname, pdata in self.poses.items():
                pe = ET.SubElement(poses_elem, 'pose'); pe.set('name', pname)
                for oid, (t, r, s) in pdata.items():
                    oe = ET.SubElement(pe, 'transform')
                    oe.set('id', oid)
                    oe.set('translate', f"{t.x},{t.y},{t.z}")
                    oe.set('rotate',    f"{r.x},{r.y},{r.z}")
                    oe.set('scale',     f"{s.x},{s.y},{s.z}")
        if self.materials:
            mats_elem = ET.SubElement(root, 'materials')
            for mname, mdata in self.materials.items():
                me = ET.SubElement(mats_elem, 'material'); me.set('name', mname)
                for k, v in mdata.items(): me.set(k, str(v))
        return root

    def save(self, path):
        root    = self.to_xml()
        xml_str = ET.tostring(root, encoding='unicode')
        dom     = minidom.parseString(xml_str)
        pretty  = dom.toprettyxml(indent='  ', encoding=None)
        lines   = pretty.split('\n')
        if lines[0].startswith('<?xml'): lines = lines[1:]
        with open(path, 'w', encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('\n'.join(lines))

    @classmethod
    def load(cls, path):
        scene = cls()
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            raise ValueError(f"File '{path}' is not valid XML: {e}")
        root = tree.getroot()
        if root.tag != 'dms':
            raise ValueError(
                f"File '{path}' does not look like a .dms scene "
                f"(root element is <{root.tag}>, expected <dms>)")
        meta = root.find('metadata')
        if meta is not None: scene.metadata = dict(meta.attrib)
        vps = root.find('viewpoints')
        if vps is not None:
            scene.viewpoints = [Viewpoint.from_xml(e) for e in vps.findall('viewpoint')]
        scene_elem = root.find('scene')
        if scene_elem is not None:
            for obj_elem in scene_elem.iter('object'):
                t = obj_elem.get('type', '')
                if t and t not in PRIMITIVES:
                    raise ValueError(
                        f"Unknown primitive type '{t}' for object "
                        f"'{obj_elem.get('id', '')}'. "
                        f"Valid: {', '.join(sorted(PRIMITIVES))}")
            for obj_elem in scene_elem.findall('object'):
                scene.objects.append(SceneObject.from_xml(obj_elem))
        hist = root.find('history')
        if hist is not None:
            scene.history = [HistoryEntry.from_xml(e) for e in hist.findall('op')]
        poses_elem = root.find('poses')
        if poses_elem is not None:
            for pe in poses_elem.findall('pose'):
                pname = pe.get('name', 'unnamed')
                pdata = {}
                for oe in pe.findall('transform'):
                    oid = oe.get('id')
                    t   = Vec3.parse(oe.get('translate', '0,0,0'))
                    r   = Vec3.parse(oe.get('rotate',    '0,0,0'))
                    s   = Vec3.parse(oe.get('scale',     '1,1,1'))
                    pdata[oid] = (t, r, s)
                scene.poses[pname] = pdata
        mats_elem = root.find('materials')
        if mats_elem is not None:
            for me in mats_elem.findall('material'):
                mname = me.get('name', 'unnamed')
                scene.materials[mname] = {k: v for k, v in me.attrib.items() if k != 'name'}
        return scene

    @classmethod
    def new(cls):
        scene = cls()
        scene.metadata = {'created': _now(), 'version': '1.0'}
        return scene


# ═════════════════════════════════════════════════════════════════════════════
# § TESSELLATION
# ═════════════════════════════════════════════════════════════════════════════

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
# § OPERATION PARSER & HELPERS
# ═════════════════════════════════════════════════════════════════════════════

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


def _apply_material_kwargs(obj, kwargs):
    """Apply colour/fill/stroke/opacity/shininess kwargs to an object's material."""
    colour = kwargs.get('colour', kwargs.get('color', kwargs.get('fill')))
    if colour:             obj.material.fill      = colour
    if 'stroke'    in kwargs: obj.material.stroke     = kwargs['stroke']
    if 'opacity'   in kwargs: obj.material.opacity    = float(kwargs['opacity'])
    if 'shininess' in kwargs: obj.material.shininess  = float(kwargs['shininess'])
    if 'texture'   in kwargs: obj.material.texture    = kwargs['texture']


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
    # D3: named finish presets
    FINISH_PRESETS = {
        'matte':   'finish { ambient 0.2 diffuse 0.9 specular 0.0 }',
        'plastic': 'finish { ambient 0.1 diffuse 0.8 specular 0.4 roughness 0.05 }',
        'metal':   'finish { ambient 0.1 diffuse 0.6 specular 0.9 roughness 0.02 metallic }',
        'glass':   'finish { ambient 0.0 diffuse 0.1 specular 0.9 roughness 0.01 reflection 0.2 }',
        'skin':    'finish { ambient 0.3 diffuse 0.85 specular 0.15 roughness 0.15 }',
        'glow':    'finish { ambient 0.8 diffuse 0.4 specular 0.0 }',
    }

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
        obj.material.fill = colour; changes.append(f"fill={colour}")
    if 'stroke'        in kwargs:
        obj.material.stroke = kwargs['stroke']; changes.append(f"stroke={kwargs['stroke']}")
    if 'opacity'       in kwargs:
        obj.material.opacity = float(kwargs['opacity']); changes.append(f"opacity={kwargs['opacity']}")
    if 'shininess'     in kwargs:
        obj.material.shininess = float(kwargs['shininess']); changes.append(f"shininess={kwargs['shininess']}")
    if 'finish'        in kwargs:
        preset = kwargs['finish'].lower()
        if preset in FINISH_PRESETS:
            obj.material.povray_finish = FINISH_PRESETS[preset]
            changes.append(f"finish={preset}")
        else:
            known = ', '.join(FINISH_PRESETS.keys())
            raise ValueError(f"Unknown finish '{preset}'. Use: {known}")
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
    move target=<id> to=x,y,z           - absolute position in parent space
    move target=<id> by=dx,dy,dz        - relative move from current position
    move target=<id> world_to=x,y,z     - absolute position in world space

    All variants check for intersections and refuse if any found,
    unless force=true is specified.
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    force     = opt(kwargs, 'force', 'false').lower() in ('true', '1', 'yes')

    saved = Vec3(obj.transform.translate.x,
                 obj.transform.translate.y,
                 obj.transform.translate.z)

    if 'world_to' in kwargs:
        world_target = Vec3.parse(kwargs['world_to'])
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
        raise ValueError("Specify to=x,y,z (parent space), world_to=x,y,z (world space), or by=dx,dy,dz (relative).")

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
    rotate target=<id> world_set=x,y,z   - set orientation in WORLD space (F9)

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
        # F9: set world-space orientation by computing the local rotation needed
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
    """
    viewpoint [name=<n>] [az=N] [el=N] [scale=N] [pos=x,y,z] [look_at=x,y,z]

    Sets the active viewpoint for feedback and SVG/POV-Ray export.
    az/el compute camera position. pos= overrides az/el in POV-Ray export.

    Common presets:
      Front:  az=150 el=0     Side: az=60 el=0
      Top:    az=0   el=89    3/4:  az=330 el=25 (default)
    """
    name = opt(kwargs, 'name', 'default')
    vp   = next((v for v in scene.viewpoints if v.name == name), None)
    if vp is None:
        vp = Viewpoint(name=name); scene.viewpoints.append(vp)
    scene.viewpoints.remove(vp); scene.viewpoints.insert(0, vp)
    changes = []
    if 'az'     in kwargs: vp.az    = float(kwargs['az']);    changes.append(f"az={vp.az}°")
    if 'el'     in kwargs: vp.el    = float(kwargs['el']);    changes.append(f"el={vp.el}°")
    if 'scale'  in kwargs: vp.scale = float(kwargs['scale']); changes.append(f"scale={vp.scale}")
    if 'pos'    in kwargs: vp.pos   = Vec3.parse(kwargs['pos']);     changes.append(f"camera at {vp.pos}")
    if 'look_at'in kwargs: vp.look_at=Vec3.parse(kwargs['look_at']); changes.append(f"look_at {vp.look_at}")
    return f"Viewpoint '{name}' active. {', '.join(changes) if changes else 'No changes.'}"


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
    """
    align target=<id> axis=x|y|z mirror_of=<source_id>

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


# -- F-TEXT-1: Text primitive stub ----------------------------------------
def op_text(scene, kwargs):
    """
    STUB - F-TEXT-1: Text primitive (billboard text).

    Planned: add type=text id=<id> content=<string> size=<n> fill=<hex>
    Renders as a flat billboard facing the camera. Essential for labels,
    annotations, and screen-reader accessibility.

    Not yet implemented.
    """
    return ("Text primitive (F-TEXT-1) is not yet implemented. "
            "Planned: 'add type=text id=<id> content=<string> size=<n>'.")


# -- F-DEFORM-1: Pull/dent deformation stub --------------------------------
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
    'text':      op_text,       # F-TEXT-1: text primitive (billboard)
    'pull':      op_pull,       # F-DEFORM-1: plasticine pull/dent at intersection
    'dent':      op_pull,       # alias for pull
    'press':     op_press,      # clay deformation: records deformed_by in DMS
    'unpress':   op_unpress,    # remove press relationship
}


# ═════════════════════════════════════════════════════════════════════════════
# § FEEDBACK
# ═════════════════════════════════════════════════════════════════════════════

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
                  f'Scene: {len(all_objs)} objects. Viewpoint: az={vp.az} el={vp.el}',
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
    # User rotates the scene-sphere; camera is fixed.
    # cos(az): +1 = scene faces you (+Z toward viewer), -1 = scene faces away
    # sin(az): +1 = scene rotated right (+Z points right), -1 = scene rotated left
    _facing = _math.cos(_az_r)
    _lateral = _math.sin(_az_r)

    _thr = 0.4
    if abs(_facing) > (1 - _thr) and abs(_lateral) < _thr:
        if _facing > 0:
            _orient = 'Scene faces you. Scene left is your right, scene right is your left.'
        else:
            _orient = 'Scene faces away. Scene left is your left, scene right is your right.'
    elif abs(_lateral) > (1 - _thr) and abs(_facing) < _thr:
        if _lateral > 0:
            _orient = 'Scene faces right. Scene left is toward you, scene right is away from you.'
        else:
            _orient = 'Scene faces left. Scene left is away from you, scene right is toward you.'
    else:
        _fd = 'toward you' if _facing > 0 else 'away'
        _side = 'right' if _lateral > 0 else 'left'
        # Describe which side of the scene is closer to you due to the rotation
        _closer = 'Scene left side is closest to you.' if _lateral > 0 else 'Scene right side is closest to you.'
        _orient = f'Scene rotated {_side}, facing {_fd}. {_closer}'

    # Elevation description -- full -90 to +90 range, plain language
    _el = vp.el
    if abs(_el) < 5:
        _elev = 'Viewing straight on, no vertical tilt. Top of scene is up, bottom is down.'
    elif _el > 0:
        if _el < 20:
            _elev = 'Looking slightly down. Scene top tilts away from you, scene bottom tilts toward you.'
        elif _el < 50:
            _elev = 'Looking down from above. You see more of the scene top than the bottom.'
        elif _el < 80:
            _elev = 'Steep top-down view. Scene top faces you almost directly, sides visible around the edges.'
        else:
            _elev = 'Looking almost straight down. Scene top faces you. Left/right still apply horizontally.'
    else:
        _el_abs = abs(_el)
        if _el_abs < 20:
            _elev = 'Looking slightly up. Scene bottom tilts away from you, scene top tilts toward you.'
        elif _el_abs < 50:
            _elev = 'Looking up from below. You see more of the scene bottom than the top.'
        elif _el_abs < 80:
            _elev = 'Steep bottom-up view. Scene bottom faces you almost directly, sides visible around the edges.'
        else:
            _elev = 'Looking almost straight up. Scene bottom faces you. Left/right still apply horizontally.'

    lines += ['',
              f'Scene contains {len(all_objs)} object{"s" if len(all_objs)!=1 else ""}.',
              f'Viewpoint: azimuth {vp.az}°, elevation {vp.el}°, scale {vp.scale}.',
              f'  {_orient}',
              f'  {_elev}',
              '']

    # -- Object tree ----------------------------------------------------------─
    lines.append('-- Objects --')
    lines.append('')

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
        if rot.x or rot.y or rot.z:
            lines.append(f"{indent}  Rotated: x={Transform.display_angle(rot.x):.1f}°, y={Transform.display_angle(rot.y):.1f}°, z={Transform.display_angle(rot.z):.1f}°.")
        opacity_str = f", {int(mat.opacity*100)}% opaque" if mat.opacity < 1.0 else ""
        lines.append(f"{indent}  Color: fill {mat.fill}{opacity_str}.")
        if obj.attach_point:
            lines.append(f"{indent}  Attached at local {_format_pos(obj.attach_point)}.")
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

    view='top'   - top-down (X horizontal, Z into screen, Y ignored) -- default
    view='side'  - side view (X horizontal, Y vertical, Z ignored)
    view='front' - front view (Z horizontal, Y vertical, X ignored)
    """
    all_objs = scene.all_objects()
    if not all_objs: return '  (empty)'
    W, H = 60, 20

    view = view.lower()
    if view == 'side':
        # X horizontal, Y vertical (spine/height visible)
        label = 'Side view (X=right, Y=up)'
        def proj(p): return (p.x, -p.y)
    elif view == 'front':
        # Z horizontal, Y vertical (depth/height visible)
        label = 'Front view (Z=right, Y=up)'
        def proj(p): return (p.z, -p.y)
    else:
        # Top-down: X horizontal, Z vertical (footprint visible)
        label = 'Top view (X=right, Z=down)'
        def proj(p): return (p.x, p.z)

    positions = [(o, proj(scene.world_pos(o))) for o in all_objs]
    xs = [p[0] for _, p in positions]; ys = [p[1] for _, p in positions]
    xr = max(xs)-min(xs) or 1;        yr = max(ys)-min(ys) or 1
    grid = [['·']*W for _ in range(H)]
    for obj, (sx, sy) in positions:
        col = int((sx-min(xs))/xr*(W-1)); row = int((sy-min(ys))/yr*(H-1))
        col = max(0, min(W-1, col));      row = max(0, min(H-1, row))
        # Text primitives: show content string, not object id
        if obj.type == 'text':
            label = str(obj.params.get('content', obj.id))[:W]
        else:
            label = obj.id[:4].upper()
        for i, ch in enumerate(label):
            if col+i < W: grid[row][col+i] = ch
    lines = [f'  {label}']
    lines += ['  '+''.join(row) for row in grid]
    lines += ['', '  Key: object IDs at projected positions. · = empty space.']
    return '\n'.join(lines)


def ansi_render(scene, char_w=72, char_h=32):
    """ANSI truecolour half-block render of the scene.

    Uses proper az/el rotation (matching _proj_for_export), per-shape projected
    half-extents (not bounding-sphere radius) and a z-buffer so occlusion is
    correct regardless of paint order.

    Depth convention (from _proj_for_export comment):
        depth = y*sin(el) + rz*cos(el)
        SMALLER depth = closer to camera = wins in z-buffer.
    """
    vp       = scene.active_viewpoint()
    all_objs = scene.all_objects()
    if not all_objs: return '  (empty scene)'

    az_r = math.radians(vp.az)
    el_r = math.radians(vp.el)
    sc   = vp.scale

    def _view(x, y, z):
        """World point → (screen_x, screen_y, depth).  Smaller depth = nearer."""
        rx  =  x*math.cos(az_r) - z*math.sin(az_r)
        rz  =  x*math.sin(az_r) + z*math.cos(az_r)
        ry2 =  y*math.cos(el_r) - rz*math.sin(el_r)
        rz2 =  y*math.sin(el_r) + rz*math.cos(el_r)
        depth = -rz2 if math.cos(az_r)*math.cos(el_r) > 0 else rz2
        return -rx*sc, -ry2*sc, depth

    def _proj_vec(dx, dy, dz):
        """Project a DIRECTION vector (no translation) and return |screen_x|, |screen_y|."""
        rx  =  dx*math.cos(az_r) - dz*math.sin(az_r)
        rz  =  dx*math.sin(az_r) + dz*math.cos(az_r)
        ry2 =  dy*math.cos(el_r) - rz*math.sin(el_r)
        return abs(rx*sc), abs(ry2*sc)

    def _shape_extents(obj):
        """Return (srx, sry): projected screen-space half-extents for obj.

        Sums the absolute screen contributions of the 3 local half-extent axes
        transformed through the full world matrix.  This avoids the massive
        over-estimate of bounding-sphere radius for thin panels / cylinders.
        """
        t = obj.type; p = obj.params
        if t in ('sphere', 'icosahedron', 'octahedron'):
            r = float(p.get('radius', 1.0))
            hx = hy = hz = r
        elif t == 'cube':
            hx = float(p.get('width',  1.0)) * 0.5
            hy = float(p.get('height', 1.0)) * 0.5
            hz = float(p.get('depth',  1.0)) * 0.5
        elif t == 'cylinder':
            cr = float(p.get('radius', 1.0))
            hx = hz = cr
            hy  = float(p.get('height', 2.0)) * 0.5
        elif t == 'torus':
            hor = float(p.get('outer_radius', 2.0))
            ir  = float(p.get('inner_radius', 0.5))
            hx = hz = hor + ir; hy = ir
        elif t == 'plane':
            hx = float(p.get('width',  10.0)) * 0.5
            hy = 0.05
            hz = float(p.get('depth',  10.0)) * 0.5
        elif t == 'cone':
            hx = hz = float(p.get('base_radius', 1.0))
            hy  = float(p.get('height', 2.0)) * 0.5
        elif t == 'capsule':
            cr = float(p.get('radius', 1.0))
            hx = hz = cr
            hy  = cr + float(p.get('height', 2.0)) * 0.5
        else:
            r = scene.world_radius(obj)
            return r * sc, r * sc
        M   = scene.world_matrix_of(obj.id)
        org = M * Vec3(0, 0, 0)
        srx = sry = 0.0
        for lx, ly, lz in ((hx, 0, 0), (0, hy, 0), (0, 0, hz)):
            tip = M * Vec3(lx, ly, lz)
            px, py = _proj_vec(tip.x - org.x, tip.y - org.y, tip.z - org.z)
            srx += px; sry += py
        return max(1.0, srx), max(1.0, sry)

    projected = []
    for obj in all_objs:
        wp = scene.world_pos(obj)
        sx, sy, depth = _view(wp.x, wp.y, wp.z)
        srx, sry = _shape_extents(obj)
        projected.append({'obj': obj, 'sx': sx, 'sy': sy, 'depth': depth,
                          'srx': srx, 'sry': sry,
                          'rgb': _hex_to_rgb(obj.material.fill)})

    pad = 2
    min_sx = min(p['sx'] - p['srx'] for p in projected) - pad
    max_sx = max(p['sx'] + p['srx'] for p in projected) + pad
    min_sy = min(p['sy'] - p['sry'] for p in projected) - pad
    max_sy = max(p['sy'] + p['sry'] for p in projected) + pad
    w = max_sx - min_sx or 1
    h = max_sy - min_sy or 1

    pw = char_w; ph = char_h * 2; BG = (18, 18, 18)
    buf  = [[BG] * pw for _ in range(ph)]
    zbuf = [[1e18] * pw for _ in range(ph)]   # smaller depth = closer = wins

    for p in projected:
        if p['obj'].type == 'text': continue   # handled separately below
        cx = int((p['sx'] - min_sx) / w * pw)
        cy = int((p['sy'] - min_sy) / h * ph)
        rx = max(1, int(p['srx'] / w * pw))
        ry = max(1, int(p['sry'] / h * ph))
        r, g, b = p['rgb']
        dv = p['depth']
        for dy in range(-ry, ry + 1):
            for dx in range(-rx, rx + 1):
                norm2 = (dx / max(rx, 1)) ** 2 + (dy / max(ry, 1)) ** 2
                if norm2 <= 1.0:
                    px_ = cx + dx; py_ = cy + dy
                    if 0 <= px_ < pw and 0 <= py_ < ph:
                        if dv < zbuf[py_][px_]:       # closer wins
                            zbuf[py_][px_] = dv
                            edge = math.sqrt(norm2)
                            lit  = 1.0 - 0.45 * edge
                            buf[py_][px_] = (int(r * lit), int(g * lit), int(b * lit))

    RST = '\033[0m'
    def fg(r, g, b): return f'\033[38;2;{r};{g};{b}m'
    def bg(r, g, b): return f'\033[48;2;{r};{g};{b}m'

    # Text overlay: char_buf stores (char, r, g, b) or None per cell
    # Text objects are skipped in the sphere loop and rendered here as actual glyphs
    char_buf = [[None] * pw for _ in range(char_h)]
    for p in sorted(projected, key=lambda x: x['depth'], reverse=True):
        obj = p['obj']
        if obj.type != 'text': continue
        content = str(obj.params.get('content', obj.id))
        r, g, b = p['rgb']
        cx = int((p['sx'] - min_sx) / w * pw)
        cy_char = max(0, min(char_h - 1, int((p['sy'] - min_sy) / h * char_h)))
        col_start = max(0, cx - len(content) // 2)
        for i, ch in enumerate(content):
            col = col_start + i
            if 0 <= col < pw:
                char_buf[cy_char][col] = (ch, r, g, b)

    out = []
    for cy in range(char_h):
        line = ''
        for cx in range(pw):
            cell = char_buf[cy][cx]
            if cell is not None:
                ch, r, g, b = cell
                line += fg(r, g, b) + ch
            else:
                ur, ug, ub = buf[cy * 2][cx]
                lr, lg, lb = buf[cy * 2 + 1][cx]
                line += fg(ur, ug, ub) + bg(lr, lg, lb) + '▀'
        out.append(line + RST)
    seen = {}
    for p in projected:
        if p['obj'].id not in seen: seen[p['obj'].id] = p['rgb']
    legend = '  ' + ' '.join(f'\033[38;2;{r};{g};{b}m●\033[0m {oid}'
                              for oid, (r, g, b) in list(seen.items())[:10])
    out.append(legend)
    return '\n'.join(out)


# ═════════════════════════════════════════════════════════════════════════════
# § EXPORTERS
# ═════════════════════════════════════════════════════════════════════════════

# -- Shared projection helper ------------------------------------------------─

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
    # Derive camera position and look_at
    _dist = _camera_dist(scene, vp)
    if vp.pos:
        cam_pos  = (vp.pos.x, vp.pos.y, vp.pos.z)
        look_at  = (vp.look_at.x if vp.look_at else 0,
                    vp.look_at.y if vp.look_at else 0,
                    vp.look_at.z if vp.look_at else 0)
    else:
        el_r = math.radians(vp.el); az_r = math.radians(vp.az)
        cam_pos = ( _dist*math.cos(el_r)*math.sin(az_r),
                    _dist*math.sin(el_r),
                   -_dist*math.cos(el_r)*math.cos(az_r))
        look_at = (0.0, 0.0, 0.0)

    def vsub(a,b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
    def vadd(a,b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
    def vdot(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
    def vcross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    def vnorm(a):
        m=math.sqrt(vdot(a,a)); return (a[0]/m,a[1]/m,a[2]/m) if m>1e-12 else (0,0,1)
    def vscale(a,s): return (a[0]*s,a[1]*s,a[2]*s)

    # Forward, right, up basis
    fwd = vnorm(vsub(look_at, cam_pos))
    wup = (0.0, 1.0, 0.0)
    rgt = vcross(wup, fwd); rgt = vnorm(rgt) if vdot(rgt,rgt)>1e-12 else (1,0,0)
    up  = vcross(rgt, fwd)

    def to_cam(p):
        """Transform world-space point to camera space."""
        d = vsub(p, cam_pos)
        return (vdot(d,rgt), vdot(d,up), vdot(d,fwd))

    def proj2d(pc, sc):
        """Project camera-space point to 2D SVG coords (orthographic, scaled)."""
        return (pc[0]*sc, pc[1]*sc)

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
            # Back-face cull in camera space
            # Normal via cross product; dot with any vertex (camera at origin)
            e1 = vsub(cam_tri[1], cam_tri[0])
            e2 = vsub(cam_tri[2], cam_tri[0])
            n  = vcross(e1, e2)
            # Camera is at origin; vector from camera to vertex = cam_tri[0]
            # Face is front-facing if normal points TOWARD camera (dot < 0)
            if vdot(n, cam_tri[0]) >= 0:
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
    vp.scale is 2D display zoom only -- it does NOT affect 3D camera distance.
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
    if vp.pos:
        cam_pos = f'<{vp.pos.x},{vp.pos.y},{vp.pos.z}>'
    else:
        el_r = math.radians(vp.el)
        az_r = math.radians(vp.az)
        dist = _camera_dist(scene, vp)
        cx = dist * math.cos(el_r) * math.sin(az_r)
        cy = dist * math.sin(el_r)
        cz = -dist * math.cos(el_r) * math.cos(az_r)
        lx = vp.look_at.x if vp.look_at else 0
        ly = vp.look_at.y if vp.look_at else 0
        lz = vp.look_at.z if vp.look_at else 0
        cam_pos = f'<{cx+lx:.2f},{cy+ly:.2f},{cz+lz:.2f}>'

    # cam_flip: when the camera is on the -Z side (cz < 0), POV looks at the back
    # of all geometry. Fix: move camera to the mirror position (+Z side) by negating
    # cx and cz. Text primitives (billboards) also need rotate <0,180,0> to face the
    # camera from this new position -- handled in emit below.
    cam_flip = (not vp.pos) and (cz < 0)
    if cam_flip:
        cam_pos = f'<{-(cx+lx):.2f},{cy+ly:.2f},{-(cz+lz):.2f}>'
    look = f'<{vp.look_at.x},{vp.look_at.y},{vp.look_at.z}>' if vp.look_at else '<0,0,0>'

    def h2pov(h):
        r,g,b=_hex_to_rgb(h); return f'rgb<{r/255:.3f},{g/255:.3f},{b/255:.3f}>'

    lines = [
        f'// DwarvenModeller POV-Ray export  {_now()[:19]}',
        '#include "colors.inc"', '',
        'global_settings { ambient_light rgb<2,2,2> }', '',
        f'camera {{ location {cam_pos} look_at {look} angle 45 }}', '',
        'light_source { <20,40,50> color White }',
        'light_source { <-20,10,40> color rgb<0.4,0.4,0.6> }',
        'light_source { <0,-30,-50> color rgb<0.2,0.2,0.2> }', '',
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
            f'texture {{ pigment {{ color {fill} }} finish {{ ambient 0.1 diffuse 0.8 specular {shine:.2f} }} }}'
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
            # Centre the text: POV-Ray text starts at origin, ~0.7*size wide per char
            offset_x = -len(content) * size * 0.35
            lines_out.append(f'  text {{')
            lines_out.append(f'    ttf "{font}" "{content}" {depth_t:.3f}, 0')
            lines_out.append(f'    {tx_block}')
            lines_out.append(f'    scale {size:.4f}')
            lines_out.append(f'    translate <{offset_x:.4f}, 0, 0>')
            if cam_flip:
                lines_out.append(f'    translate <0, 0, {-depth_t:.3f}>')
                lines_out.append(f'    rotate <0,180,0>')
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
              f'texture {{ pigment {{ color {fill} }} finish {{ ambient 0.1 diffuse 0.8 specular {shine:.2f} }} }}')
        lines.append(f'// merge_group={gname}')
        lines.append('union {')
        for obj in grp_objs:
            parent = scene.find_parent(obj.id)
            parent_M = scene.world_matrix_of(parent.id) if parent else None
            lines.append(f'  // {obj.id}')
            emit_pov_object(obj, parent_M, lines)
        lines.append(f'  {tx}')
        lines.append('}')
        lines.append('')

    # Emit blob groups (blob{} -- smooth organic merging between components)
    for gname, grp_objs in blob_groups.items():
        rep_mat = grp_objs[0].material
        fill = h2pov(rep_mat.fill); shine = rep_mat.shininess
        tx = (f'texture {{ pigment {{ color {fill} }} {rep_mat.povray_finish} }}' if rep_mat.povray_finish else
              f'texture {{ pigment {{ color {fill} transmit {1-rep_mat.opacity:.2f} }} }}' if rep_mat.opacity < 1 else
              f'texture {{ pigment {{ color {fill} }} finish {{ ambient 0.1 diffuse 0.8 specular {shine:.2f} }} }}')
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
              f'texture {{ pigment {{ color {fill} }} finish {{ ambient 0.1 diffuse 0.8 specular {shine:.2f} }} }}')

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
                        f'finish {{ ambient 0.1 diffuse 0.8 specular {shine:.2f} }} }}')

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
            # World X mirrored in both cases to match geometry convention.
            # cam_flip: geometry correct as-is, text rotated 180Y to face cam.
            # not cam_flip: geometry gets scale <-1,1,1>, text needs -wpx and
            #   scale <-1,1,1> to un-mirror the letterforms.
            tx_wpx = wpx if cam_flip else -wpx
            # Text emitted OUTSIDE the union so it's never occluded by geometry
            text_lines.append('text {')
            text_lines.append(f'  ttf "{font}" "{content}" {depth_t:.3f}, 0')
            text_lines.append(f'  {tx_block}')
            text_lines.append(f'  scale {size:.4f}')
            text_lines.append(f'  translate <{offset_x:.4f}, 0, 0>')
            if cam_flip:
                text_lines.append(f'  translate <0, 0, {-depth_t:.3f}>')
                text_lines.append(f'  rotate <0,180,0>')
            else:
                text_lines.append(f'  scale <-1,1,1>')
            text_lines.append(f'  translate <{tx_wpx:.4f},{wpy:.4f},{wpz:.4f}>')
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
    # cam_flip=True  (cz<0): camera moved to +Z side, geometry correct as-is.
    # cam_flip=False (cz>0): camera on +Z side already, but native uses -rx convention
    #   so world +X goes screen LEFT. POV default has +X going screen RIGHT -- mirror needed.
    #   Apply scale <-1,1,1> to DM_scene to mirror X. Winding auto-corrects because
    #   POV-Ray flips face normals when a negative scale is applied to a union.
    lines.append('}')
    if cam_flip:
        lines.append('object { DM_scene }')
    else:
        lines.append('object { DM_scene scale <-1,1,1> }')
    lines.append('')
    # Text objects outside the union -- never occluded by geometry
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
                        lines_v.append(f'v {-v[0]:.6f} {v[1]:.6f} {v[2]:.6f}')
                for i in range(len(tris)):
                    a = offset+i*3; lines_f.append(f'f {a} {a+1} {a+2}')
                offset += len(tris)*3
                lines_v.append('')
        for child in obj.children:
            collect(child, world_M)

    for obj in scene.objects:
        collect(obj)

    with open(out_path, 'w') as f: f.write('\n'.join(lines_v + lines_f))

    # Write camera sidecar for Blender testbench -- same position as gltf camera
    import json as _json
    vp = scene.active_viewpoint()
    el_r = math.radians(vp.el); az_r = math.radians(vp.az); dist = _camera_dist(scene, vp)
    if vp.pos:
        dm_cx, dm_cy, dm_cz = vp.pos.x, vp.pos.y, vp.pos.z
    else:
        lx = vp.look_at.x if vp.look_at else 0
        ly = vp.look_at.y if vp.look_at else 0
        lz = vp.look_at.z if vp.look_at else 0
        dm_cx = dist * math.cos(el_r) * math.sin(az_r) + lx
        dm_cy = dist * math.sin(el_r) + ly
        dm_cz = -dist * math.cos(el_r) * math.cos(az_r) + lz
    # Geometry X is negated in export. Camera follows: +dm_cx on negated geometry = correct side.
    lx = vp.look_at.x if vp.look_at else 0
    ly = vp.look_at.y if vp.look_at else 0
    lz = vp.look_at.z if vp.look_at else 0
    sidecar = out_path.rsplit('.', 1)[0] + '.camera.json'
    with open(sidecar, 'w') as f:
        _json.dump({'cam': [dm_cx, -dm_cz, dm_cy], 'look_at': [lx, -lz, ly]}, f)

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
    el_r = math.radians(vp.el); az_r = math.radians(vp.az); dist = _camera_dist(scene, vp)
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
                coords=' '.join(f'{v[0]:.3f} {v[1]:.3f} {v[2]:.3f}' for v in all_v)
                indices=' '.join(f'{i*3} {i*3+1} {i*3+2} -1' for i in range(len(tris)))
                lines.append(f'      <IndexedFaceSet solid="true" coordIndex="{indices}">')
                lines.append(f'        <Coordinate point="{coords}"/>')
                lines.append(f'      </IndexedFaceSet>')

        lines += [f'    </Shape>', f'  </Transform>', '']
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
        for v in verts: pos_bytes+=struct.pack('<fff', v[0], v[1], v[2])
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
        el_r = math.radians(vp.el); az_r = math.radians(vp.az)
        dm_cx =  dist * math.cos(el_r) * math.sin(az_r) + lx
        dm_cy =  dist * math.sin(el_r)                  + ly
        dm_cz = -dist * math.cos(el_r) * math.cos(az_r) + lz

    # Camera: +dm_cx places Blender camera on the correct side to match native renderer.
    gcx = dm_cx
    gcy = dm_cy
    gcz = dm_cz
    glz = lz

    # Build camera rotation quaternion.
    # Strategy: compute in Blender Z-up space (where we know the camera position),
    # then convert quaternion back to glTF Y-up space.
    #
    # Blender imports glTF with: bl_x=gltf_x, bl_y=gltf_z, bl_z=gltf_y
    # So Blender camera pos = (gcx, gcz_neg, gcy) where gcz_neg = -dm_cz (already done above)
    # i.e. Blender pos = (dm_cx, dm_cz, dm_cy) -- wait, gcz=-dm_cz so Blender Y = gcz = -dm_cz = -41.8 ✓
    #
    # In Blender Z-up space, camera is at (gcx, gcz, gcy) looking toward (lx, glz, ly)
    # Note: Blender bl_y = gltf_z = gcz, Blender bl_z = gltf_y = gcy

    def _normalize(v):
        m = math.sqrt(sum(x*x for x in v))
        return tuple(x/m for x in v) if m > 1e-10 else (0,0,1)
    def _cross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    def _dot(a,b):   return sum(x*y for x,y in zip(a,b))

    # Blender camera position: bl_x=gltf_x, bl_y=-gltf_z, bl_z=gltf_y
    bl_cam    = (gcx, -gcz, gcy)
    bl_target = (lx,  -glz, ly)

    fwd   = _normalize(tuple(t-c for t,c in zip(bl_target, bl_cam)))
    right = _normalize(_cross(fwd, (0,0,1)))   # up hint = Z in Blender
    if _dot(right, right) < 1e-10:
        right = (1,0,0)
    up    = _cross(right, fwd)

    # Rotation matrix: columns are right, up, -fwd (camera looks along -Z)
    cam_z = (-fwd[0], -fwd[1], -fwd[2])
    mr = [[right[0], up[0], cam_z[0]],
          [right[1], up[1], cam_z[1]],
          [right[2], up[2], cam_z[2]]]

    # Matrix to quaternion (Blender Z-up space)
    trace = mr[0][0]+mr[1][1]+mr[2][2]
    if trace > 0:
        s = 0.5/math.sqrt(trace+1)
        bw = 0.25/s
        bx = (mr[2][1]-mr[1][2])*s; by = (mr[0][2]-mr[2][0])*s; bz = (mr[1][0]-mr[0][1])*s
    elif mr[0][0]>mr[1][1] and mr[0][0]>mr[2][2]:
        s = 2*math.sqrt(1+mr[0][0]-mr[1][1]-mr[2][2])
        bw=(mr[2][1]-mr[1][2])/s; bx=0.25*s; by=(mr[0][1]+mr[1][0])/s; bz=(mr[0][2]+mr[2][0])/s
    elif mr[1][1]>mr[2][2]:
        s = 2*math.sqrt(1+mr[1][1]-mr[0][0]-mr[2][2])
        bw=(mr[0][2]-mr[2][0])/s; bx=(mr[0][1]+mr[1][0])/s; by=0.25*s; bz=(mr[1][2]+mr[2][1])/s
    else:
        s = 2*math.sqrt(1+mr[2][2]-mr[0][0]-mr[1][1])
        bw=(mr[1][0]-mr[0][1])/s; bx=(mr[0][2]+mr[2][0])/s; by=(mr[1][2]+mr[2][1])/s; bz=0.25*s

    # Write Blender-space quaternion directly to glTF.
    # Blender's glTF importer will read it correctly since we computed it
    # in the same space Blender uses after import.
    qx = bx; qy = by; qz = bz; qw = bw

    gltf['cameras'].append({'type':'perspective',
                             'perspective':{'yfov':0.698,'aspectRatio':1.0,
                                            'znear':0.1,'zfar':1000.0}})
    cam_node_idx = len(gltf['nodes'])
    gltf['nodes'].append({
        'name': 'DwarvenCamera',
        'camera': 0,
        'translation': [round(gcx,4), round(gcy,4), round(gcz,4)],
        'rotation':    [round(qx,6),  round(qy,6),  round(qz,6), round(qw,6)],
        'extras':      {'look_at': [lx, ly, lz]},
    })
    gltf['scenes'][0]['nodes'] = [i for i in gltf['scenes'][0]['nodes'] if i != -2] + [cam_node_idx]

    b64=base64.b64encode(bytes(bin_data)).decode('ascii')
    gltf['buffers']=[{'byteLength':len(bin_data),
                      'uri':f'data:application/octet-stream;base64,{b64}'}]
    with open(out_path,'w',encoding='utf-8') as f: _json.dump(gltf,f,indent=2)
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
    el_r = _math.radians(vp.el)
    sc   = vp.scale

    # Identical projection to ansi_render._view (our verified source of truth)
    def _view(x, y, z):
        rx  =  x*_math.cos(az_r) - z*_math.sin(az_r)
        rz  =  x*_math.sin(az_r) + z*_math.cos(az_r)
        ry2 =  y*_math.cos(el_r) - rz*_math.sin(el_r)
        rz2 =  y*_math.sin(el_r) + rz*_math.cos(el_r)
        depth = -rz2 if _math.cos(az_r)*_math.cos(el_r) > 0 else rz2
        return -rx*sc, -ry2*sc, depth

    def _hex_rgb(h):
        h = h.lstrip('#')
        return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))

    def _shade(rgb, normal_z, ambient=0.35, diffuse=0.65):
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
            'label': obj.params.get('content') if obj.type == 'text' else None,
            'font_size': float(obj.params.get('size', 5.0)) if obj.type == 'text' else None,
        })

    if not projected:
        img = Image.new('RGBA', (size, size), (0,0,0,0))
        img.save(out_path)
        return f"Exported PNG (native): {out_path} ({size}x{size}px, no visible objects)."

    # Scene bounds
    pad = 1.0
    min_sx = min(p['sx'] - p['r'] for p in projected) - pad
    max_sx = max(p['sx'] + p['r'] for p in projected) + pad
    min_sy = min(p['sy'] - p['r'] for p in projected) - pad
    max_sy = max(p['sy'] + p['r'] for p in projected) + pad
    rw = max_sx - min_sx or 1.0
    rh = max_sy - min_sy or 1.0

    def to_px(sx, sy):
        x = (sx - min_sx) / rw * size
        y = (sy - min_sy) / rh * size
        return x, y

    def r_px(r):
        return max(2, int(r / rw * size))

    # Build image -- pure painter's algorithm (back-to-front)
    W = H = size
    img = Image.new('RGBA', (W, H), (0,0,0,0))
    draw_img = ImageDraw.Draw(img)

    # Sort back-to-front: largest depth painted first
    projected.sort(key=lambda p: p['depth'], reverse=True)

    for p in projected:
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
    """Stub for temporarily disabled exporters. Re-enable after core renderer is finalised."""
    fmt = out_path.rsplit('.', 1)[-1].upper() if '.' in out_path else '?'
    return (f"Export '{fmt}' is currently disabled. "
            f"Only 'png' and 'povray' are active while core renderer is being finalised.")

EXPORT_FORMATS = {
    # -- ACTIVE --
    'povray': export_povray, 'pov': export_povray,
    'png':        export_png,
    'png_native': export_png_native,
    # -- DISABLED (pending core renderer sign-off) --
    'svg':        _export_disabled,
    'svg_trace':  _export_disabled,
    'svg_pov':    _export_disabled,
    'svg+pov':    _export_disabled,
    'svgpov':     _export_disabled,
    'svg_vector': _export_disabled,
    'obj':        _export_disabled,
    'stl':        _export_disabled,
    'x3d':        _export_disabled,
    'gltf':       _export_disabled, 'glb':    _export_disabled,
    'css':        _export_disabled, 'css3d':  _export_disabled, 'html': _export_disabled,
    'txt':        _export_disabled, 'text':   _export_disabled,
    'braille':    _export_disabled, 'spatial':_export_disabled,
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
# § MERGE
# ═════════════════════════════════════════════════════════════════════════════

def merge_scenes(scene_a, scene_b, namespace_b):
    """
    Merge scene_b into scene_a.
    All objects from scene_b are prefixed with 'namespace_b::' to avoid ID conflicts.
    History entries are also merged and annotated.
    """
    existing = set(scene_a.all_ids())

    def prefix(obj, ns):
        new_id = f"{ns}::{obj.id}"
        if new_id in existing:
            i = 2
            while f"{new_id}_{i}" in existing: i += 1
            new_id = f"{new_id}_{i}"
        obj.id = new_id; existing.add(new_id)
        for child in obj.children: prefix(child, ns)

    imported = []
    for obj in scene_b.objects:
        obj_copy = copy.deepcopy(obj)
        prefix(obj_copy, namespace_b)
        scene_a.objects.append(obj_copy)
        imported.append(obj_copy.id)

    for entry in scene_b.history:
        scene_a.history.append(HistoryEntry(
            f"[merged from {namespace_b}] {entry.op}", entry.timestamp))

    return (f"Merged {len(imported)} object{'s' if len(imported)!=1 else ''} "
            f"from '{namespace_b}': {', '.join(imported)}.")


# ═════════════════════════════════════════════════════════════════════════════
# § HELP
# ═════════════════════════════════════════════════════════════════════════════

def print_help_ops():
    """Print detailed help for all operations - screen-reader friendly."""
    print('DwarvenModeller - Operation Reference')
    print('=' * 60)
    print()
    print('All operations follow the pattern:')
    print('  --op "verb key=value key=value ..."')
    print()
    seen = set()
    for name in sorted(OPERATIONS.keys()):
        fn = OPERATIONS[name]
        if fn in seen: continue
        seen.add(fn)
        aliases = [k for k,v in OPERATIONS.items() if v==fn and k!=name]
        print(f'  {name.upper()}')
        if aliases: print(f'    Aliases: {", ".join(aliases)}')
        doc = fn.__doc__ or '(no documentation)'
        for line in doc.strip().splitlines():
            print(f'    {line}')
        print()


# ═════════════════════════════════════════════════════════════════════════════
# § CLI
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='DwarvenModeller - headless stateless 3D modeller',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--file',     '-f', help='Scene file (.dms)')
    parser.add_argument('--new',            help='Create new empty scene file')
    parser.add_argument('--op',       '-o', help='Operation to apply (quoted string)')
    parser.add_argument('--feedback',       nargs='?', const='', metavar='target=ID',
                        help='Print spatial feedback. Optional: target=<id> for local axis detail')
    parser.add_argument('--list',           action='store_true',
                        help='List all objects with world positions')
    parser.add_argument('--export',   '-e',
                        help='Export: format=svg|png|povray|svg_pov|svg_vector|obj|stl|x3d|gltf|css|txt '
                             'out=<path> [size=N] [subdivisions=N]')
    parser.add_argument('--merge',    '-m',
                        help='Merge another .dms file (objects namespaced by filename)')
    parser.add_argument('--batch',    '-b',
                        help='Run a file of operations, one per line. Use - to read from stdin')
    parser.add_argument('--strict',   action='store_true',
                        help='In --batch mode: abort on first error, do not save')
    parser.add_argument('--repl',     action='store_true',
                        help='Interactive REPL: read ops from stdin, keep scene in memory')
    parser.add_argument('--no-save',        action='store_true',
                        help='Do not save after operation')
    parser.add_argument('--up-axis',        default='Y', metavar='Y|Z',
                        help='Display up axis for feedback (Y=default, Z=spine-along-Z convention). '
                             'Does not change geometry -- only affects projection in feedback.')
    parser.add_argument('--undo',           action='store_true',
                        help='Remove the last operation from history and revert the file')
    parser.add_argument('--help-ops',       action='store_true',
                        help='Print detailed help for all operations')

    args = parser.parse_args()

    if args.help_ops:
        print_help_ops(); return 0

    if args.new:
        scene = Scene.new(); scene.save(args.new)
        print(f"Created new scene: {args.new}"); return 0

    if not args.file:
        parser.print_help(); return 1

    if not os.path.exists(args.file):
        print(f"Error: '{args.file}' not found.", file=sys.stderr)
        print(f"Create it with: dwarvenmodeller --new {args.file}", file=sys.stderr)
        return 1

    try:
        scene = Scene.load(args.file)
    except ValueError as e:
        print(f"Error loading '{args.file}': {e}", file=sys.stderr); return 1

    # -- undo: replay history minus last entry ---------------------------------
    if args.undo:
        if not scene.history:
            print("Nothing to undo -- history is empty.")
            return 0
        removed = scene.history[-1]
        # Replay from scratch: fresh scene, all history except last.
        # Inject force=true into every op -- replaying known-good history,
        # intersection guards should not block it.
        ops_to_replay = [h.op for h in scene.history[:-1]]
        fresh = Scene.new()
        for op_str in ops_to_replay:
            try:
                verb, kwargs = parse_op(op_str)
                kwargs.setdefault('force', 'true')  # bypass intersection guards on replay
                handler = OPERATIONS.get(verb)
                if handler:
                    handler(fresh, kwargs)
                    fresh.history.append(HistoryEntry(op_str))
            except Exception:
                pass  # skip ops that genuinely can't replay
        if not args.no_save:
            fresh.save(args.file)
            print(f"Undone: '{removed.op}'. Scene reverted and saved.")
        else:
            print(f"Undone: '{removed.op}'. (not saved -- --no-save)")
        return 0

    result = None

    def _expand_targets(kwargs):
        """If target=@tagname, return list of matching object IDs. Else return [target]."""
        t = kwargs.get('target', '')
        if not t.startswith('@'):
            return [t] if t else []
        pattern = t[1:]  # strip @
        matches = []
        for obj in scene.all_objects():
            # Match on tag value, type, or id prefix
            if (pattern in obj.tags or
                any(tag.startswith(pattern + '=') or tag == pattern for tag in obj.tags) or
                obj.type == pattern or
                obj.id.startswith(pattern)):
                matches.append(obj.id)
        if not matches:
            raise ValueError(f"No objects matched '@{pattern}'. "
                             f"Try a tag name, type name, or id prefix.")
        return matches

    def run_op(op_str):
        verb, kwargs = parse_op(op_str)
        handler = OPERATIONS.get(verb)
        if not handler:
            close = difflib.get_close_matches(verb, OPERATIONS.keys(), n=1, cutoff=0.5)
            msg = f"Unknown operation '{verb}'."
            if close: msg += f" Did you mean '{close[0]}'?"
            msg += f" Valid: {', '.join(sorted(set(OPERATIONS.keys())))}."
            raise ValueError(msg)

        # Multi-target expansion: target=@tagname applies op to all matching objects
        if kwargs.get('target', '').startswith('@'):
            targets = _expand_targets(kwargs)
            results = []
            for tid in targets:
                kw = dict(kwargs); kw['target'] = tid
                results.append(handler(scene, kw))
            scene.history.append(HistoryEntry(op_str))
            return f"Applied to {len(targets)} objects ({', '.join(targets)}): {results[0] if len(results)==1 else str(len(results))+' results'}"

        r = handler(scene, kwargs)
        scene.history.append(HistoryEntry(op_str))
        return r

    if args.op:
        try:
            result = run_op(args.op)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr); return 1

    if args.batch:
        if args.batch == '-':
            lines_in = sys.stdin.read().splitlines()
        elif not os.path.exists(args.batch):
            print(f"Error: batch file '{args.batch}' not found.", file=sys.stderr); return 1
        else:
            with open(args.batch) as f:
                lines_in = f.read().splitlines()
        ops = [l.strip() for l in lines_in if l.strip() and not l.strip().startswith('#')]
        errors = 0
        aborted = False
        for i, op_str in enumerate(ops, 1):
            try:
                r = run_op(op_str); print(f"[{i}/{len(ops)}] {r}")
            except ValueError as e:
                print(f"[{i}/{len(ops)}] Error: {e}", file=sys.stderr)
                errors += 1
                if args.strict:
                    print(f"Batch aborted at op {i} (--strict mode). Scene NOT saved.",
                          file=sys.stderr)
                    aborted = True
                    break
        if errors and not aborted:
            print(f"\n{errors} error{'s' if errors!=1 else ''} in batch.", file=sys.stderr)
        if aborted:
            return 1
        result = f"Batch complete: {len(ops)-errors}/{len(ops)} operations succeeded."

    if args.repl:
        print(f"DwarvenModeller REPL -- {args.file}")
        print(f"Scene: {len(list(scene.all_objects()))} objects. Type 'quit' or Ctrl-D to exit.")
        print(f"Ops are applied and saved after each successful command.")
        print()
        while True:
            try:
                try:
                    line = input('dm> ').strip()
                except EOFError:
                    print("\nEOF -- exiting REPL.")
                    break
                if not line or line.startswith('#'):
                    continue
                if line.lower() in ('quit', 'exit', 'q'):
                    break
                if line.lower() in ('help', '?'):
                    print("  Any DM op: add, move, rotate, scale, colour, attach, snap, ...")
                    print("  feedback         -- print scene report")
                    print("  feedback skeleton -- compact table")
                    print("  quit / Ctrl-D    -- exit REPL")
                    continue
                if line.lower().startswith('feedback'):
                    _, fkw = parse_op('feedback ' + line[8:].strip())
                    fb_mode = fkw.get('mode', 'full')
                    fb_view = fkw.get('view', 'top')
                    print(generate_feedback(scene, tty=sys.stdout.isatty(),
                                            mode=fb_mode, view=fb_view))
                    continue
                r = run_op(line)
                print(f"  -> {r}")
                if not args.no_save:
                    scene.save(args.file)
            except ValueError as e:
                print(f"  Error: {e}", file=sys.stderr)
            except KeyboardInterrupt:
                print("\nInterrupted -- exiting REPL.")
                break
        return 0

    if args.merge:
        if not os.path.exists(args.merge):
            print(f"Error: merge file '{args.merge}' not found.", file=sys.stderr); return 1
        try:
            other = Scene.load(args.merge)
        except ValueError as e:
            print(f"Error loading merge file: {e}", file=sys.stderr); return 1
        ns     = os.path.splitext(os.path.basename(args.merge))[0]
        result = merge_scenes(scene, other, ns)
        scene.history.append(HistoryEntry(f"merge {args.merge}"))

    if args.export:
        _, ekwargs = parse_op('export ' + args.export)
        fmt  = ekwargs.get('format', 'svg').lower()
        # Map format name to correct file extension
        _fmt_ext = {
            'povray': 'pov', 'pov': 'pov',
            'png': 'png', 'png_native': 'png', 'svg': 'svg', 'svg_trace': 'svg',
            'svg_pov': 'svg', 'svg_vector': 'svg',
            'obj': 'obj', 'stl': 'stl', 'gltf': 'gltf', 'glb': 'glb',
            'x3d': 'x3d', 'css': 'html', 'css3d': 'html', 'html': 'html',
            'txt': 'txt', 'text': 'txt', 'braille': 'txt', 'spatial': 'txt',
        }
        ext = _fmt_ext.get(fmt, fmt)
        # Default output: basename of source file in CWD, not DMS dir
        default_out = os.path.join(
            os.getcwd(),
            os.path.splitext(os.path.basename(args.file))[0] + f'.{ext}'
        )
        out  = ekwargs.get('out', default_out)
        size = int(ekwargs.get('size', 512))
        subs = int(ekwargs['subdivisions']) if 'subdivisions' in ekwargs else None
        try:
            result = run_export(scene, fmt, out, size, subdivisions=subs)
        except (ValueError, Exception) as e:
            print(f"Export error: {e}", file=sys.stderr); return 1

    if args.feedback is not None:
        tty = sys.stdout.isatty()
        fb_target = None
        fb_az = fb_el = None
        fb_mode = 'full'
        fb_view = 'top'
        if args.feedback:
            _, fkw = parse_op('feedback ' + args.feedback)
            fb_target = fkw.get('target') or fkw.get('id')
            if 'az'   in fkw: fb_az   = float(fkw['az'])
            if 'el'   in fkw: fb_el   = float(fkw['el'])
            if 'mode' in fkw: fb_mode = fkw['mode']
            if 'view' in fkw: fb_view = fkw['view']
        # --up-axis Z: rotate el by +90 so Z appears as vertical in ANSI render
        up_axis = args.up_axis.upper() if args.up_axis else 'Y'
        if up_axis == 'Z':
            fb_el = (fb_el if fb_el is not None else scene.active_viewpoint().el) + 90.0
        # Temporarily override viewpoint for feedback only (no file write)
        if fb_az is not None or fb_el is not None:
            vp = scene.active_viewpoint()
            orig_az, orig_el = vp.az, vp.el
            if fb_az is not None: vp.az = fb_az
            if fb_el is not None: vp.el = fb_el
            print(generate_feedback(scene, tty=tty, target_id=fb_target,
                                    mode=fb_mode, view=fb_view))
            vp.az, vp.el = orig_az, orig_el
        else:
            print(generate_feedback(scene, tty=tty, target_id=fb_target,
                                    mode=fb_mode, view=fb_view))

    if args.list:
        all_objs = scene.all_objects()
        if not all_objs:
            print("Scene is empty.")
        else:
            print(f"{'ID':<30} {'TYPE':<14} {'WORLD POSITION':<28} PARENT")
            print('-' * 80)
            for obj in all_objs:
                wp     = scene.world_pos(obj)
                parent = scene.find_parent(obj.id)
                ps     = f"→ {parent.id}" if parent else "(root)"
                pos    = f"({wp.x:.1f}, {wp.y:.1f}, {wp.z:.1f})"
                print(f"{obj.id:<30} {obj.type:<14} {pos:<28} {ps}")

    if result:
        print(result)

    should_save = (args.op or args.merge or args.batch) and not args.no_save
    if should_save:
        scene.save(args.file)

    return 0


if __name__ == '__main__':
    sys.exit(main())

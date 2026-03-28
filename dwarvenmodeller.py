#!/usr/bin/env python3
"""
DwarvenModeller — Headless stateless 3D modeller.
Text-first. No GUI. No viewport. No mouse required.

PHILOSOPHY: Digital clay, not CAD.
  DwarvenModeller is a virtual clay modeller — organic, sculptural, expressive.
  Not a CAD app, not a mesh editor. Think in shapes and relationships,
  not vertices and edge loops. Build faces, animals, chess pieces, icons.
  The blind human artist and the Claude instance use the same interface.
  Accessibility is not a feature — it is the architecture.

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
  svg         — True scalable vector: POV render → vtracer trace → <path> elements
                Perfect quality at any zoom. Works for all geometry complexity.
                Requires: povray, vtracer (pip install vtracer)
  svg_vector  — Pure geometric vector BSP (simple non-interpenetrating scenes only)
  svg_pov     — POV render embedded as base64 PNG in SVG wrapper (fast, not scalable)
  png         — Direct POV render, honest raster
  povray      — POV-Ray scene file (.pov), ground truth 3D render
  obj         — Wavefront OBJ mesh
  stl         — STL mesh for 3D printing
  x3d         — X3D/VRML scene
  gltf        — glTF 2.0 (web 3D)
  css/html    — CSS3D scene (browser-renderable)
  txt/spatial/braille — Text spatial layout (screen reader / Braille display)

PRIMITIVES (Platonic solids + conveniences):
  tetrahedron  cube  octahedron  dodecahedron  icosahedron
  sphere  cylinder  plane  torus  null

COORDINATE SYSTEM: right-handed, Y-up, Z-toward-viewer-at-az=0. Units arbitrary.

FILE FORMAT: .dms (XML)
  Root element: <dms version="1.0">
  Legacy <dwm> root accepted for backwards compatibility.
  The file IS the state. No daemon. No persistent process.
  Every op is timestamped in <history>. Full audit trail, infinite rollback.

TYPO DETECTION:
  Uses Python difflib.get_close_matches (Ratcliff/Obershelp sequence matching).
  Thresholds: object IDs 0.5, primitive types 0.4, operation verbs 0.5.
  "Did you mean 'colour'?" style suggestions on unknown identifiers.

DEFORMATION/TOPOLOGY:
  Deformation lives in op_deform() — per-axis scale applied to world transform.
  True topology editing (subdivision, boolean CSG) is not implemented.
  For organic blending of adjacent primitives, use merge_group= tag +
  POV-Ray union{} export (format=povray). This removes internal surface
  boundaries between grouped objects in the render.

  For future true topology: the tessellate_object() function is the geometry
  kernel — all mesh generation flows through it. BSP, SVG, OBJ, STL, glTF
  all call tessellate_scene(). Add topology ops there.

TEST SCENES (in outputs/):
  aldric.dms    — 30-object face sculpture, all primitive types demonstrated
  box.dms       — cardboard box with documents, complex overlapping geometry
  knight.dms    — chess knight, organic sculptural construction
  colourcube    — 6-colour diagnostic cube, used for export regression testing
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

    def matrix(self):
        """Build the local 4×4 TRS matrix."""
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
        if elem.get('rotate'):    tf.rotate    = Vec3.parse(elem.get('rotate'))
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

    # ── Parameter helpers ────────────────────────────────────────────────────

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

    # ── XML serialisation ─────────────────────────────────────────────────────

    def to_xml(self, parent):
        obj = ET.SubElement(parent, 'object')
        obj.set('id',   self.id)
        obj.set('type', self.type)
        if self.tags: obj.set('tags', ','.join(self.tags))
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
        obj.tags = [t for t in tags.split(',') if t]
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
    The Scene is the root of everything — serialises to/from .dms XML.
    """

    def __init__(self):
        self.objects    = []
        self.viewpoints = [Viewpoint()]
        self.history    = []
        self.metadata   = {}

    # ── Object lookup ─────────────────────────────────────────────────────────

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

    # ── World-space transform helpers ─────────────────────────────────────────

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
        r  = obj.get_param('radius', 0.5) * max(
            obj.transform.scale.x,
            obj.transform.scale.y,
            obj.transform.scale.z)
        chain = self._parent_chain(obj.id)
        for ancestor in chain[:-1]:
            s = ancestor.transform.scale
            r *= max(s.x, s.y, s.z)
        return r

    # ── XML serialisation ─────────────────────────────────────────────────────

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
        if root.tag not in ('dms', 'dwm'):   # accept legacy dwm root
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

    elif t == 'plane':
        w=float(p.get('width',10.0)); d=float(p.get('depth',10.0))
        hw=w/2; hd=d/2
        a=(-hw,0,-hd); b=(hw,0,-hd); c=(hw,0,hd); d_=(-hw,0,hd)
        tris = [(tv(*a),tv(*b),tv(*c)),(tv(*a),tv(*c),tv(*d_))]

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
    """Shallow copy of obj with no children — for per-object tessellation."""
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
    Positional args become '_0', '_1', etc.
    """
    parts = op_str.strip().split()
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
                sphere cylinder plane torus null
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
                  'inner_radius', 'outer_radius', 'segments'):
        if param in kwargs: obj.set_param(param, float(kwargs[param]))

    if 'at'     in kwargs: obj.transform.translate = Vec3.parse(kwargs['at'])
    if 'scale'  in kwargs: obj.transform.scale     = Vec3.parse(kwargs['scale'])
    if 'rotate' in kwargs: obj.transform.rotate    = Vec3.parse(kwargs['rotate'])

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
    fill      — main body colour (hex)
    stroke    — outline/edge colour (hex)
    opacity   — 0.0 (invisible) to 1.0 (fully opaque)
    shininess — 0.0 (matte) to 1.0 (mirror)

    finish= named presets (D3) — maps to appropriate POV-Ray finish block:
      matte   — flat, no specular (clay, stone, fabric)
      plastic — medium shine, tight highlight (painted surfaces)
      metal   — high shininess, metallic look
      glass   — transparent, refractive-looking
      skin    — warm subsurface-style, soft highlight (faces, organic)
      glow    — high ambient, emissive-looking (lights, screens)

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


def op_move(scene, kwargs):
    """
    move target=<id> to=x,y,z       — absolute position in parent space
    move target=<id> by=dx,dy,dz    — relative move from current position
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    if 'to' in kwargs:
        obj.transform.translate = Vec3.parse(kwargs['to'])
        pos = obj.transform.translate
        return f"Moved '{target_id}' to ({pos.x}, {pos.y}, {pos.z}) in parent space."
    elif 'by' in kwargs:
        delta = Vec3.parse(kwargs['by'])
        obj.transform.translate = obj.transform.translate + delta
        pos = obj.transform.translate
        return f"Moved '{target_id}' by ({delta.x}, {delta.y}, {delta.z}). Now at ({pos.x}, {pos.y}, {pos.z})."
    else:
        raise ValueError("Specify to=x,y,z (absolute) or by=dx,dy,dz (relative).")


# ─────────────────────────────────────────────────────────────────────────────
# Intersection detection — Separating Axis Theorem for OBBs
# ─────────────────────────────────────────────────────────────────────────────

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
    rotate target=<id> x=deg              — rotate around object's local X axis
    rotate target=<id> y=deg              — rotate around object's local Y axis
    rotate target=<id> z=deg              — rotate around object's local Z axis
    rotate target=<id> x=deg y=deg z=deg  — compose all three in X→Y→Z order
    rotate target=<id> set=x,y,z         — set absolute Euler angles directly
    rotate target=<id> world_set=x,y,z   — set orientation in WORLD space (F9)

    Rotations are always relative to the object's own local axes — parent
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
        obj.transform.rotate = Vec3(rx, ry, rz)
    elif 'set' in kwargs:
        v = Vec3.parse(kwargs['set'])
        obj.transform.rotate = v
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
        obj.transform.rotate = Vec3(rx, ry, rz)

    collisions = _find_intersections(scene, target_id)
    if collisions and not force:
        obj.transform.rotate = saved
        raise ValueError(
            f"Rotation refused: '{target_id}' would intersect "
            f"{', '.join(collisions)}. Use force=true to override.")

    r   = obj.transform.rotate
    msg = f"'{target_id}' rotation: ({r.x:.1f}°, {r.y:.1f}°, {r.z:.1f}°)."
    if collisions:
        msg += f" WARNING: intersects {', '.join(collisions)} (forced)."
    return msg
    """
    rotate target=<id> x=deg              — rotate around object's local X axis
    rotate target=<id> y=deg              — rotate around object's local Y axis
    rotate target=<id> z=deg              — rotate around object's local Z axis
    rotate target=<id> x=deg y=deg z=deg  — compose all three in X→Y→Z order
    rotate target=<id> set=x,y,z         — set absolute Euler angles directly

    Rotations are always relative to the object's own local axes — parent
    chain rotations are transparent. x=30 always means "30° around this
    object's own X axis", regardless of how the parent is oriented.

    Use set= only when you need to force specific Euler values (rare).
    """
    target_id = require(kwargs, 'target')
    obj       = resolve_target(scene, target_id)
    force     = opt(kwargs, 'force', 'false').lower() in ('true', '1', 'yes')

    # Save rotation so we can restore if intersection check fails
    saved = Vec3(obj.transform.rotate.x, obj.transform.rotate.y, obj.transform.rotate.z)

    if 'set' in kwargs:
        v = Vec3.parse(kwargs['set'])
        obj.transform.rotate = v
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
        obj.transform.rotate = Vec3(rx, ry, rz)

    collisions = _find_intersections(scene, target_id)
    if collisions and not force:
        obj.transform.rotate = saved
        raise ValueError(
            f"Rotation refused: '{target_id}' would intersect "
            f"{', '.join(collisions)}. Use force=true to override.")

    r   = obj.transform.rotate
    msg = f"'{target_id}' rotation: ({r.x:.1f}°, {r.y:.1f}°, {r.z:.1f}°)."
    if collisions:
        msg += f" WARNING: intersects {', '.join(collisions)} (forced)."
    return msg


def op_scale(scene, kwargs):
    """
    scale target=<id> x=N y=N z=N   — set scale per axis
    scale target=<id> uniform=N     — uniform scale on all axes
    scale target=<id> by=sx,sy,sz   — multiply current scale

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
    deform target=<id> axis=x|y|z scale=N   — stretch along axis (immediate)
    deform target=<id> taper=N axis=y       — store taper for renderer
    deform target=<id> twist=N axis=y       — store twist for renderer
    deform target=<id> bend=N  axis=x       — store bend for renderer
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


def op_attach(scene, kwargs):
    """
    attach child=<id> to=<parent_id> [at=x,y,z] [world_at=x,y,z] [normal=x,y,z]

    Makes <child> a child of <parent>.
    at=       — position in parent's local space.
    world_at= — position in world space; DM computes the required local offset (F8).
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

    if 'world_at' in kwargs:
        # F8: convert world position to parent local space
        world_target = Vec3.parse(kwargs['world_at'])
        parent_world_M = scene._world_matrix(parent)
        # Invert parent world matrix to get world→local transform
        try:
            parent_inv = parent_world_M.inverse()
            local_pos = parent_inv * world_target
        except Exception:
            local_pos = world_target  # fallback if matrix not invertible
        child.attach_point = local_pos
        child.transform.translate = local_pos
    elif 'at' in kwargs:
        child.attach_point = Vec3.parse(kwargs['at'])
        child.transform.translate = Vec3.parse(kwargs['at'])

    if 'normal' in kwargs:
        child.attach_normal = Vec3.parse(kwargs['normal'])
    parent.children.append(child)
    wp = scene.world_pos(child)
    lp = child.transform.translate
    return (f"'{child_id}' attached to '{parent_id}'. "
            f"Local: ({lp.x:.2f}, {lp.y:.2f}, {lp.z:.2f}). "
            f"World: ({wp.x:.2f}, {wp.y:.2f}, {wp.z:.2f}).")
    """
    attach child=<id> to=<parent_id> [at=x,y,z] [normal=x,y,z]

    Makes <child> a child of <parent>. at= is in parent's local space.
    Prevents cycles. World position is reported after attaching.
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
    if 'at' in kwargs:
        child.attach_point = Vec3.parse(kwargs['at'])
        child.transform.translate = Vec3.parse(kwargs['at'])
    if 'normal' in kwargs:
        child.attach_normal = Vec3.parse(kwargs['normal'])
    parent.children.append(child)
    wp = scene.world_pos(child)
    lp = child.transform.translate
    return (f"'{child_id}' attached to '{parent_id}'. "
            f"Local: ({lp.x}, {lp.y}, {lp.z}). "
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


# ═════════════════════════════════════════════════════════════════════════════
# § OPERATIONS REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

OPERATIONS = {
    'add':       op_add,
    'color':     op_color,
    'colour':    op_color,     # British spelling alias
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
}


# ═════════════════════════════════════════════════════════════════════════════
# § FEEDBACK
# ═════════════════════════════════════════════════════════════════════════════

def generate_feedback(scene, tty=True, target_id=None):
    """
    Generate scene feedback.
    tty=True      → includes ANSI half-block render (for terminal)
    tty=False     → prose spatial layout (for screen readers / piped output)
    target_id     → if set, prints detailed local axis orientation for that object (F7)
    """
    lines = []
    sep   = '═' * 60
    lines.append(sep)
    lines.append('  DwarvenModeller — Scene Report')
    lines.append(sep)

    all_objs = scene.all_objects()

    if not all_objs:
        lines += ['', 'The scene is empty.',
                  '', 'To begin:', '  --op "add type=sphere id=myobject radius=10"', '']
        return '\n'.join(lines)

    vp = scene.active_viewpoint()
    lines += ['',
              f'Scene contains {len(all_objs)} object{"s" if len(all_objs)!=1 else ""}.',
              f'Viewpoint: azimuth {vp.az}°, elevation {vp.el}°, scale {vp.scale}.',
              '']

    # ── Object tree ───────────────────────────────────────────────────────────
    lines.append('── Objects ──')
    lines.append('')

    def describe(obj, depth=0, parent_M=None):
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M
        wp      = world_M * Vec3(0, 0, 0)
        sc      = obj.transform.scale
        rot     = obj.transform.rotate
        r       = obj.get_param('radius', obj.get_param('width', 1.0))
        eff_r   = r * max(sc.x, sc.y, sc.z)
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
            lines.append(f"{indent}  Rotated: x={rot.x:.1f}°, y={rot.y:.1f}°, z={rot.z:.1f}°.")
        opacity_str = f", {int(mat.opacity*100)}% opaque" if mat.opacity < 1.0 else ""
        lines.append(f"{indent}  Color: fill {mat.fill}{opacity_str}.")
        if obj.attach_point:
            lines.append(f"{indent}  Attached at local {_format_pos(obj.attach_point)}.")
        lines.append('')
        for child in obj.children: describe(child, depth+1, world_M)

    for obj in scene.objects: describe(obj)

    # ── Spatial relationships ─────────────────────────────────────────────────
    lines.append('── Spatial relationships ──')
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
    overlaps = []
    for i, a in enumerate(all_objs):
        for b in all_objs[i+1:]:
            pa = scene.world_pos(a); pb = scene.world_pos(b)
            d  = _dist(pa, pb)
            ra = scene.world_radius(a); rb = scene.world_radius(b)
            if d < ra + rb:
                pct = (ra+rb-d)/(ra+rb)*100
                is_child = (scene.find_parent(b.id) and scene.find_parent(b.id).id == a.id) or \
                           (scene.find_parent(a.id) and scene.find_parent(a.id).id == b.id)
                overlaps.append((a.id, b.id, ra+rb-d, pct, is_child))
    if overlaps:
        lines.append(f"Overlapping pairs ({len(overlaps)}):")
        for aid, bid, overlap, pct, is_child in overlaps:
            note = "normal for attached child" if is_child else "WARNING: unexpected intersection"
            lines.append(f"  '{aid}' ↔ '{bid}': {overlap:.2f} units ({pct:.0f}%) — {note}.")
    else:
        lines.append("No overlaps detected.")
    lines.append('')

    # ── Render ────────────────────────────────────────────────────────────────
    if tty:
        lines.append('── ANSI render (truecolour terminal) ──')
        lines.append('')
        lines.append(ansi_render(scene))
        lines.append('')
    else:
        lines.append('── Spatial layout ──')
        lines.append('')
        lines.append(text_layout_summary(scene))
        lines.append('')

    # ── History ───────────────────────────────────────────────────────────────
    if scene.history:
        n = len(scene.history)
        lines.append(f'── History ({n} op{"s" if n!=1 else ""}) ──')
        lines.append('')
        show = scene.history[-8:]
        if n > 8: lines.append(f'  (last 8 of {n})')
        for entry in show:
            ts = entry.timestamp[:19].replace('T', ' ') if entry.timestamp else ''
            lines.append(f'  [{ts}]  {entry.op}')
        lines.append('')

    lines.append(sep)

    # ── F7: Local axis orientation for target object ──────────────────────────
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
            lines.append(f"\n── Local axes for '{target_id}' in world space ──")
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


def text_layout_summary(scene):
    """ASCII-art spatial layout — screen-reader and Braille-display friendly."""
    all_objs = scene.all_objects()
    if not all_objs: return '  (empty)'
    vp  = scene.active_viewpoint()
    az  = math.radians(vp.az); el = math.radians(vp.el); sc = vp.scale
    W, H = 60, 20

    def proj(p):
        rx = p.x*math.cos(az) - p.z*math.sin(az)
        rz = p.x*math.sin(az) + p.z*math.cos(az)
        return (rx*sc, -(p.y - rz*math.sin(el))*sc)

    positions = [(o, proj(scene.world_pos(o))) for o in all_objs]
    xs=[p[0] for _,p in positions]; ys=[p[1] for _,p in positions]
    xr=max(xs)-min(xs) or 1; yr=max(ys)-min(ys) or 1
    grid=[['·']*W for _ in range(H)]
    for obj,(sx,sy) in positions:
        col=int((sx-min(xs))/xr*(W-1)); row=int((sy-min(ys))/yr*(H-1))
        col=max(0,min(W-1,col)); row=max(0,min(H-1,row))
        for i,ch in enumerate(obj.id[:4].upper()):
            if col+i<W: grid[row][col+i]=ch
    lines = ['  '+''.join(row) for row in grid]
    lines += ['', '  Key: object IDs at projected positions. · = empty space.']
    return '\n'.join(lines)


def ansi_render(scene, char_w=72, char_h=32):
    """ANSI truecolour half-block render of the scene."""
    vp       = scene.active_viewpoint()
    all_objs = scene.all_objects()
    if not all_objs: return '  (empty scene)'

    az=math.radians(vp.az); el=math.radians(vp.el); sc=vp.scale

    def proj(p):
        rx=p.x*math.cos(az)-p.z*math.sin(az)
        rz=p.x*math.sin(az)+p.z*math.cos(az)
        return (rx*sc, -(p.y-rz*math.sin(el))*sc)

    projected = []
    for obj in all_objs:
        wp=scene.world_pos(obj); sx,sy=proj(wp)
        depth=wp.x*math.sin(az)+wp.z*math.cos(az)-wp.y*math.sin(el)
        projected.append({'obj':obj,'sx':sx,'sy':sy,'depth':depth,
                          'r':max(0.5,scene.world_radius(obj)*sc),
                          'rgb':_hex_to_rgb(obj.material.fill)})
    projected.sort(key=lambda p: p['depth'], reverse=True)

    pad=1
    min_sx=min(p['sx']-p['r'] for p in projected)-pad
    max_sx=max(p['sx']+p['r'] for p in projected)+pad
    min_sy=min(p['sy']-p['r'] for p in projected)-pad
    max_sy=max(p['sy']+p['r'] for p in projected)+pad
    w=max_sx-min_sx or 1; h=max_sy-min_sy or 1

    pw=char_w; ph=char_h*2; BG=(18,18,18)
    buf=[[BG]*pw for _ in range(ph)]

    for p in projected:
        cx=int((p['sx']-min_sx)/w*pw); cy=int((p['sy']-min_sy)/h*ph)
        rx=max(1,int(p['r']/w*pw));    ry=max(1,int(p['r']/h*ph))
        r,g,b=p['rgb']
        for dy in range(-ry,ry+1):
            for dx in range(-rx,rx+1):
                if (dx/max(rx,1))**2+(dy/max(ry,1))**2<=1.0:
                    px=cx+dx; py=cy+dy
                    if 0<=px<pw and 0<=py<ph:
                        edge=math.sqrt((dx/max(rx,1))**2+(dy/max(ry,1))**2)
                        lit=1.0-0.45*edge
                        buf[py][px]=(int(r*lit),int(g*lit),int(b*lit))

    RST='\033[0m'
    def fg(r,g,b): return f'\033[38;2;{r};{g};{b}m'
    def bg(r,g,b): return f'\033[48;2;{r};{g};{b}m'
    out=[]
    for cy in range(char_h):
        line=''
        for cx in range(pw):
            ur,ug,ub=buf[cy*2][cx]; lr,lg,lb=buf[cy*2+1][cx]
            line+=fg(ur,ug,ub)+bg(lr,lg,lb)+'▀'
        out.append(line+RST)
    seen={}
    for p in projected:
        if p['obj'].id not in seen: seen[p['obj'].id]=p['rgb']
    legend='  '+' '.join(f'\033[38;2;{r};{g};{b}m●\033[0m {oid}'
                          for oid,(r,g,b) in list(seen.items())[:10])
    out.append(legend)
    return '\n'.join(out)


# ═════════════════════════════════════════════════════════════════════════════
# § EXPORTERS
# ═════════════════════════════════════════════════════════════════════════════

# ── Shared projection helper ─────────────────────────────────────────────────

def _proj_for_export(vp):
    """Return (proj, depth, face_nz) functions for the given viewpoint.

    Uses proper az/el rotation matrix — not a shear approximation.
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
        return (rx * sc, -ry2 * sc)  # SVG Y flipped

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
        Uses 3D world-space normal dot camera-direction — correct for all angles.
        Also returns the projected 2D cross product magnitude for screen-area tests.
        """
        a, b, c = tri
        # World-space face normal via cross product
        ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
        ac = (c[0]-a[0], c[1]-a[1], c[2]-a[2])
        nx = ab[1]*ac[2] - ab[2]*ac[1]
        ny = ab[2]*ac[0] - ab[0]*ac[2]
        nz = ab[0]*ac[1] - ab[1]*ac[0]
        # Dot with camera direction — negative means face points TOWARD camera = visible
        dot = nx*_cam_dir_x + ny*_cam_dir_y + nz*_cam_dir_z
        # Return magnitude (for screen area check) with sign flipped so positive = visible
        return -dot

    return proj, depth, face_nz


def _skip_in_emit(obj):
    """True if this object should be skipped in analytical exporters (null/group)."""
    return obj.type == 'null' or 'group' in obj.tags


# ── SVG ──────────────────────────────────────────────────────────────────────

def export_svg(scene, out_path, size=512):
    """Export scene as SVG. Uses camera-space BSP for correct painter ordering.

    #doc ARCHITECTURE: Mirrors tscircuit/simple-3d-svg.
    Pipeline: world coords → camera space → back-face cull → BSP sort → project 2D → render.
    Camera is at origin in camera space, simplifying BSP camera-side tests.

    #doc PROJECTION QUIRK: Orthographic projection (not perspective).
    Camera basis: fwd = normalize(lookAt - camPos), rgt = cross(worldUp, fwd),
    up = cross(rgt, fwd). Note: cross(worldUp, fwd) NOT cross(fwd, worldUp) —
    the order matters for handedness. Getting this wrong inverts left/right AND
    causes vertical flip at non-zero elevations.
    proj2d: screen_x = cam_x * scale, screen_y = cam_y * scale (NO Y-flip needed
    because the camera basis already handles orientation correctly).

    #doc BACK-FACE CULL: Uses camera-space dot product: vdot(normal, cam_vertex) >= 0
    means back-facing (normal points away from camera at origin). This is correct
    for orthographic projection. Faces with vdot < 0 are front-facing and visible.

    #doc SCREEN-AREA CULL: Projected triangles with screen area < 2.0 sq units
    are discarded as degenerate. This removes most edge faces of thin slabs
    (document pages, die colour faces) but NOT all — see KNOWN LIMITATION.

    #doc KNOWN LIMITATION: Thin slabs at oblique angles can show inner faces
    (the face pointing toward the object interior that also happens to face camera).
    This is geometrically correct but visually wrong for die/document construction
    patterns. The svg_trace pipeline (POV → vtracer) handles this correctly.
    """
    vp = scene.active_viewpoint()

    # ── Colour helpers ────────────────────────────────────────────────────────
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

    # ── Camera basis vectors ──────────────────────────────────────────────────
    # Derive camera position and look_at
    _dist = 50
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

    # ── Tessellate and transform to camera space ──────────────────────────────
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
            # Screen area cull — skip degenerate/tiny faces
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

    # ── BSP sort in camera space ──────────────────────────────────────────────
    # Camera is at origin in camera space — simplifies cameraSide check.
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

    # ── Merge coplanar adjacent triangles into quads ──────────────────────────
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

    # ── Render ───────────────────────────────────────────────────────────────
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



# ── POV-Ray ───────────────────────────────────────────────────────────────────

def export_povray(scene, out_path):
    """Export scene to POV-Ray .pov format. Spheres/cylinders stay analytical.

    #doc COORDINATE QUIRK: DM uses right-handed Y-up with camera at -Z for az=0.
    POV-Ray also uses right-handed Y-up but camera convention differs.
    Camera position is computed as:
      cx = dist * cos(el) * sin(az)
      cy = dist * sin(el)
      cz = -dist * cos(el) * cos(az)
    The negative Z on cz is intentional — az=0 means "looking from front" which
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
    # All exports must render from this exact angle — no recalculation.
    if vp.pos:
        cam_pos = f'<{vp.pos.x},{vp.pos.y},{vp.pos.z}>'
    else:
        el_r = math.radians(vp.el)
        az_r = math.radians(vp.az)
        dist = 50
        # Match SVG projection: az rotates around Y, el elevates
        # SVG proj: rx = x*cos(az) - z*sin(az), so camera is at:
        # x = dist*cos(el)*sin(az), y = dist*sin(el), z = -dist*cos(el)*cos(az)
        # (negative Z because az=0 means looking along -Z in our system)
        cx = dist * math.cos(el_r) * math.sin(az_r)
        cy = dist * math.sin(el_r)
        cz = -dist * math.cos(el_r) * math.cos(az_r)
        lx = vp.look_at.x if vp.look_at else 0
        ly = vp.look_at.y if vp.look_at else 0
        lz = vp.look_at.z if vp.look_at else 0
        cam_pos = f'<{cx+lx:.2f},{cy+ly:.2f},{cz+lz:.2f}>'
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
        '// Transparent background — render with +UA for alpha, or remove for opaque black',
        'background { color rgbt <0,0,0,1> }', '',
    ]

    # ── F6: collect merge_group tags → emit as POV union{} blocks ────────────
    from collections import defaultdict
    merge_groups = defaultdict(list)  # group_name → [obj, ...]
    for obj in scene.all_objects():
        for tag in obj.tags:
            if tag.startswith('merge_group='):
                gname = tag.split('=', 1)[1].strip()
                merge_groups[gname].append(obj)
    merge_group_ids = {obj.id for grp in merge_groups.values() for obj in grp}

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
            lines_out.append(f'  cylinder {{ <{wpx:.4f},{wpy-h/2:.4f},{wpz:.4f}>,'
                             f'<{wpx:.4f},{wpy+h/2:.4f},{wpz:.4f}>,{r}')
            lines_out.append(f'    {tx_block}')
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

    # Emit merge groups first
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

    def emit(obj, parent_M=None):
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M

        # Skip null/group — but still recurse into children
        if _skip_in_emit(obj):
            for child in obj.children: emit(child, world_M)
            return

        # Skip objects already emitted in a merge_group
        if obj.id in merge_group_ids:
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
            lines.append(f'cylinder {{ <{wpx:.4f},{wpy-h/2:.4f},{wpz:.4f}>,'
                         f'<{wpx:.4f},{wpy+h/2:.4f},{wpz:.4f}>,{r}')
            lines.append(f'  {tx_block}')
            if sc.x!=1 or sc.y!=1 or sc.z!=1:
                lines.append(f'  scale <{sc.x},{sc.y},{sc.z}>')
            lines.append('}')

        elif t == 'torus':
            R=float(p.get('outer_radius',2.0)); r=float(p.get('inner_radius',0.5))
            lines.append(f'torus {{ {R},{r}  {tx_block}')
            lines.append(f'  translate <{wpx:.4f},{wpy:.4f},{wpz:.4f}>')
            lines.append('}')

        elif t == 'plane':
            lines.append(f'plane {{ y,{wpy:.4f}  {tx_block} }}')

        else:
            # Platonic solids — tessellate to mesh2
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

    with open(out_path, 'w') as f: f.write('\n'.join(lines))
    exported = [o for o in scene.all_objects() if not _should_skip(o)]
    return f"Exported POV-Ray: {out_path} ({len(exported)} object{'s' if len(exported)!=1 else ''})."


# ── OBJ ──────────────────────────────────────────────────────────────────────

def _viewpoint_export_matrix(scene):
    """Return a Y-rotation matrix that orients the scene so DM's viewpoint
    faces the standard front direction used by OBJ/STL viewers (camera at -Z).
    Rotating by -az aligns DM's view with az=0 (standard front).
    """
    vp = scene.active_viewpoint()
    return Mat4.rotate_y(-vp.az)


def export_obj(scene, out_path):
    """Export scene as Wavefront OBJ -- compatible with Blender and most 3D tools.
    Geometry is pre-rotated so DM's viewpoint faces the standard OBJ front view.
    """
    lines_v = [f'# DwarvenModeller OBJ  {_now()[:19]}', '']
    lines_f = []; offset = 1
    orient_M = _viewpoint_export_matrix(scene)

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
                        rv = orient_M * Vec3(v[0], v[1], v[2])
                        lines_v.append(f'v {rv.x:.6f} {rv.y:.6f} {rv.z:.6f}')
                for i in range(len(tris)):
                    a = offset+i*3; lines_f.append(f'f {a} {a+1} {a+2}')
                offset += len(tris)*3
                lines_v.append('')
        for child in obj.children:
            collect(child, world_M)

    for obj in scene.objects:
        collect(obj)

    with open(out_path, 'w') as f: f.write('\n'.join(lines_v + lines_f))
    return f"Exported OBJ: {out_path}."


# ── STL ──────────────────────────────────────────────────────────────────────

def export_stl(scene, out_path, subdivisions=3):
    """Export scene as binary STL -- universal 3D printing format (Z-up).
    Geometry is pre-rotated so DM's viewpoint faces the standard STL/slicer front.
    """
    pairs = tessellate_scene(scene, subdivisions)
    tris  = [tri for tris,_ in pairs for tri in tris]
    orient_M = _viewpoint_export_matrix(scene)

    def normal(tri):
        a,b,c = [Vec3(*v) for v in tri]
        ab=b-a; ac=c-a
        n=Vec3(ab.y*ac.z-ab.z*ac.y, ab.z*ac.x-ab.x*ac.z, ab.x*ac.y-ab.y*ac.x)
        l=n.length()
        return (n.x/l, n.y/l, n.z/l) if l>1e-10 else (0,0,1)

    def orient(v):
        rv = orient_M * Vec3(v[0], v[1], v[2])
        return (rv.x, rv.y, rv.z)

    # Convert Y-up Z-forward to Z-up Y-forward (slicer convention)
    def stl_v(v): return (v[0], -v[2], v[1])
    def stl_n(n): return (n[0], -n[2], n[1])

    header = (b'DwarvenModeller STL export' + b'\x00'*54)[:80]
    buf    = [header, struct.pack('<I', len(tris))]
    for tri in tris:
        otri = tuple(orient(v) for v in tri)
        nx,ny,nz = normal(otri)
        cnx,cny,cnz = stl_n((nx,ny,nz))
        buf.append(struct.pack('<fff', cnx,cny,cnz))
        for v in otri: buf.append(struct.pack('<fff', *stl_v(v)))
        buf.append(struct.pack('<H', 0))
    with open(out_path, 'wb') as f:
        for b in buf: f.write(b)
    return f"Exported STL: {out_path} ({len(tris)} triangles)."


# ── X3D ──────────────────────────────────────────────────────────────────────

def export_x3d(scene, out_path):
    """Export scene as X3D — browser-viewable 3D, analytical primitives preserved."""
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


# ── glTF ─────────────────────────────────────────────────────────────────────

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
        for v in verts: pos_bytes+=struct.pack('<fff',v[0],v[1],v[2])
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

    # ── Camera node ───────────────────────────────────────────────────────────
    # Convert DM viewpoint (az/el) to glTF camera position.
    # DM: Y-up, Z-toward-viewer at az=0. glTF: Y-up, Z-backward.
    # So glTF cam_z = -DM cam_z.
    dist = 50
    if vp.pos:
        lx = vp.look_at.x if vp.look_at else 0
        ly = vp.look_at.y if vp.look_at else 0
        lz = vp.look_at.z if vp.look_at else 0
        ox = vp.pos.x - lx; oy = vp.pos.y - ly; oz = vp.pos.z - lz
        d = math.sqrt(ox*ox+oy*oy+oz*oz)
        if d > 1e-10:
            el_r = math.asin(max(-1.0, min(1.0, oy/d)))
            az_r = math.atan2(ox, -oz)
        else:
            el_r = math.radians(vp.el); az_r = math.radians(vp.az)
        cx = vp.pos.x; cy = vp.pos.y; cz = vp.pos.z
    else:
        el_r = math.radians(vp.el); az_r = math.radians(vp.az)
        cx =  dist * math.cos(el_r) * math.sin(az_r)
        cy =  dist * math.sin(el_r)
        cz = -dist * math.cos(el_r) * math.cos(az_r)
        lx = vp.look_at.x if vp.look_at else 0
        ly = vp.look_at.y if vp.look_at else 0
        lz = vp.look_at.z if vp.look_at else 0
        cx += lx; cy += ly; cz += lz

    # Build look-at rotation matrix → quaternion for glTF
    # Camera looks from (cx,cy,cz) toward (lx,ly,lz), Y-up
    def _normalize(v):
        m = math.sqrt(sum(x*x for x in v))
        return tuple(x/m for x in v) if m > 1e-10 else (0,0,1)
    def _cross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    def _dot(a,b): return sum(x*y for x,y in zip(a,b))

    fwd = _normalize((lx-cx, ly-cy, lz-cz))
    # In glTF camera space, camera looks along -Z
    cam_z = (-fwd[0], -fwd[1], -fwd[2])  # -forward = glTF -Z axis
    world_up = (0, 1, 0)
    cam_x = _normalize(_cross(world_up, cam_z))
    if _dot(cam_x, cam_x) < 1e-10:
        cam_x = (1, 0, 0)
    cam_y = _cross(cam_z, cam_x)

    # Rotation matrix to quaternion (column vectors = camera axes)
    m = [[cam_x[0], cam_y[0], cam_z[0]],
         [cam_x[1], cam_y[1], cam_z[1]],
         [cam_x[2], cam_y[2], cam_z[2]]]
    trace = m[0][0]+m[1][1]+m[2][2]
    if trace > 0:
        s = 0.5/math.sqrt(trace+1)
        qw = 0.25/s
        qx = (m[2][1]-m[1][2])*s
        qy = (m[0][2]-m[2][0])*s
        qz = (m[1][0]-m[0][1])*s
    elif m[0][0]>m[1][1] and m[0][0]>m[2][2]:
        s = 2*math.sqrt(1+m[0][0]-m[1][1]-m[2][2])
        qw = (m[2][1]-m[1][2])/s; qx = 0.25*s
        qy = (m[0][1]+m[1][0])/s; qz = (m[0][2]+m[2][0])/s
    elif m[1][1]>m[2][2]:
        s = 2*math.sqrt(1+m[1][1]-m[0][0]-m[2][2])
        qw = (m[0][2]-m[2][0])/s; qx = (m[0][1]+m[1][0])/s
        qy = 0.25*s; qz = (m[1][2]+m[2][1])/s
    else:
        s = 2*math.sqrt(1+m[2][2]-m[0][0]-m[1][1])
        qw = (m[1][0]-m[0][1])/s; qx = (m[0][2]+m[2][0])/s
        qy = (m[1][2]+m[2][1])/s; qz = 0.25*s

    gltf['cameras'].append({'type':'perspective',
                             'perspective':{'yfov':0.785,'aspectRatio':1.0,
                                            'znear':0.1,'zfar':1000.0}})
    cam_node_idx = len(gltf['nodes'])
    gltf['nodes'].append({
        'name': 'DwarvenCamera',
        'camera': 0,
        'translation': [round(cx,4), round(cy,4), round(cz,4)],
        'rotation': [round(qx,6), round(qy,6), round(qz,6), round(qw,6)],
    })
    # Fix scene nodes list (replace placeholder -2 with actual index)
    gltf['scenes'][0]['nodes'] = [i for i in gltf['scenes'][0]['nodes'] if i != -2] + [cam_node_idx]

    b64=base64.b64encode(bytes(bin_data)).decode('ascii')
    gltf['buffers']=[{'byteLength':len(bin_data),
                      'uri':f'data:application/octet-stream;base64,{b64}'}]
    with open(out_path,'w',encoding='utf-8') as f: _json.dump(gltf,f,indent=2)
    n=len([p for p in pairs if p[0]])
    return f"Exported glTF: {out_path} ({n} meshes, {sum(len(t) for t,_ in pairs)} triangles)."


# ── CSS 3D ───────────────────────────────────────────────────────────────────

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
        f'<title>{os.path.basename(out_path)} — DwarvenModeller CSS 3D</title>',
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


# ── Spatial text (Braille / screen reader) ───────────────────────────────────

def export_spatial_text(scene, out_path):
    """
    Export a structured prose spatial description.
    No visual output — designed for screen readers, Braille displays, JAWS, NVDA.
    Pipe to any text-to-speech system or Braille terminal.
    """
    all_objs = scene.all_objects()
    lines    = [
        'DWARVEN MODELLER — SPATIAL SCENE DESCRIPTION',
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
    }
    lines += ['OBJECTS', '-'*30, '']

    def describe(obj, depth=0, parent_M=None):
        local_M = obj.transform.matrix()
        world_M = (parent_M * local_M) if parent_M else local_M
        wp  = world_M * Vec3(0,0,0)
        sc  = obj.transform.scale
        r   = obj.get_param('radius', obj.get_param('width', 1.0))
        eff_r = r * max(sc.x,sc.y,sc.z)
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
            lines.append(f'{ind}  Rotated: x={rot.x:.1f}° y={rot.y:.1f}° z={rot.z:.1f}°.')
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


# ── SVG via POV-Ray (opt 4) ───────────────────────────────────────────────────

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

        # Step 2: vtracer — PNG → vector SVG paths
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


def export_png(scene, out_path, size=512):
    """Export scene as PNG by rendering via POV-Ray.
    Pixel-perfect, correct for ALL geometry. Honest raster output.
    """
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
        return f"Exported PNG: {out_path} ({size}×{size}px, {kb}KB)."

    finally:
        try: os.unlink(pov_path)
        except: pass


# ── Export dispatcher ─────────────────────────────────────────────────────────

EXPORT_FORMATS = {
    'povray': export_povray, 'pov': export_povray,
    'svg':        export_svg_trace,    # true vector SVG: POV render → vtracer → paths
    'svg_trace':  export_svg_trace,    # explicit alias
    'svg_pov':    export_svg_povray,   # raster-in-SVG (faster, not scalable)
    'svg+pov':    export_svg_povray,   # alias
    'svgpov':     export_svg_povray,   # alias
    'svg_vector': export_svg,          # pure geometric vector (simple scenes only)
    'png':        export_png,          # straight PNG via POV — honest raster
    'obj':    export_obj,
    'stl':    export_stl,
    'x3d':    export_x3d,
    'gltf':   export_gltf,  'glb': export_gltf,
    'css':    export_css3d, 'css3d': export_css3d, 'html': export_css3d,
    'txt':    export_spatial_text, 'text': export_spatial_text,
    'braille':export_spatial_text, 'spatial': export_spatial_text,
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
    """Print detailed help for all operations — screen-reader friendly."""
    print('DwarvenModeller — Operation Reference')
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
        description='DwarvenModeller — headless stateless 3D modeller',
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
                        help='Run a file of operations, one per line')
    parser.add_argument('--no-save',        action='store_true',
                        help='Do not save after operation')
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

    result = None

    def run_op(op_str):
        verb, kwargs = parse_op(op_str)
        handler = OPERATIONS.get(verb)
        if not handler:
            close = difflib.get_close_matches(verb, OPERATIONS.keys(), n=1, cutoff=0.5)
            msg = f"Unknown operation '{verb}'."
            if close: msg += f" Did you mean '{close[0]}'?"
            msg += f" Valid: {', '.join(sorted(set(OPERATIONS.keys())))}."
            raise ValueError(msg)
        r = handler(scene, kwargs)
        scene.history.append(HistoryEntry(op_str))
        return r

    if args.op:
        try:
            result = run_op(args.op)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr); return 1

    if args.batch:
        if not os.path.exists(args.batch):
            print(f"Error: batch file '{args.batch}' not found.", file=sys.stderr); return 1
        with open(args.batch) as f:
            ops = [l.strip() for l in f if l.strip() and not l.strip().startswith('#')]
        errors = 0
        for i, op_str in enumerate(ops, 1):
            try:
                r = run_op(op_str); print(f"[{i}/{len(ops)}] {r}")
            except ValueError as e:
                print(f"[{i}/{len(ops)}] Error: {e}", file=sys.stderr); errors += 1
        if errors: print(f"\n{errors} error{'s' if errors!=1 else ''} in batch.", file=sys.stderr)
        result = f"Batch complete: {len(ops)-errors}/{len(ops)} operations succeeded."

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
        out  = ekwargs.get('out', args.file.replace('.dms', f'.{fmt}'))
        size = int(ekwargs.get('size', 512))
        subs = int(ekwargs['subdivisions']) if 'subdivisions' in ekwargs else None  # F3
        try:
            result = run_export(scene, fmt, out, size, subdivisions=subs)
        except (ValueError, Exception) as e:
            print(f"Export error: {e}", file=sys.stderr); return 1

    if args.feedback is not None:
        tty = sys.stdout.isatty()
        fb_target = None
        fb_az = fb_el = None
        if args.feedback:
            _, fkw = parse_op('feedback ' + args.feedback)
            fb_target = fkw.get('target') or fkw.get('id')
            if 'az' in fkw: fb_az = float(fkw['az'])   # F4: viewpoint override
            if 'el' in fkw: fb_el = float(fkw['el'])   # F4: viewpoint override
        # F4: temporarily override viewpoint for feedback only (no file write)
        if fb_az is not None or fb_el is not None:
            vp = scene.active_viewpoint()
            orig_az, orig_el = vp.az, vp.el
            if fb_az is not None: vp.az = fb_az
            if fb_el is not None: vp.el = fb_el
            print(generate_feedback(scene, tty=tty, target_id=fb_target))
            vp.az, vp.el = orig_az, orig_el  # restore — no save needed
        else:
            print(generate_feedback(scene, tty=tty, target_id=fb_target))

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

"""DwarvenModeller -- scene graph: Scene, Object, Viewpoint, Transform."""
from __future__ import annotations
import math, datetime, copy
import xml.etree.ElementTree as ET
from xml.dom import minidom
from .constants import *
from .math_utils import *
# ═════════════════════════════════════════════════════════════════════════════



__all__ = ['Transform', 'Material', 'SceneObject', 'Viewpoint', 'HistoryEntry', 'Scene']

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

    def __init__(self, name='default', az=180.0, el=25.0, scale=1.0,
                 pos=None, look_at=None):
        self.name    = name
        self.az      = az       # azimuth degrees
        self.el      = el       # elevation degrees
        self.roll    = 0.0      # roll degrees (rotation around axis pointing at you)
        self.scale   = scale    # projection scale
        self.pos     = pos      # explicit camera Vec3 (overrides az/el in POV-Ray)
        self.look_at = look_at  # explicit look-at Vec3

    def to_xml(self, parent):
        vp = ET.SubElement(parent, 'viewpoint')
        vp.set('name',  self.name)
        vp.set('az',    str(self.az))
        vp.set('el',    str(self.el))
        if self.roll:   vp.set('roll',  str(self.roll))
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
        if elem.get('roll'):    vp.roll    = float(elem.get('roll'))
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

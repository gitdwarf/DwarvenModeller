"""DwarvenModeller -- maths helpers (Vec3, Mat3, transforms)."""
from __future__ import annotations
import math, datetime
from .constants import *
# ═════════════════════════════════════════════════════════════════════════════



__all__ = ['Vec3', 'Mat4', '_now', '_COLOUR_NAMES', '_hex_to_rgb', '_dist', '_direction_name', '_size_description', '_format_pos', '_approximate_colour_name', '_should_skip']

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


_COLOUR_NAMES = {
    'red':'#ff0000','green':'#00ff00','blue':'#0000ff','cyan':'#00ffff',
    'magenta':'#ff00ff','yellow':'#ffff00','white':'#ffffff','black':'#000000',
    'orange':'#ff8000','purple':'#800080','brown':'#8b4513','grey':'#888888',
    'gray':'#888888','pink':'#ffc0cb','lime':'#32cd32','navy':'#000080',
    'teal':'#008080','maroon':'#800000','olive':'#808000','silver':'#c0c0c0',
    'gold':'#ffd700','beige':'#f5f5dc','ivory':'#fffff0','coral':'#ff7f50',
    'indigo':'#4b0082','violet':'#ee82ee','salmon':'#fa8072','tan':'#d2b48c',
}

def _hex_to_rgb(h):
    """Parse '#rrggbb', '#rgb', or colour name to (r, g, b) tuple."""
    if h and h[0] != '#':
        h = _COLOUR_NAMES.get(h.lower().strip(), h)
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

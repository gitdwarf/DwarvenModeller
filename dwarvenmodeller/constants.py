"""DwarvenModeller -- constants, primitive definitions, colour names."""
from __future__ import annotations
import math, datetime, os, sys, struct, base64, json as _json
import difflib, argparse, copy
import xml.etree.ElementTree as ET
from xml.dom import minidom

# PITCH_INVERSION: 1 = intuitive (DM default), 0 = standard CAD convention
__all__ = ['PITCH_INVERSION', 'PRIMITIVES', 'PARAM_DEFAULTS']

PITCH_INVERSION = 1

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

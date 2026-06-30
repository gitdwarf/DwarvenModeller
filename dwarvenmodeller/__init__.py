"""DwarvenModeller -- headless stateless 3D clay modeller.

Text-first. No GUI. No viewport. No mouse required.
Digital clay, not CAD.
"""
from .constants import *
from .math_utils import *
from .scene import *
from .primitives import *
from .ops import *
from .feedback import *
from .exporters import *

__version__ = '0.3.5'
__author__  = 'DwarvenForge'

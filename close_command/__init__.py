"""
Close Command — Intercompany Financial Close Automation System.
"""

import os
import sys

# Ensure internal bare imports (from data.*, from models.*, etc.) work by
# placing the close_command package directory on sys.path.
_pkg_dir = os.path.dirname(os.path.abspath(__file__))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

__version__ = "1.0.0"
__all__ = []

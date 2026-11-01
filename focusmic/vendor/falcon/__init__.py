"""Vendored Falcon inference code (Apache-2.0).

Falcon's runtime imports its model package as top-level ``falcon_model``; keep
this directory on sys.path so the vendored copy works both in-tree and in a
packaged build.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

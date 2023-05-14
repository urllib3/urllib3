"""
This is meant to support various HTTP version.

    - (standard) http.client shipped within cpython distribution
    - (experimental) hface shipped by installing urllib3-ext-hface
"""

from __future__ import annotations

from ._base import BaseBackend, HttpVersion, QuicPreemptiveCacheType
from .hface import HfaceBackend
from .httplib import LegacyBackend

__all__ = (
    "BaseBackend",
    "LegacyBackend",
    "HfaceBackend",
    "HttpVersion",
    "QuicPreemptiveCacheType",
)

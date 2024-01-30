from __future__ import annotations

from .connection import extract_from_urllib3, inject_into_urllib3

__all__ = [
    "inject_into_urllib3",
    "extract_from_urllib3",
]

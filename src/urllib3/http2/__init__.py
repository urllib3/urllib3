from __future__ import annotations

from importlib.metadata import version

__all__ = [
    "inject_into_urllib3",
    "extract_from_urllib3",
]


def inject_into_urllib3() -> None:
    # First check if h2 version is valid
    h2_version = version("h2")
    if not h2_version.startswith("4."):
        raise ImportError(
            "urllib3 v2 supports h2 version 4.x.x, currently "
            f"the 'h2' module is compiled with {h2_version!r}. "
            "See: https://github.com/urllib3/urllib3/issues/3290"
        )


def extract_from_urllib3() -> None:
    pass

from __future__ import annotations

import typing

_TYPE_HEADER_KEY = typing.Union[str, bytes]
_TYPE_HEADER_VALUE = typing.Union[str, bytes]
_TYPE_HEADERS = typing.Union[
    typing.Mapping[str, _TYPE_HEADER_VALUE],
    typing.Mapping[bytes, _TYPE_HEADER_VALUE],
    typing.Mapping[_TYPE_HEADER_KEY, _TYPE_HEADER_VALUE],
]

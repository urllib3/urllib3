from __future__ import annotations

from dataclasses import dataclass, field

from ..._base_connection import _TYPE_BODY
from ..._collections import _TYPE_HTTP_HEADER_KEY, _TYPE_HTTP_HEADER_VALUE


@dataclass
class EmscriptenRequest:
    method: str
    url: str
    params: dict[str, str] | None = None
    body: _TYPE_BODY | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 0
    decode_content: bool = True

    def set_header(
        self, name: _TYPE_HTTP_HEADER_KEY, value: _TYPE_HTTP_HEADER_VALUE
    ) -> None:
        if isinstance(name, bytes):
            name = name.decode("latin-1")
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        self.headers[name.capitalize()] = value

    def set_body(self, body: _TYPE_BODY | None) -> None:
        self.body = body

from __future__ import annotations

from dataclasses import dataclass, field

from ..._base_connection import _TYPE_BODY


@dataclass
class EmscriptenRequest:
    method: str
    url: str
    params: dict[str, str] | None = None
    body: _TYPE_BODY | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 0
    decode_content: bool = True

    def set_header(self, name: str, value: str | bytes) -> None:
        # Fetch and XMLHttpRequest accept Web IDL ByteStrings, represented by
        # JavaScript strings with code points in the range 0-255.
        if isinstance(value, bytes):
            value = value.decode("latin-1")
        self.headers[name.capitalize()] = value

    def set_body(self, body: _TYPE_BODY | None) -> None:
        self.body = body

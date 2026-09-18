from __future__ import annotations

import io
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

    def set_header(self, name: str, value: str) -> None:
        # Fetch calculates Content-Length and browsers forbid setting it directly.
        if name.lower() == "content-length":
            return
        self.headers[name.capitalize()] = value

    def set_body(self, body: _TYPE_BODY | None) -> None:
        if body is not None and hasattr(body, "read"):
            buffered = io.BytesIO()
            while True:
                chunk = body.read(16384)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                else:
                    chunk = bytes(chunk)
                buffered.write(chunk)
            self.body = buffered.getvalue()
            return
        self.body = body

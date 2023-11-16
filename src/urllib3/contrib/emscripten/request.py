from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..._base_connection import _TYPE_BODY


@dataclass
class EmscriptenRequest:
    method: str
    url: str
    params: dict[str, str] | None = None
    body: _TYPE_BODY | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 0

    def set_header(self, name: str, value: str) -> None:
        self.headers[name.capitalize()] = value

    def set_body(self, body: _TYPE_BODY | None) -> None:
        self.body = body

    def set_json(self, body: dict[str, Any]) -> None:
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.set_body(json.dumps(body).encode("utf-8"))

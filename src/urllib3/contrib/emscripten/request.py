from dataclasses import dataclass, field
from typing import Dict


@dataclass
class EmscriptenRequest:
    method: str
    url: str
    params: dict[str, str] | None = None
    body: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: int = 0

    def set_header(self, name: str, value: str):
        self.headers[name.capitalize()] = value

    def set_body(self, body: bytes):
        self.body = body

    def set_json(self, body: dict):
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.set_body(json.dumps(body).encode("utf-8"))

from __future__ import annotations

import typing
from dataclasses import dataclass, field


@dataclass
class WasiRequest:
    method: str
    url: str
    scheme: str
    host: str
    port: int
    params: dict[str, str] | None = None
    body: typing.Iterable[bytes] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float | None = None
    decode_content: bool = True
    preload_content: bool = False

    def set_header(self, name: str, value: str) -> None:
        self.headers[name.capitalize()] = value

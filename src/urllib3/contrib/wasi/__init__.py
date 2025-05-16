from __future__ import annotations

import urllib3.connection

from ...connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from .connection import WasiHTTPConnection, WasiHTTPSConnection


def inject_into_urllib3() -> None:
    HTTPConnectionPool.ConnectionCls = WasiHTTPConnection
    HTTPSConnectionPool.ConnectionCls = WasiHTTPSConnection
    urllib3.connection.HTTPConnection = WasiHTTPConnection  # type: ignore[misc,assignment]
    urllib3.connection.HTTPSConnection = WasiHTTPSConnection  # type: ignore[misc,assignment]
    urllib3.connectionpool.HTTPConnection = WasiHTTPConnection  # type: ignore[attr-defined,assignment]
    urllib3.connectionpool.HTTPSConnection = WasiHTTPSConnection  # type: ignore[attr-defined,assignment]

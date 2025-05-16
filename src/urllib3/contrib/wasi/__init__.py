from __future__ import annotations

import urllib3.connection

from ...connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from .connection import WasiHTTPConnection, WasiHTTPSConnection


def inject_into_urllib3() -> None:
    HTTPConnectionPool.ConnectionCls = WasiHTTPConnection
    HTTPSConnectionPool.ConnectionCls = WasiHTTPSConnection
    urllib3.connection.HTTPConnection = WasiHTTPConnection
    urllib3.connection.HTTPSConnection = WasiHTTPSConnection
    urllib3.connectionpool.HTTPConnection = WasiHTTPConnection
    urllib3.connectionpool.HTTPSConnection = WasiHTTPSConnection

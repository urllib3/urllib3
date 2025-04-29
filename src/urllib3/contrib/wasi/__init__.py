from __future__ import annotations

import functools

import urllib3.connection
import urllib3.connectionpool

from ...connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from .connection import WasiHTTPConnection, WasiHTTPSConnection
from .wasi import preload


def enable_wasi_backend(world_name: str) -> None:
    # componentize-py requires all imports to be loaded when the interpreter is preloaded.
    # Not preloading here would fail at runtime as we are dynamically loading based on the world name when sending requests.
    preload(world_name)

    http_cls = partialclass(WasiHTTPConnection, world_name=world_name)  # type: ignore[no-untyped-call]
    https_cls = partialclass(WasiHTTPSConnection, world_name=world_name)  # type: ignore[no-untyped-call]

    HTTPConnectionPool.ConnectionCls = http_cls
    HTTPSConnectionPool.ConnectionCls = https_cls
    urllib3.connection.HTTPConnection = http_cls  # type: ignore[misc]
    urllib3.connection.HTTPSConnection = https_cls  # type: ignore[misc]
    urllib3.connectionpool.HTTPConnection = http_cls  # type: ignore[attr-defined]
    urllib3.connectionpool.HTTPSConnection = https_cls  # type: ignore[attr-defined]


def partialclass(cls, *args, **kwds):  # type: ignore[no-untyped-def]
    class NewCls(cls):  # type: ignore[misc,valid-type]
        __init__ = functools.partialmethod(cls.__init__, *args, **kwds)  # type: ignore[assignment]

    return NewCls

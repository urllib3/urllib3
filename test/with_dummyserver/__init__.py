from __future__ import annotations

import typing

from urllib3 import HTTPConnectionPool, PoolManager
from urllib3.response import BaseHTTPResponse

PoolFactory = typing.Callable[..., HTTPConnectionPool]
PoolManagerFactory = typing.Callable[..., PoolManager]
RequestFunction = typing.Callable[..., BaseHTTPResponse]

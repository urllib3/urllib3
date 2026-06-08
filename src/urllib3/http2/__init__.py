from __future__ import annotations

from importlib.metadata import version

__all__ = [
    "inject_into_urllib3",
    "extract_from_urllib3",
]

import typing

orig_HTTPSConnection: typing.Any = None
orig_HTTPConnection: typing.Any = None


def inject_into_urllib3(
    *, h2c: bool | typing.Literal["prior_knowledge", "upgrade"] = False
) -> None:
    # First check if h2 version is valid
    h2_version = version("h2")
    if not h2_version.startswith("4."):
        raise ImportError(
            "urllib3 v2 supports h2 version 4.x.x, currently "
            f"the 'h2' module is compiled with {h2_version!r}. "
            "See: https://github.com/urllib3/urllib3/issues/3290"
        )

    # Import here to avoid circular dependencies.
    from .. import connection as urllib3_connection
    from .. import util as urllib3_util
    from ..connectionpool import HTTPConnectionPool, HTTPSConnectionPool
    from ..util import ssl_ as urllib3_util_ssl
    from .connection import (
        HTTP2CleartextConnection,
        HTTP2Connection,
        HTTP2UpgradeConnection,
    )

    global orig_HTTPConnection, orig_HTTPSConnection
    if orig_HTTPSConnection is None:
        orig_HTTPSConnection = urllib3_connection.HTTPSConnection
    if orig_HTTPConnection is None:
        orig_HTTPConnection = urllib3_connection.HTTPConnection

    if h2c is True or h2c == "prior_knowledge":
        http_connection_cls = HTTP2CleartextConnection
    elif h2c == "upgrade":
        http_connection_cls = HTTP2UpgradeConnection
    elif h2c is False:
        http_connection_cls = orig_HTTPConnection
    else:
        raise ValueError("h2c must be True, 'prior_knowledge', 'upgrade', or False")

    HTTPSConnectionPool.ConnectionCls = HTTP2Connection
    urllib3_connection.HTTPSConnection = HTTP2Connection  # type: ignore[misc]
    HTTPConnectionPool.ConnectionCls = http_connection_cls
    urllib3_connection.HTTPConnection = http_connection_cls  # type: ignore[misc]

    # TODO: Offer 'http/1.1' as well, but for testing purposes this is handy.
    urllib3_util.ALPN_PROTOCOLS = ["h2"]
    urllib3_util_ssl.ALPN_PROTOCOLS = ["h2"]


def extract_from_urllib3() -> None:
    from .. import connection as urllib3_connection
    from .. import util as urllib3_util
    from ..connectionpool import HTTPConnectionPool, HTTPSConnectionPool
    from ..util import ssl_ as urllib3_util_ssl

    global orig_HTTPConnection, orig_HTTPSConnection
    if orig_HTTPSConnection is not None:
        HTTPSConnectionPool.ConnectionCls = orig_HTTPSConnection
        urllib3_connection.HTTPSConnection = orig_HTTPSConnection  # type: ignore[misc]
        orig_HTTPSConnection = None
    if orig_HTTPConnection is not None:
        HTTPConnectionPool.ConnectionCls = orig_HTTPConnection
        urllib3_connection.HTTPConnection = orig_HTTPConnection  # type: ignore[misc]
        orig_HTTPConnection = None

    urllib3_util.ALPN_PROTOCOLS = ["http/1.1"]
    urllib3_util_ssl.ALPN_PROTOCOLS = ["http/1.1"]

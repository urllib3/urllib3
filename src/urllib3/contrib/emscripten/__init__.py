"""
The urllib3.contrib.emscripten submodule contains support for using urllib3 within an Emscripten webassembly environment.

Currently this supports Pyodide (https://www.pyodide.org) in web-browser environments only. Node.js is not supported yet. It should
also work in jupyterlite (https://jupyterlite.readthedocs.io/)

With one exception below, you shouldn't need to call most of the classes in this module directly as they are patched in when you import urllib3 in emscripten.

"""



from __future__ import annotations

import urllib3.connection

from ...connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from .connection import EmscriptenHTTPConnection, EmscriptenHTTPSConnection


def inject_into_urllib3() -> None:
    """ 
    Override connection classes to use emscripten specific classes. This is automatically called on import, so
    you shouldn't need to use it.
    """
    # n.b. mypy complains about the overriding of classes below
    # if it isn't ignored
    HTTPConnectionPool.ConnectionCls = EmscriptenHTTPConnection
    HTTPSConnectionPool.ConnectionCls = EmscriptenHTTPSConnection
    urllib3.connection.HTTPConnection = EmscriptenHTTPConnection  # type: ignore[misc,assignment]
    urllib3.connection.HTTPSConnection = EmscriptenHTTPSConnection  # type: ignore[misc,assignment]

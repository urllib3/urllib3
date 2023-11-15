from .connection import EmscriptenHTTPConnection, EmscriptenHTTPSConnection
from ...connectionpool import HTTPConnectionPool, HTTPSConnectionPool

HTTPConnectionPool.ConnectionCls = EmscriptenHTTPConnection
HTTPSConnectionPool.ConnectionCls = EmscriptenHTTPSConnection

import urllib3.connection

urllib3.connection.HTTPConnection = EmscriptenHTTPConnection
urllib3.connection.HTTPSConnection = EmscriptenHTTPSConnection

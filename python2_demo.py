from __future__ import print_function

import urllib3
from urllib3._backends import SyncBackend

URL = "http://httpbin.org/uuid"

print("--- urllib3 using synchronous sockets in Python 2 ---")
with urllib3.PoolManager(backend=SyncBackend()) as http:
    print("URL:", URL)
    r = http.request("GET", URL, preload_content=False)
    print("Status:", r.status)
    print("Data: {!r}".format(r.data))

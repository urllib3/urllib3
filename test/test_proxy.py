#!/usr/bin/env python

__author__      = "Cal Leeming"
__maintainer__  = "Cal Leeming"
__credits__     = ["Cal Leeming", ]
__email__       = "cal.leeming@simplicitymedialtd.co.uk"


def fix_import_path():
    import os
    import sys
    CURRENT_DIR = os.path.realpath(os.path.dirname(__file__))
    IMPORT_PATH = "%s/../" % ( CURRENT_DIR, )
    sys.path.append(IMPORT_PATH)

fix_import_path()
import urllib3
import sys
import os

proxys = [
    "http://192.168.56.1:8888",
    "socks4://192.168.56.1:8889",
    "socks5://192.168.56.1:8889"
]
for x in proxys:
    print "TEST Proxy: %s" % ( x, )
    pool = urllib3.PoolManager(proxy_url = x)
    req = pool.request('GET', 'https://www.google.co.uk/')
    assert req.data.count("google_favicon_128.png"), "string detect failed"
    print "HTTPS OK"

    req = pool.request('GET', 'http://www.google.co.uk/')
    assert req.data.count("google_favicon_128.png"), "string detect failed"
    print "HTTP OK"

    print "---"

print "TEST: No proxy via PoolManager"
pool = urllib3.PoolManager()
req = pool.request('GET', 'https://www.google.co.uk/')
assert req.data.count("google_favicon_128.png"), "string detect failed"
print "HTTPS OK"

req = pool.request('GET', 'http://www.google.co.uk/')
assert req.data.count("google_favicon_128.png"), "string detect failed"
print "HTTP OK"

print "---"

print "TEST: No proxy via connection_from_url"
_rq = urllib3.connection_from_url('https://www.google.co.uk/')
req = _rq.request("GET", "/")
assert req.data.count("google_favicon_128.png"), "string detect failed"
print "HTTPS OK"

_rq = urllib3.connection_from_url('http://www.google.co.uk/')
req = _rq.request("GET", "/")
assert req.data.count("google_favicon_128.png"), "string detect failed"
print "HTTP OK"
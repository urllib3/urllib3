#!/usr/bin/env python

"""
Really simple rudimentary benchmark to compare ConnectionPool versus standard
urllib to demonstrate the usefulness of connection re-using.
"""

import sys
import time
import urllib.request

sys.path.append("../src")
import urllib3  # noqa: E402

# URLs to download. Doesn't matter as long as they're from the same host, so we
# can take advantage of connection re-using.
TO_DOWNLOAD = [
    "http://code.google.com/apis/apps/",
    "http://code.google.com/apis/base/",
    "http://code.google.com/apis/blogger/",
    "http://code.google.com/apis/calendar/",
    "http://code.google.com/apis/codesearch/",
    "http://code.google.com/apis/books/",
    "http://code.google.com/apis/documents/",
    "http://code.google.com/apis/finance/",
    "http://code.google.com/apis/health/",
    "http://code.google.com/apis/notebook/",
    "http://code.google.com/apis/picasaweb/",
    "http://code.google.com/apis/spreadsheets/",
    "http://code.google.com/apis/webmastertools/",
    "http://code.google.com/apis/youtube/",
]


def urllib_get(url_list):
    assert url_list
    for url in url_list:
        now = time.time()
        urllib.request.urlopen(url)
        elapsed = time.time() - now
        print(f"Got in {elapsed:0.3f}: {url}")


def pool_get(url_list):
    assert url_list
    pool = urllib3.PoolManager()
    for url in url_list:
        now = time.time()
        pool.request("GET", url, assert_same_host=False)
        elapsed = time.time() - now
        print(f"Got in {elapsed:0.3f}s: {url}")


if __name__ == "__main__":
    print("Running pool_get ...")
    now = time.time()
    pool_get(TO_DOWNLOAD)
    pool_elapsed = time.time() - now

    print("Running urllib_get ...")
    now = time.time()
    urllib_get(TO_DOWNLOAD)
    urllib_elapsed = time.time() - now

    print(f"Completed pool_get in {pool_elapsed:0.3f}s")
    print(f"Completed urllib_get in {urllib_elapsed:0.3f}s")


"""
Example results:

Completed pool_get in 1.163s
Completed urllib_get in 2.318s
"""

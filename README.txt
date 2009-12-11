Highlights
==========

 * Re-use the same socket connection for multiple requests
   (``HTTPConnectionPool`` and ``HTTPSConnectionPool``)
 * File posting (``encode_multipart_formdata``)
 * Built-in redirection and retries (optional)
 * Thread-safe

What's wrong with urllib and urllib2?
=====================================

There are two critical features missing from the Python standard library:
Connection re-using/pooling and file posting. It's not terribly hard to 
implement these yourself, but it's much easier to use a module that already
did the work for you.

The Python standard libraries ``urllib`` and ``urllib2`` have little to do
with each other. They were designed to be independent and standalone, each
solving a different scope of problems, and ``urllib3`` follows in a similar
vein.

Why do I want to reuse connections?
===================================

Performance. When you normally do a urllib call, a separate socket
connection is created with each request. By reusing existing sockets
(supported since HTTP 1.1), the requests will take up less resources on the
server's end, and also provide a faster response time at the client's end.
With some simple benchmarks (see `test/benchmark.py 
<http://code.google.com/p/urllib3/source/browse/trunk/test/benchmark.py>`_
), downloading 15 URLs from google.com is about twice as fast when using
HTTPConnectionPool (which uses 1 connection) than using plain urllib (which
uses 15 connections).

This library is perfect for:

 * Talking to an API
 * Crawling a website
 * Any situation where being able to post files, handle redirection, and
   retrying is useful. It's relatively lightweight, so it can be used for
   anything!

Examples
========

Go to the `Examples wiki <http://code.google.com/p/urllib3/wiki/Examples>`_
for more nice syntax-highlighted examples.

But, long story short::

  import urllib3

  API_URL = 'http://ajax.googleapis.com/ajax/services/search/web'
  
  http_pool = urllib3.connection_from_url(API_URL)
  
  fields = {'v': '1.0', 'q': 'urllib3'}
  r = http_pool.get_url(API_URL, fields)
  
  print r.status, r.data


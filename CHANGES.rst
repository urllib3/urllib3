Changes
=======

dev (master)
++++++++++++

* Improved url parsing in ``urllib3.util.parse_url`` (properly parse '@' in
  username, and blank ports like 'hostname:').

* New ``urllib3.connection`` module which contains all the HTTPConnection
  objects.

* Several ``urllib3.util.Timeout``-related fixes. Also changed constructor
  signature to a more sensible order. [Backwards incompatible]
  (Issues #252, #262, #263)

* Use ``backports.ssl_match_hostname`` if it's installed. (Issue #274)

* Added ``.tell()`` method to ``urllib3.response.HTTPResponse`` which
  returns the number of bytes read so far. (Issue #277)

* Support for platforms without threading. (Issue #289)

* Expand default-port comparison in ``HTTPConnectionPool.is_same_host``
  to allow a pool with no specified port to be considered equal to to an
  HTTP/HTTPS url with port 80/443 explicitly provided. (Issue #305)

* Improved default SSL/TLS settings to avoid vulnerabilities.
  (Issue #309)

* Fixed ``urllib3.poolmanager.ProxyManager`` not retrying on connect errors.
  (Issue #310)

* Disable Nagle's Algorithm on the socket for non-proxies. A subset of requests
  will send the entire HTTP request ~200 milliseconds faster; however, some of
  the resulting TCP packets will be smaller. (Issue #254)

* ... [Short description of non-trivial change.] (Issue #)



1.7.1 (2013-09-25)
++++++++++++++++++

* Added granular timeout support with new ``urllib3.util.Timeout`` class.
  (Issue #231)

* Fixed Python 3.4 support. (Issue #238)


1.7 (2013-08-14)
++++++++++++++++

* More exceptions are now pickle-able, with tests. (Issue #174)

* Fixed redirecting with relative URLs in Location header. (Issue #178)

* Support for relative urls in ``Location: ...`` header. (Issue #179)

* ``urllib3.response.HTTPResponse`` now inherits from ``io.IOBase`` for bonus
  file-like functionality. (Issue #187)

* Passing ``assert_hostname=False`` when creating a HTTPSConnectionPool will
  skip hostname verification for SSL connections. (Issue #194)

* New method ``urllib3.response.HTTPResponse.stream(...)`` which acts as a
  generator wrapped around ``.read(...)``. (Issue #198)

* IPv6 url parsing enforces brackets around the hostname. (Issue #199)

* Fixed thread race condition in
  ``urllib3.poolmanager.PoolManager.connection_from_host(...)`` (Issue #204)

* ``ProxyManager`` requests now include non-default port in ``Host: ...``
  header. (Issue #217)

* Added HTTPS proxy support in ``ProxyManager``. (Issue #170 #139)

* New ``RequestField`` object can be passed to the ``fields=...`` param which
  can specify headers. (Issue #220)

* Raise ``urllib3.exceptions.ProxyError`` when connecting to proxy fails.
  (Issue #221)

* Use international headers when posting file names. (Issue #119)

* Improved IPv6 support. (Issue #203)


1.6 (2013-04-25)
++++++++++++++++

* Contrib: Optional SNI support for Py2 using PyOpenSSL. (Issue #156)

* ``ProxyManager`` automatically adds ``Host: ...`` header if not given.

* Improved SSL-related code. ``cert_req`` now optionally takes a string like
  "REQUIRED" or "NONE". Same with ``ssl_version`` takes strings like "SSLv23"
  The string values reflect the suffix of the respective constant variable.
  (Issue #130)

* Vendored ``socksipy`` now based on Anorov's fork which handles unexpectedly
  closed proxy connections and larger read buffers. (Issue #135)

* Ensure the connection is closed if no data is received, fixes connection leak
  on some platforms. (Issue #133)

* Added SNI support for SSL/TLS connections on Py32+. (Issue #89)

* Tests fixed to be compatible with Py26 again. (Issue #125)

* Added ability to choose SSL version by passing an ``ssl.PROTOCOL_*`` constant
  to the ``ssl_version`` parameter of ``HTTPSConnectionPool``. (Issue #109)

* Allow an explicit content type to be specified when encoding file fields.
  (Issue #126)

* Exceptions are now pickleable, with tests. (Issue #101)

* Fixed default headers not getting passed in some cases. (Issue #99)

* Treat "content-encoding" header value as case-insensitive, per RFC 2616
  Section 3.5. (Issue #110)

* "Connection Refused" SocketErrors will get retried rather than raised.
  (Issue #92)

* Updated vendored ``six``, no longer overrides the global ``six`` module
  namespace. (Issue #113)

* ``urllib3.exceptions.MaxRetryError`` contains a ``reason`` property holding
  the exception that prompted the final retry. If ``reason is None`` then it
  was due to a redirect. (Issue #92, #114)

* Fixed ``PoolManager.urlopen()`` from not redirecting more than once.
  (Issue #149)

* Don't assume ``Content-Type: text/plain`` for multi-part encoding parameters
  that are not files. (Issue #111)

* Pass `strict` param down to ``httplib.HTTPConnection``. (Issue #122)

* Added mechanism to verify SSL certificates by fingerprint (md5, sha1) or
  against an arbitrary hostname (when connecting by IP or for misconfigured
  servers). (Issue #140)

* Streaming decompression support. (Issue #159)


1.5 (2012-08-02)
++++++++++++++++

* Added ``urllib3.add_stderr_logger()`` for quickly enabling STDERR debug
  logging in urllib3.

* Native full URL parsing (including auth, path, query, fragment) available in
  ``urllib3.util.parse_url(url)``.

* Built-in redirect will switch method to 'GET' if status code is 303.
  (Issue #11)

* ``urllib3.PoolManager`` strips the scheme and host before sending the request
  uri. (Issue #8)

* New ``urllib3.exceptions.DecodeError`` exception for when automatic decoding,
  based on the Content-Type header, fails.

* Fixed bug with pool depletion and leaking connections (Issue #76). Added
  explicit connection closing on pool eviction. Added
  ``urllib3.PoolManager.clear()``.

* 99% -> 100% unit test coverage.


1.4 (2012-06-16)
++++++++++++++++

* Minor AppEngine-related fixes.

* Switched from ``mimetools.choose_boundary`` to ``uuid.uuid4()``.

* Improved url parsing. (Issue #73)

* IPv6 url support. (Issue #72)


1.3 (2012-03-25)
++++++++++++++++

* Removed pre-1.0 deprecated API.

* Refactored helpers into a ``urllib3.util`` submodule.

* Fixed multipart encoding to support list-of-tuples for keys with multiple
  values. (Issue #48)

* Fixed multiple Set-Cookie headers in response not getting merged properly in
  Python 3. (Issue #53)

* AppEngine support with Py27. (Issue #61)

* Minor ``encode_multipart_formdata`` fixes related to Python 3 strings vs
  bytes.


1.2.2 (2012-02-06)
++++++++++++++++++

* Fixed packaging bug of not shipping ``test-requirements.txt``. (Issue #47)


1.2.1 (2012-02-05)
++++++++++++++++++

* Fixed another bug related to when ``ssl`` module is not available. (Issue #41)

* Location parsing errors now raise ``urllib3.exceptions.LocationParseError``
  which inherits from ``ValueError``.


1.2 (2012-01-29)
++++++++++++++++

* Added Python 3 support (tested on 3.2.2)

* Dropped Python 2.5 support (tested on 2.6.7, 2.7.2)

* Use ``select.poll`` instead of ``select.select`` for platforms that support
  it.

* Use ``Queue.LifoQueue`` instead of ``Queue.Queue`` for more aggressive
  connection reusing. Configurable by overriding ``ConnectionPool.QueueCls``.

* Fixed ``ImportError`` during install when ``ssl`` module is not available.
  (Issue #41)

* Fixed ``PoolManager`` redirects between schemes (such as HTTP -> HTTPS) not
  completing properly. (Issue #28, uncovered by Issue #10 in v1.1)

* Ported ``dummyserver`` to use ``tornado`` instead of ``webob`` +
  ``eventlet``. Removed extraneous unsupported dummyserver testing backends.
  Added socket-level tests.

* More tests. Achievement Unlocked: 99% Coverage.


1.1 (2012-01-07)
++++++++++++++++

* Refactored ``dummyserver`` to its own root namespace module (used for
  testing).

* Added hostname verification for ``VerifiedHTTPSConnection`` by vendoring in
  Py32's ``ssl_match_hostname``. (Issue #25)

* Fixed cross-host HTTP redirects when using ``PoolManager``. (Issue #10)

* Fixed ``decode_content`` being ignored when set through ``urlopen``. (Issue
  #27)

* Fixed timeout-related bugs. (Issues #17, #23)


1.0.2 (2011-11-04)
++++++++++++++++++

* Fixed typo in ``VerifiedHTTPSConnection`` which would only present as a bug if
  you're using the object manually. (Thanks pyos)

* Made RecentlyUsedContainer (and consequently PoolManager) more thread-safe by
  wrapping the access log in a mutex. (Thanks @christer)

* Made RecentlyUsedContainer more dict-like (corrected ``__delitem__`` and
  ``__getitem__`` behaviour), with tests. Shouldn't affect core urllib3 code.


1.0.1 (2011-10-10)
++++++++++++++++++

* Fixed a bug where the same connection would get returned into the pool twice,
  causing extraneous "HttpConnectionPool is full" log warnings.


1.0 (2011-10-08)
++++++++++++++++

* Added ``PoolManager`` with LRU expiration of connections (tested and
  documented).
* Added ``ProxyManager`` (needs tests, docs, and confirmation that it works
  with HTTPS proxies).
* Added optional partial-read support for responses when
  ``preload_content=False``. You can now make requests and just read the headers
  without loading the content.
* Made response decoding optional (default on, same as before).
* Added optional explicit boundary string for ``encode_multipart_formdata``.
* Convenience request methods are now inherited from ``RequestMethods``. Old
  helpers like ``get_url`` and ``post_url`` should be abandoned in favour of
  the new ``request(method, url, ...)``.
* Refactored code to be even more decoupled, reusable, and extendable.
* License header added to ``.py`` files.
* Embiggened the documentation: Lots of Sphinx-friendly docstrings in the code
  and docs in ``docs/`` and on urllib3.readthedocs.org.
* Embettered all the things!
* Started writing this file.


0.4.1 (2011-07-17)
++++++++++++++++++

* Minor bug fixes, code cleanup.


0.4 (2011-03-01)
++++++++++++++++

* Better unicode support.
* Added ``VerifiedHTTPSConnection``.
* Added ``NTLMConnectionPool`` in contrib.
* Minor improvements.


0.3.1 (2010-07-13)
++++++++++++++++++

* Added ``assert_host_name`` optional parameter. Now compatible with proxies.


0.3 (2009-12-10)
++++++++++++++++

* Added HTTPS support.
* Minor bug fixes.
* Refactored, broken backwards compatibility with 0.2.
* API to be treated as stable from this version forward.


0.2 (2008-11-17)
++++++++++++++++

* Added unit tests.
* Bug fixes.


0.1 (2008-11-16)
++++++++++++++++

* First release.

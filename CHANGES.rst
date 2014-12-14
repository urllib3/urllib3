Changes
=======

1.10 (2014-12-14)
+++++++++++++++++

* Disabled SSLv3. (Issue #473)

* Add ``Url.url`` property to return the composed url string. (Issue #394)

* Fixed PyOpenSSL + gevent ``WantWriteError``. (Issue #412)

* ``MaxRetryError.reason`` will always be an exception, not string.
  (Issue #481)

* Fixed SSL-related timeouts not being detected as timeouts. (Issue #492)

* Py3: Use ``ssl.create_default_context()`` when available. (Issue #473)

* Emit ``InsecureRequestWarning`` for *every* insecure HTTPS request.
  (Issue #496)

* Emit ``SecurityWarning`` when certificate has no ``subjectAltName``.
  (Issue #499)

* Close and discard sockets which experienced SSL-related errors.
  (Issue #501)

* Handle ``body`` param in ``.request(...)``. (Issue #513)

* Respect timeout with HTTPS proxy. (Issue #505)

* PyOpenSSL: Handle ZeroReturnError exception. (Issue #520)


1.9.1 (2014-09-13)
++++++++++++++++++

* Apply socket arguments before binding. (Issue #427)

* More careful checks if fp-like object is closed. (Issue #435)

* Fixed packaging issues of some development-related files not
  getting included. (Issue #440)
  
* Allow performing *only* fingerprint verification. (Issue #444)

* Emit ``SecurityWarning`` if system clock is waaay off. (Issue #445)

* Fixed PyOpenSSL compatibility with PyPy. (Issue #450)

* Fixed ``BrokenPipeError`` and ``ConnectionError`` handling in Py3.
  (Issue #443)



1.9 (2014-07-04)
++++++++++++++++

* Shuffled around development-related files. If you're maintaining a distro
  package of urllib3, you may need to tweak things. (Issue #415)

* Unverified HTTPS requests will trigger a warning on the first request. See
  our new `security documentation
  <https://urllib3.readthedocs.org/en/latest/security.html>`_ for details.
  (Issue #426)

* New retry logic and ``urllib3.util.retry.Retry`` configuration object.
  (Issue #326)

* All raised exceptions should now wrapped in a
  ``urllib3.exceptions.HTTPException``-extending exception. (Issue #326)

* All errors during a retry-enabled request should be wrapped in
  ``urllib3.exceptions.MaxRetryError``, including timeout-related exceptions
  which were previously exempt. Underlying error is accessible from the
  ``.reason`` propery. (Issue #326)

* ``urllib3.exceptions.ConnectionError`` renamed to
  ``urllib3.exceptions.ProtocolError``. (Issue #326)

* Errors during response read (such as IncompleteRead) are now wrapped in
  ``urllib3.exceptions.ProtocolError``. (Issue #418)

* Requesting an empty host will raise ``urllib3.exceptions.LocationValueError``.
  (Issue #417)

* Catch read timeouts over SSL connections as
  ``urllib3.exceptions.ReadTimeoutError``. (Issue #419)

* Apply socket arguments before connecting. (Issue #427)


1.8.3 (2014-06-23)
++++++++++++++++++

* Fix TLS verification when using a proxy in Python 3.4.1. (Issue #385)

* Add ``disable_cache`` option to ``urllib3.util.make_headers``. (Issue #393)

* Wrap ``socket.timeout`` exception with
  ``urllib3.exceptions.ReadTimeoutError``. (Issue #399)

* Fixed proxy-related bug where connections were being reused incorrectly.
  (Issues #366, #369)

* Added ``socket_options`` keyword parameter which allows to define
  ``setsockopt`` configuration of new sockets. (Issue #397)

* Removed ``HTTPConnection.tcp_nodelay`` in favor of
  ``HTTPConnection.default_socket_options``. (Issue #397)

* Fixed ``TypeError`` bug in Python 2.6.4. (Issue #411)


1.8.2 (2014-04-17)
++++++++++++++++++

* Fix ``urllib3.util`` not being included in the package.


1.8.1 (2014-04-17)
++++++++++++++++++

* Fix AppEngine bug of HTTPS requests going out as HTTP. (Issue #356)

* Don't install ``dummyserver`` into ``site-packages`` as it's only needed
  for the test suite. (Issue #362)

* Added support for specifying ``source_address``. (Issue #352)


1.8 (2014-03-04)
++++++++++++++++

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

* Increased maximum number of SubjectAltNames in ``urllib3.contrib.pyopenssl``
  from the default 64 to 1024 in a single certificate. (Issue #318)

* Headers are now passed and stored as a custom
  ``urllib3.collections_.HTTPHeaderDict`` object rather than a plain ``dict``.
  (Issue #329, #333)

* Headers no longer lose their case on Python 3. (Issue #236)

* ``urllib3.contrib.pyopenssl`` now uses the operating system's default CA
  certificates on inject. (Issue #332)

* Requests with ``retries=False`` will immediately raise any exceptions without
  wrapping them in ``MaxRetryError``. (Issue #348)

* Fixed open socket leak with SSL-related failures. (Issue #344, #348)


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

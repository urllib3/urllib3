Changes
=======


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

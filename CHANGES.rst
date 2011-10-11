Changes
=======

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

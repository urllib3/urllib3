Changes
=======

1.0 (2011-10-08)
++++++++++++++++

* Added ``ProxyManager`` (still needs some work for HTTPS support).
* Added ``PoolManager`` with LRU expiration of connections.
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
  and docs in ``docs/`` and on
  `urllib3.readthedocs.org <http://urllib3.readthedocs.org/>`_.
* Embettered all the things!
* Started writing this file.

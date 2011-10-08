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
* Added more friendly helpers for consistency, inherited from
  ``urllib3.request.RequestMethods``: ``get_url``, ``post_url``, ``head_url``,
  ``delete_url``, ``put_url``, ``options_url``, ``patch_url``, ``trace_url``.
* Refactored code to be even more decoupled, reusable, and extendable.
* License header added to ``.py`` files.
* Embiggened the documentation: Lots of Sphinx-friendly docstrings in the code
  and docs in ``docs/`` and on
  `urllib3.readthedocs.org <http://urllib3.readthedocs.org/>`_.
* Embettered all the things!
* Started writing this file.

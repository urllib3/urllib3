.. _helpers:

Helpers
=======

Useful methods for working with :mod:`httplib`, completely decoupled from
code specific to **urllib3**.

At the very core, just like its predecessors, :mod:`urllib3` is built on top of
:mod:`httplib` -- the lowest level HTTP library included in the Python
standard library.

To aid the limited functionality of the :mod:`httplib` module, :mod:`urllib3`
provides various helper methods which are used with the higher level components
but can also be used independently.

Timeouts
--------

.. automodule:: urllib3.util.timeout
   :members:

Retries
-------

.. automodule:: urllib3.util.retry
   :members:

URL Helpers
-----------

.. automodule:: urllib3.util.url
    :members:

Filepost
--------

.. automodule:: urllib3.filepost
   :members:

.. automodule:: urllib3.fields
   :members:

Request
-------

.. automodule:: urllib3.request
   :members:

.. automodule:: urllib3.util.request
   :members:

Response
--------

.. automodule:: urllib3.response
   :members:
   :undoc-members:

SSL/TLS Helpers
---------------

.. automodule:: urllib3.util.ssl_
   :members:

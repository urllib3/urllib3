ConnectionPools
===============

A connection pool is a container for a collection of connections to a specific
host.

:mod:`urllib3.connectionpool` comes with two connection pools:

.. automodule:: urllib3.connectionpool

    .. autoclass:: HTTPConnectionPool
       :members:
       :inherited-members:

    .. autoclass:: HTTPSConnectionPool


Helpers
-------

There are various helper functions provided for instantiating these
ConnectionPools more easily:

    .. autofunction:: connection_from_url

    .. autofunction:: make_headers

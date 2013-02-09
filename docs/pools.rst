ConnectionPools
===============

.. automodule:: urllib3.connectionpool

A connection pool is a container for a collection of connections to a specific
host.

If you need to make requests to the same host repeatedly, then you should use a
:class:`.HTTPConnectionPool`. ::

    >>> from urllib3 import HTTPConnectionPool
    >>> pool = HTTPConnectionPool('ajax.googleapis.com', maxsize=1)
    >>> r = pool.request('GET', '/ajax/services/search/web',
    ...                  fields={'q': 'urllib3', 'v': '1.0'})
    >>> r.status
    200
    >>> r.headers['content-type']
    'text/javascript; charset=utf-8'
    >>> len(r.data) # Content of the response
    3318
    >>> r = pool.request('GET', '/ajax/services/search/web',
    ...                  fields={'q': 'python', 'v': '1.0'})
    >>> len(r.data) # Content of the response
    2960
    >>> pool.num_connections
    1
    >>> pool.num_requests
    2

By default, the pool will cache just one connection. If you're planning on using
such a pool in a multithreaded environment, you should set the ``maxsize`` of
the pool to a higher number, such as the number of threads. You can also control
many other variables like timeout, blocking, and default headers.

Helpers
-------

There are various helper functions provided for instantiating these
ConnectionPools more easily:

    .. autofunction:: connection_from_url

API
---

:mod:`urllib3.connectionpool` comes with two connection pools:

    .. autoclass:: HTTPConnectionPool
       :members:
       :inherited-members:

    .. autoclass:: HTTPSConnectionPool


All of these pools inherit from a common base class:

    .. autoclass:: ConnectionPool

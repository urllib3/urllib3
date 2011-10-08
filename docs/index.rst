=====================
urllib3 Documentation
=====================

Highlights
==========

- Re-use the same socket connection for multiple requests
  (:class:`HTTPConnectionPool` and :class:`HTTPSConnectionPool`)
  (with optional client-side certificate verification).
- File posting (:func:`encode_multipart_formdata`).
- Built-in redirection and retries (optional).
- Supports gzip and deflate decoding.
- Thread-safe and sanity-safe.
- Small and easy to understand codebase perfect for extending and building upon.
  For a more comprehensive solution, have a look at
  `Requests <http://python-requests.org/>`_.


Getting Started
===============

Installing
----------

``pip install urllib3`` or fetch the latest source from
`github.com/shazow/urllib3 <https://github.com/shazow/urllib3>`_.

ConnectionPool
--------------

If you need to make requests to the same host repeatedly, then you should use a
:doc:`ConnectionPool <pools>`. ::

    >>> from urllib3 import HTTPConnectionPool
    >>> pool = HTTPConnectionPool('ajax.googleapis.com', maxsize=1)
    >>> r = pool.request('GET', '/ajax/services/search/web',
    ...                  fields={'q': 'urllib3', 'v': '1.0'})
    >>> r.status
    200
    >>> r.headers['content-type']
    'text/javascript; charset=utf-8'
    >>> len(r.data)
    3318
    >>> r = pool.request('GET', '/ajax/services/search/web',
    ...                  fields={'q': 'python', 'v': '1.0'})
    >>> len(r.data)
    2960
    >>> pool.num_connections
    1
    >>> pool.num_requests
    2

By default, the pool will cache just one connection. If you're planning on using
such a pool in a multithreaded environment, you should set the ``maxsize`` of
the pool to a higher number, such as the number of threads. You can also control
many other variables like timeout, blocking, and default headers.


PoolManager
-----------

If you need to make requests to multiple hosts, then you can use a
:doc:`PoolManager <managers>`, which takes care of maintaining your pools
so you don't have to. ::

    >>> from urllib3 import PoolManager
    >>> manager = PoolManager(10)
    >>> r = manager.request('GET', 'http://google.com/')
    >>> r.headers['server']
    'gws'
    >>> r = manager.request('GET', 'http://yahoo.com/')
    >>> r.headers['server']
    'YTS/1.20.0'
    >>> r = manager.request('POST', 'http://google.com/mail')
    >>> r = manager.request('HEAD', 'http://google.com/calendar')
    >>> len(manager.pools)
    2
    >>> conn = manager.connection_from_host('google.com')
    >>> conn.num_requests
    3

The PoolManager uses a Least Recently Used (LRU) policy for discarding old
pools. That is, if you set the PoolManager ``num_pools`` to 10, then after
making requests to 11 different hosts, the least recently used pool will be
discarded.

Actually, the cleanup of old pools doesn't happen immediately, but you can read
more about it in :class:`urllib3._collections.RecentlyUsedContainer`
implementation.


Components
==========

.. toctree::
   :maxdepth: 1

   pools
   managers

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

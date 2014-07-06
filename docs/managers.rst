PoolManager
===========

.. automodule:: urllib3.poolmanager

A pool manager is an abstraction for a collection of
:doc:`ConnectionPools <pools>`.

If you need to make requests to multiple hosts, then you can use a
:class:`.PoolManager`, which takes care of maintaining your pools
so you don't have to.

.. doctest ::

    >>> from urllib3 import PoolManager
    >>> manager = PoolManager(10)
    >>> r = manager.request('GET', 'http://example.com')
    >>> r.headers['server']
    'ECS (iad/182A)'
    >>> r = manager.request('GET', 'http://httpbin.org/')
    >>> r.headers['server']
    'gunicorn/18.0'
    >>> r = manager.request('POST', 'http://httpbin.org/headers')
    >>> r = manager.request('HEAD', 'http://httpbin.org/cookies')
    >>> len(manager.pools)
    2
    >>> conn = manager.connection_from_host('httpbin.org')
    >>> conn.num_requests
    3

The API of a :class:`.PoolManager` object is similar to that of a
:doc:`ConnectionPool <pools>`, so they can be passed around interchangeably.

The PoolManager uses a Least Recently Used (LRU) policy for discarding old
pools. That is, if you set the PoolManager ``num_pools`` to 10, then after
making requests to 11 or more different hosts, the least recently used pools
will be cleaned up eventually.

Cleanup of stale pools does not happen immediately. You can read more about the
implementation and the various adjustable variables within
:class:`~urllib3._collections.RecentlyUsedContainer`.

API
---

    .. autoclass:: PoolManager
       :inherited-members:

ProxyManager
============

:class:`.ProxyManager` is an HTTP proxy-aware subclass of :class:`.PoolManager`.
It produces a single
:class:`~urllib3.connectionpool.HTTPConnectionPool` instance for all HTTP
connections and individual per-server:port
:class:`~urllib3.connectionpool.HTTPSConnectionPool` instances for tunnelled
HTTPS connections.

API
---
    .. autoclass:: ProxyManager


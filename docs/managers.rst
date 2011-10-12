PoolManager
===========

.. automodule:: urllib3.poolmanager

A pool manager is an abstraction for a collection of
:doc:`ConnectionPools <pools>`.

If you need to make requests to multiple hosts, then you can use a
:class:`.PoolManager`, which takes care of maintaining your pools
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

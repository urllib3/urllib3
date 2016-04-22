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

A :class:`.PoolManager` will create a new :doc:`ConnectionPool <pools>`
when no :doc:`ConnectionPools <pools>` exist with a matching pool key.
The pool key is derived using the requested URL and the current values
of the ``connection_pool_kw`` instance variable on :class:`.PoolManager`.

The keys in ``connection_pool_kw`` used when deriving the key are
configurable. For example, by default the ``my_field`` key is not
considered.

.. doctest ::

    >>> from urllib3.poolmanager import PoolManager
    >>> manager = PoolManager(10, my_field='wheat')
    >>> manager.connection_from_url('http://example.com')
    >>> manager.connection_pool_kw['my_field'] = 'barley'
    >>> manager.connection_from_url('http://example.com')
    >>> len(manager.pools)
    1

To make the pool manager create new pools when the value of
``my_field`` changes, you can define a custom pool key and alter
the ``key_fn_by_scheme`` instance variable on :class:`.PoolManager`.

.. doctest ::

    >>> import functools
    >>> from collections import namedtuple
    >>> from urllib3.poolmanager import PoolManager, HTTPPoolKey
    >>> from urllib3.poolmanager import default_key_normalizer as normalizer
    >>> CustomKey = namedtuple('CustomKey', HTTPPoolKey._fields + ('my_field',))
    >>> manager = PoolManager(10, my_field='wheat')
    >>> manager.key_fn_by_scheme['http'] = functools.partial(normalizer, CustomKey)
    >>> manager.connection_from_url('http://example.com')
    >>> manager.connection_pool_kw['my_field'] = 'barley'
    >>> manager.connection_from_url('http://example.com')
    >>> len(manager.pools)
    2

The API of a :class:`.PoolManager` object is similar to that of a
:doc:`ConnectionPool <pools>`, so they can be passed around interchangeably.

The PoolManager uses a Least Recently Used (LRU) policy for discarding old
pools. That is, if you set the PoolManager ``num_pools`` to 10, then after
making requests to 11 or more different hosts, the least recently used pools
will be cleaned up eventually.

Cleanup of stale pools does not happen immediately but can be forced when used 
as a context manager.

.. doctest ::
    
    >>> from urllib3 import PoolManager
    >>> with PoolManager(10) as manager:
    ...     r = manager.request('GET', 'http://example.com')
    ...     r = manager.request('GET', 'http://httpbin.org/')
    ...     len(manager.pools)
    ...
    2
    >>> len(manager.pools)
    0

You can read more about the implementation and the various adjustable variables 
within :class:`~urllib3._collections.RecentlyUsedContainer`.

API
---

    .. autoclass:: PoolManager
       :inherited-members:
    .. autoclass:: BasePoolKey
       :inherited-members:
    .. autoclass:: HTTPPoolKey
       :inherited-members:
    .. autoclass:: HTTPSPoolKey
       :inherited-members:

ProxyManager
============

:class:`.ProxyManager` is an HTTP proxy-aware subclass of :class:`.PoolManager`.
It produces a single
:class:`~urllib3.connectionpool.HTTPConnectionPool` instance for all HTTP
connections and individual per-server:port
:class:`~urllib3.connectionpool.HTTPSConnectionPool` instances for tunnelled
HTTPS connections.

Example using proxy authentication:

::

	>>> headers = urllib3.make_headers(proxy_basic_auth='myusername:mypassword')
	>>> proxy = urllib3.ProxyManager('http://localhost:3128', proxy_headers=headers)
	>>> r = proxy.request('GET', 'http://example.com/')
	>>> r.status
	200


API
---
    .. autoclass:: ProxyManager


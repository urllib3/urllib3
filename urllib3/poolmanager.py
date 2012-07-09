# urllib3/poolmanager.py
# Copyright 2008-2012 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

import logging

from ._collections import RecentlyUsedContainer
from .connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from .connectionpool import get_host, connection_from_url, port_by_scheme
from .exceptions import HostChangedError
from .request import RequestMethods


__all__ = ['PoolManager', ]


pool_classes_by_scheme = {
    'http': HTTPConnectionPool,
    'https': HTTPSConnectionPool,
}

log = logging.getLogger(__name__)


class PoolManager(RequestMethods):
    """
    Allows for arbitrary requests while transparently keeping track of
    necessary connection pools for you.

    :param num_pools:
        Number of connection pools to cache before discarding the least recently
        used pool.

    :param \**connection_pool_kw:
        Additional parameters are used to create fresh
        :class:`urllib3.connectionpool.ConnectionPool` instances.

    Example: ::

        >>> manager = PoolManager(num_pools=2)
        >>> r = manager.urlopen("http://google.com/")
        >>> r = manager.urlopen("http://google.com/mail")
        >>> r = manager.urlopen("http://yahoo.com/")
        >>> len(manager.pools)
        2

    """

    # TODO: Make sure there are no memory leaks here.

    def __init__(self, num_pools=10, proxy_url = None, **connection_pool_kw):
        self.connection_pool_kw = connection_pool_kw
        self.proxy_url = proxy_url
        self.pools = RecentlyUsedContainer(num_pools)

    def connection_from_host(self, host, port=80, scheme='http'):
        """
        Get a :class:`ConnectionPool` based on the host, port, and scheme.

        Note that an appropriate ``port`` value is required here to normalize
        connection pools in our container most effectively.
        """
        pool_key = (scheme, host, port)

        # If the scheme, host, or port doesn't match existing open connections,
        # open a new ConnectionPool.
        pool = self.pools.get(pool_key)
        if pool:
            return pool

        # Make a fresh ConnectionPool of the desired type
        pool_cls = pool_classes_by_scheme[scheme]
        pool = pool_cls(host, port, proxy_url = self.proxy_url, **self.connection_pool_kw)

        self.pools[pool_key] = pool

        return pool

    def connection_from_url(self, url):
        """
        Similar to :func:`urllib3.connectionpool.connection_from_url` but
        doesn't pass any additional parameters to the
        :class:`urllib3.connectionpool.ConnectionPool` constructor.

        Additional parameters are taken from the :class:`.PoolManager`
        constructor.
        """
        scheme, host, port = get_host(url)

        port = port or port_by_scheme.get(scheme, 80)

        return self.connection_from_host(host, port=port, scheme=scheme)

    def urlopen(self, method, url, **kw):
        """
        Same as :meth:`urllib3.connectionpool.HTTPConnectionPool.urlopen`.

        ``url`` must be absolute, such that an appropriate
        :class:`urllib3.connectionpool.ConnectionPool` can be chosen for it.
        """
        conn = self.connection_from_url(url)
        try:
            return conn.urlopen(method, url, **kw)

        except HostChangedError as e:
            kw['retries'] = e.retries # Persist retries countdown
            return self.urlopen(method, e.url, **kw)
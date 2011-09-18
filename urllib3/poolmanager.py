from heapq import heappop, heappush
from itertools import count
from collections import MutableMapping, namedtuple

from connectionpool import HTTPConnectionPool, HTTPSConnectionPool, get_host


pool_classes_by_scheme = {
    'http': HTTPConnectionPool,
    'https': HTTPSConnectionPool,
}


PriorityEntry = namedtuple('PriorityEntry', ['priority', 'key', 'is_valid'])


class RecentlyUsedContainer(MutableMapping):
    """
    Provides a dict-like that maintains up to ``maxsize`` keys while throwing
    away the least-recently-used keys beyond ``maxsize``.

    Excess keys are cleaned out every time a new key is set.
    """

    def __init__(self, maxsize=10):
        self.maxsize = maxsize

        self._container = {}

        # Global access counter to determine relative recency
        self.counter = count()

        # We use a heap to store our keys sorted by their absolute access count
        self.priority_heap = []

        # We look up the heap entry by the key to invalidate it when we update
        # the absolute access count for the key by inserting a new entry.
        self.priority_lookup = {}

    def _invalidate_entry(self, key):
        # Invalidate old entry
        self.priority_lookup[key].is_valid = False

    def _push_entry(self, key):
        new_count = self.counter()
        new_entry = PriorityEntry(new_count, key, True)

        self.priority_lookup[key] = new_entry
        heappush(self.priority_heap, new_entry)

    def __getitem__(self, key):
        item = self._container.get(key)

        if not item:
            return

        # Invalidate old entry
        self._invalidate_entry(key)

        # Insert new entry with new high priority
        self._push_entry(key)

        return item

    def __setitem__(self, key, item):
        # TODO: Make sure behaviour is correct when setting an existing key.
        # Add item to our container and priority heap
        self._container[key] = item
        self._push_entry(key)

        excess_entries = self.max_size - len(self.priorty_heap)
        if excess_entries < 1:
            return

        # Discard old entries
        for _ in xrange(excess_entries):
            _, key, is_valid = heappop(self.priority_heap)

            if not is_valid:
                continue # Invalidated entry, skip

            del self._container[key]
            del self._priority_lookup[key]

    def __delitem__(self, key):
        self._invalidate_entry(key)
        del self._container[key]
        del self._priority_lookup[key]

    def __len__(self):
        return len(self.count_heap)

    def __iter__(self):
        return self._container.__iter()

    def __contains__(self, key):
        return self._container.__contains__(key)


class PoolManager(object):
    """
    Allows for arbitrary requests while transparently keeping track of
    necessary connection pools for you.

    num_pools
        Number of connection pools to cache before discarding the least recently
        used pool.

    """

    # TODO: Make sure there are no memory leaks here.

    def __init__(self, num_pools=10, **connection_pool_kw):
        self.connection_pool_kw = connection_pool_kw

        self.pools = RecentlyUsedContainer(num_pools)
        self.recently_used_pools = []

    def connection_from_url(self, url):
        """
        Similar to connectionpool.connection_from_url but doesn't pass any
        additional keywords to the ConnectionPool constructor. Additional
        keywords are taken from the PoolManager constructor.
        """
        scheme, host, port = get_host(url)

        # We hash pools on their scheme://host, because we want a separate pool
        # if it's the same host but different scheme.
        pool_key = scheme + '://' + host

        pool = self.pools.get(pool_key)
        if pool:
            return pool

        pool = pool_classes_by_scheme[scheme](host, port, **self.connection_pool_kw)
        self.pools[pool_key] = pool

        return pool

    def urlopen(self, method, url, **kw):
        "Same as HTTP(S)ConnectionPool.urlopen"
        conn = self.connection_from_url(url)
        return conn.urlopen(method, url, **kw)

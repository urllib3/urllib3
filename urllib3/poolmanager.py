from heapq import heappop, heappush
from itertools import count
from collections import MutableMapping

from connectionpool import HTTPConnectionPool, HTTPSConnectionPool, get_host


pool_classes_by_scheme = {
    'http': HTTPConnectionPool,
    'https': HTTPSConnectionPool,
}


class PriorityEntry(object):
    __slots__ = ['priority', 'key', 'is_valid']

    def __init__(self, priority, key, is_valid=True):
        self.priority = priority
        self.key = key
        self.is_valid = is_valid

    def __cmp__(self, other):
        return self.priority - other.priority


class RecentlyUsedContainer(MutableMapping):
    """
    Provides a dict-like that maintains up to ``maxsize`` keys while throwing
    away the least-recently-used keys beyond ``maxsize``.

    The weakness of this datastructure is if few keys infinitely contend for the
    top most-accessed spots and at least one key remains within the maxsize
    limit but is never accessed.
    """

    # TODO: Make this threadsafe.

    # If len(self.priority_heap) exceeds self.maxsize * CLEANUP_FACTOR, then we
    # will attempt to cleanup some of the heap's invalidated entries during the
    # next 'get' operation.
    CLEANUP_FACTOR = 10

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
        new_count = next(self.counter)
        new_entry = PriorityEntry(new_count, key, True)

        self.priority_lookup[key] = new_entry
        heappush(self.priority_heap, new_entry)

    def _prune_entries(self, num):
        while num > 0:
            p = heappop(self.priority_heap)

            if not p.is_valid:
                continue # Invalidated entry, skip

            del self._container[p.key]
            del self.priority_lookup[p.key]
            num -= 1

    def _prune_invalidated_entries(self):
        "Rebuild our priority_heap without the invalidated entries."
        new_heap = []
        while self.priority_heap:
            p = heappop(self.priority_heap)

            if p.is_valid:
                heappush(new_heap, p)

        self.priority_heap = new_heap

    def __getitem__(self, key):
        item = self._container.get(key)

        if not item:
            return

        # Invalidate old entry
        self._invalidate_entry(key)

        # Insert new entry with new high priority
        self._push_entry(key)

        if len(self.priority_heap) > self.maxsize * self.CLEANUP_FACTOR:
            # Heap is getting too big, try to clean up any tailing invalidated
            # entries.
            self._prune_invalidated_entries()

        return item

    def __setitem__(self, key, item):
        # TODO: Make sure behaviour is correct when setting an existing key.
        # Add item to our container and priority heap
        self._container[key] = item
        self._push_entry(key)

        # Discard invalid and excess entries
        self._prune_entries(len(self._container) - self.maxsize)


    def __delitem__(self, key):
        self._invalidate_entry(key)
        del self._container[key]
        del self._priority_lookup[key]

    def __len__(self):
        return len(self.priority_heap)

    def __iter__(self):
        return self._container.__iter__()

    def __contains__(self, key):
        return self._container.__contains__(key)


class PoolManager(object):
    """
    Allows for arbitrary requests while transparently keeping track of
    necessary connection pools for you.

    num_pools
        Number of connection pools to cache before discarding the least recently
        used pool.

    Additional parameters are used to create fresh ConnectionPool instances.

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

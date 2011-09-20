from itertools import count
from collections import MutableMapping, deque

from connectionpool import HTTPConnectionPool, HTTPSConnectionPool, get_host


pool_classes_by_scheme = {
    'http': HTTPConnectionPool,
    'https': HTTPSConnectionPool,
}

port_by_scheme = {
    'http': 80,
    'https': 433,
}


class AccessEntry(object):
    __slots__ = ('key', 'is_valid')

    def __init__(self, key, is_valid=True):
        self.key = key
        self.is_valid = is_valid


class RecentlyUsedContainer(MutableMapping):
    """
    Provides a dict-like that maintains up to ``maxsize`` keys while throwing
    away the least-recently-used keys beyond ``maxsize``.

    The weakness of this datastructure is if few keys infinitely contend for the
    top most-accessed spots and at least one key remains within the maxsize
    limit but is never accessed.
    """

    # TODO: Make this threadsafe. _prune_invalidated_entries should be the
    # only real pain-point for this.

    # If len(self.access_log) exceeds self.maxsize * CLEANUP_FACTOR, then we
    # will attempt to cleanup the invalidated entries in the access_log
    # datastructure during the next 'get' operation.
    CLEANUP_FACTOR = 10

    def __init__(self, maxsize=10):
        self._maxsize = maxsize

        self._container = {}

        # We use a deque to to store our keys ordered by the last access.
        self.access_log = deque()

        # We look up the access log entry by the key to invalidate it so we can
        # insert a new authorative entry at the head without having to dig and
        # find the old entry for removal immediately.
        self.access_lookup = {}

        # Trigger a heap cleanup when we get past this size
        self.access_log_limit = maxsize * self.CLEANUP_FACTOR

    def _push_entry(self, key):
        "Push entry onto our access log, invalidate the old entry if exists."
        # Invalidate old entry if it exists
        old_entry = self.access_lookup.get(key)
        if old_entry:
            old_entry.is_valid = False

        new_entry = AccessEntry(key)

        self.access_lookup[key] = new_entry
        self.access_log.appendleft(new_entry)

    def _prune_entries(self, num):
        "Pop entries from our access log until we popped ``num`` valid ones."
        while num > 0:
            p = self.access_log.pop()

            if not p.is_valid:
                continue # Invalidated entry, skip

            del self._container[p.key]
            del self.access_lookup[p.key]
            num -= 1

    def _prune_invalidated_entries(self):
        "Rebuild our access_log without the invalidated entries."
        for _ in xrange(len(self.access_log)):
            if self.access_log[-1].is_valid:
                self.access_log.rotate(1)
                continue

            self.access_log.pop()

    def __getitem__(self, key):
        item = self._container.get(key)

        if not item:
            return

        # Insert new entry with new high priority, also implicitly invalidates
        # the old entry.
        self._push_entry(key)

        if len(self.access_log) > self.access_log_limit:
            # Heap is getting too big, try to clean up any tailing invalidated
            # entries.
            self._prune_invalidated_entries()

        return item

    def __setitem__(self, key, item):
        # Add item to our container and access log
        self._container[key] = item
        self._push_entry(key)

        # Discard invalid and excess entries
        self._prune_entries(len(self._container) - self._maxsize)


    def __delitem__(self, key):
        self._invalidate_entry(key)
        del self._container[key]
        del self._access_lookup[key]

    def __len__(self):
        return len(self.access_log)

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

        # If the scheme, host, or port doesn't match existing open connections,
        # open a new ConnectionPool.
        pool_key = (scheme, host, port or port_by_scheme.get(scheme, 80))

        pool = self.pools.get(pool_key)
        if pool:
            return pool

        # Make a fresh ConnectionPool of the desired type
        pool_cls = pool_classes_by_scheme[scheme]
        pool = pool_cls(host, port, **self.connection_pool_kw)

        self.pools[pool_key] = pool

        return pool

    def urlopen(self, method, url, **kw):
        "Same as HTTP(S)ConnectionPool.urlopen"
        conn = self.connection_from_url(url)
        return conn.urlopen(method, url, **kw)

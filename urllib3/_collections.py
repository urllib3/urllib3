# urllib3/_collections.py
# Copyright 2008-2012 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

from collections import MutableMapping
from threading import Lock

try: # Python 2.7+
    from collections import OrderedDict
except ImportError:
    from .packages.ordered_dict import OrderedDict


__all__ = ['RecentlyUsedContainer']


_Empty = object()


class RecentlyUsedContainer(MutableMapping):
    """
    Provides a dict-like that maintains up to ``maxsize`` keys while throwing
    away the least-recently-used keys beyond ``maxsize``.

    :param maxsize:
        Maximum number of recent elements to retain.

    :param dispose_func:
        Callback which will get called wwhenever an element is evicted from
        the container.
    """

    ContainerType = OrderedDict

    def __init__(self, maxsize=10, dispose_func=None):
        self._maxsize = maxsize
        self.dispose_func = dispose_func

        # OrderedDict is not inherently threadsafe, so protect it with a lock
        self._container = self.ContainerType()
        self._lock = Lock()

    def clear(self):
        with self._lock:
            # copy pointers to all values, then wipe the mapping
            # under Python 2, this copies the list of values twice :-|
            values = list(self._container.values())
            self._container.clear()

        if self.dispose_func:
            for value in values:
                self.dispose_func(value)

    def __getitem__(self, key):
        # Re-insert the item, moving it to the end of the eviction line.
        with self._lock:
            item = self._container.pop(key)
            self._container[key] = item
            return item

    def __setitem__(self, key, item):
        evicted_entry = _Empty
        with self._lock:
            # Possibly evict the existing value of 'key'
            evicted_entry = self._container.get(key, _Empty)
            self._container[key] = item

            # If we didn't evict an existing value, we might have to evict the
            # least recently used item from the beginning of the container.
            if len(self._container) > self._maxsize:
                _key, evicted_entry = self._container.popitem(last=False)

        if self.dispose_func and evicted_entry is not _Empty:
            self.dispose_func(evicted_entry)

    def __delitem__(self, key):
        with self._lock:
            entry = self._container.pop(key)

        if self.dispose_func:
            self.dispose_func(entry)

    def __len__(self):
        with self._lock:
            return len(self._container)

    def __iter__(self):
        raise NotImplementedError('Iteration over this class is unlikely to be threadsafe.')

    def keys(self):
        with self._lock:
            return self._container.keys()

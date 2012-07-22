# urllib3/_collections.py
# Copyright 2008-2012 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php
from __future__ import with_statement

import threading
from collections import MutableMapping

try:
    # available on 2.7 and up
    from collections import OrderedDict
    # hush pyflakes
    OrderedDict
except ImportError:
    from .packages.ordered_dict import OrderedDict

__all__ = ['RecentlyUsedContainer']

class RecentlyUsedContainer(MutableMapping):
    """
    Provides a dict-like that maintains up to ``maxsize`` keys while throwing
    away the least-recently-used keys beyond ``maxsize``.
    """

    # this is an object no one else knows about, sort of a hyper-None
    # cf. the implementation of OrderedDict
    __marker = object()

    def __init__(self, maxsize=10, dispose_func=None):
        """Constructor.

        Args:
            maxsize - int, maximum number of elements to retain
            dispose_func - callback taking a single argument, called to destroy
                elements that are being evicted or released
        """
        self._maxsize = maxsize
        self.dispose_func = dispose_func

        # OrderedDict is not inherently threadsafe, so protect it with a lock
        self._mapping = OrderedDict()
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            # copy pointers to all values, then wipe the mapping
            # under Python 2, this copies the list of values twice :-|
            values = list(self._mapping.values())
            self._mapping.clear()

        if self.dispose_func:
            for value in values:
                self.dispose_func(value)

    def __getitem__(self, key):
        with self._lock:
            # remove and re-add the item, moving it to the end of the eviction line
            # throw the KeyError back to calling code if it's not present:
            item = self._mapping.pop(key)
            self._mapping[key] = item
            return item

    def __setitem__(self, key, item):
        evicted_entry = self.__marker
        with self._lock:
            # possibly evict the existing value of 'key'
            evicted_entry = self._mapping.get(key, self.__marker)
            self._mapping[key] = item
            # if we didn't evict an existing value, we might have to evict the LRU value
            if len(self._mapping) > self._maxsize:
                # pop from the beginning of the dict
                _key, evicted_entry = self._mapping.popitem(last=False)

        if self.dispose_func and evicted_entry is not self.__marker:
            self.dispose_func(evicted_entry)

    def __delitem__(self, key):
        with self._lock:
            entry = self._mapping.pop(key)
        if self.dispose_func:
            self.dispose_func(entry)

    def __len__(self):
        with self._lock:
            return len(self._mapping)

    def __iter__(self):
        raise NotImplementedError('Iteration over this class is unlikely to be threadsafe.')

    def keys(self):
        with self._lock:
            return self._mapping.keys()

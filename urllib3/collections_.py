# urllib3/collections_.py
# Copyright 2008-2013 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

from collections import Mapping, MutableMapping
try:
    from threading import RLock
except ImportError: # Platform-specific: No threads available
    class RLock:
        def __enter__(self):
            pass

        def __exit__(self, exc_type, exc_value, traceback):
            pass


try: # Python 2.7+
    from collections import OrderedDict
except ImportError:
    from .packages.ordered_dict import OrderedDict
from .packages.six import itervalues


__all__ = ['RecentlyUsedContainer', 'HTTPHeaderDict']


_Null = object()


class RecentlyUsedContainer(MutableMapping):
    """
    Provides a thread-safe dict-like container which maintains up to
    ``maxsize`` keys while throwing away the least-recently-used keys beyond
    ``maxsize``.

    :param maxsize:
        Maximum number of recent elements to retain.

    :param dispose_func:
        Every time an item is evicted from the container,
        ``dispose_func(value)`` is called.  Callback which will get called
    """

    ContainerCls = OrderedDict

    def __init__(self, maxsize=10, dispose_func=None):
        self._maxsize = maxsize
        self.dispose_func = dispose_func

        self._container = self.ContainerCls()
        self.lock = RLock()

    def __getitem__(self, key):
        # Re-insert the item, moving it to the end of the eviction line.
        with self.lock:
            item = self._container.pop(key)
            self._container[key] = item
            return item

    def __setitem__(self, key, value):
        evicted_value = _Null
        with self.lock:
            # Possibly evict the existing value of 'key'
            evicted_value = self._container.get(key, _Null)
            self._container[key] = value

            # If we didn't evict an existing value, we might have to evict the
            # least recently used item from the beginning of the container.
            if len(self._container) > self._maxsize:
                _key, evicted_value = self._container.popitem(last=False)

        if self.dispose_func and evicted_value is not _Null:
            self.dispose_func(evicted_value)

    def __delitem__(self, key):
        with self.lock:
            value = self._container.pop(key)

        if self.dispose_func:
            self.dispose_func(value)

    def __len__(self):
        with self.lock:
            return len(self._container)

    def __iter__(self):
        raise NotImplementedError('Iteration over this class is unlikely to be threadsafe.')

    def clear(self):
        with self.lock:
            # Copy pointers to all values, then wipe the mapping
            # under Python 2, this copies the list of values twice :-|
            values = list(self._container.values())
            self._container.clear()

        if self.dispose_func:
            for value in values:
                self.dispose_func(value)

    def keys(self):
        with self.lock:
            return self._container.keys()


class HTTPHeaderDict(MutableMapping):

    def __init__(self, headers=None, **kwargs):
        self._data = {}
        if headers is None:
            headers = {}
        self.update(headers, **kwargs)

    def raw_header(self, key):
        return self._data[key.lower()]

    def append(self, key, value):
        self._data.setdefault(key.lower(), []).append((key, value))

    def get_all(self):
        return dict(self.items())

    def copy(self):
        h = HTTPHeaderDict()
        for key in self:
            for rawkey, value in self.raw_header(key):
                h.append(rawkey, value)
        return h

    def __eq__(self, other):
        if not isinstance(other, Mapping):
            return False
        other = HTTPHeaderDict(other)
        return dict((k1, self[k1]) for k1 in self._data) == \
                dict((k2, other[k2]) for k2 in other._data)

    def __getitem__(self, key):
        values = self._data[key.lower()]
        return ', '.join(value[1] for value in values)

    def __setitem__(self, key, value):
        self._data[key.lower()] = [(key, value)]

    def __delitem__(self, key):
        del self._data[key.lower()]

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        for headers in itervalues(self._data):
            yield headers[0][0]

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.get_all())

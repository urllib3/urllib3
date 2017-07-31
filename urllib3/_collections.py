from __future__ import absolute_import
from collections import Mapping, MutableMapping
from contextlib import contextmanager
try:
    from threading import RLock, Condition
except ImportError:  # Platform-specific: No threads available
    class RLock:
        def __enter__(self):
            pass

        def __exit__(self, exc_type, exc_value, traceback):
            pass


try:  # Python 2.7+
    from collections import OrderedDict
except ImportError:
    from .packages.ordered_dict import OrderedDict
from .packages.six import iterkeys, itervalues, PY3


__all__ = ['RecentlyUsedContainer', 'BlockingRecentlyUsedContainer',
           'HTTPHeaderDict']


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
            values = list(itervalues(self._container))
            self._container.clear()

        if self.dispose_func:
            for value in values:
                self.dispose_func(value)

    def keys(self):
        with self.lock:
            return list(iterkeys(self._container))


class BlockingRecentlyUsedContainer(object):
    """
    Provides a thread-safe container which maintains up to ``maxsize`` keys.
    Key access is done through acquiring leases, which have to be released
    afterwards. Inserting keys beyond ``maxsize`` throw away old keys, but not
    before ensuring that all leases on such keys have been released.

    Note: eviction/disposal is triggered on inserting new keys, not on
    releasing of the last lease. In the case of connection pooling, this means
    we will maintain the connections as long as possible.

    This does not expose any means to clear the pool, because it would involve
    waiting for all leases to be released. If there are concurrent acquisition
    of leases, the clear method may block indefinitely.

    :param maxsize:
        Maximum number of recent elements to retain.

    :param dispose_func:
        Every time an item is evicted from the container,
        ``dispose_func(value)`` is called.  Callback which will get called
    """
    ContainerCls = OrderedDict

    def __init__(self, maxsize=10, dispose_func=None):
        self._maxsize = maxsize
        self._dispose_func = dispose_func

        self._container = self.ContainerCls()
        self.lock = RLock()

        self._freelist = self.ContainerCls()
        self._nwaiters = 0
        self._container_not_full = Condition(self.lock)
        self._victim = None

    def acquire(self, key, constructor):
        """
        Acquires a lease on ``key`` inside this pool, if it has already
        existed. If it hasn't, ``constructor`` is called to generate the value
        and it is inserted into the pool beforehand.

        If the insertion is done while the pool is full, another key is
        evicted in a FIFO order, but not before all leases on the key have been
        released.

        :param key:
            Key to acquire lease upon.

        :param constructor:
            Function-like, used to construct the new item to lease on if it
            hasn't existed yet.

        :returns value:
            Value associated with key, or the value created by ``constructor``
            if no such item can be found.
        """
        with self.lock:
            result = self._container.get(key, _Null)

            if result is not _Null:
                refcount, value = self._container.pop(key)
                self._container[key] = [refcount + 1, value]
                _ = self._freelist.pop(key, _Null)
                return value
            else:
                item = constructor()

                if len(self._container) < self._maxsize:
                    self._container[key] = [1, item]
                else:
                    evicted_value = _Null
                    if len(self._freelist) > 0:
                        _, evicted_value = self._freelist.popitem(last=False)
                    else:
                        self._nwaiters += 1
                        self._container_not_full.wait()
                        _, evicted_value = self._container.pop(self._victim)
                        self._nwaiters -= 1

                    self._container[key] = [1, item]
                    if self._dispose_func and evicted_value is not _Null:
                        self._dispose_func(evicted_value)

                return item

    def release(self, key, silent=False):
        """
        Release the lease on ``key``.
        If other threads are waiting for for an eviction victim, notify them.

        :param key:
            Key to release lease from

        :param silent:
            If True, may raise RuntimeError if user release more times than
            the number of times this key is acquired.
        """
        with self.lock:
            refcount, item = self._container[key]
            refcount -= 1
            self._container[key][0] = refcount

            if refcount == 0:
                if self._nwaiters > 0:
                    self._victim = key
                    self._container_not_full.notify()
                else:
                    # Mark key as free for future eviction
                    self._freelist[key] = item
            elif refcount < 0 and not silent:
                raise RuntimeError("Release of unacquired key")

    @contextmanager
    def acquire_then_release(self, key, constructor, silent=False):
        value = self.acquire(key, constructor)
        try:
            yield value
        except Exception:
            raise
        self.release(key, silent)


class HTTPHeaderDict(MutableMapping):
    """
    :param headers:
        An iterable of field-value pairs. Must not contain multiple field names
        when compared case-insensitively.

    :param kwargs:
        Additional field-value pairs to pass in to ``dict.update``.

    A ``dict`` like container for storing HTTP Headers.

    Field names are stored and compared case-insensitively in compliance with
    RFC 7230. Iteration provides the first case-sensitive key seen for each
    case-insensitive pair.

    Using ``__setitem__`` syntax overwrites fields that compare equal
    case-insensitively in order to maintain ``dict``'s api. For fields that
    compare equal, instead create a new ``HTTPHeaderDict`` and use ``.add``
    in a loop.

    If multiple fields that are equal case-insensitively are passed to the
    constructor or ``.update``, the behavior is undefined and some will be
    lost.

    >>> headers = HTTPHeaderDict()
    >>> headers.add('Set-Cookie', 'foo=bar')
    >>> headers.add('set-cookie', 'baz=quxx')
    >>> headers['content-length'] = '7'
    >>> headers['SET-cookie']
    'foo=bar, baz=quxx'
    >>> headers['Content-Length']
    '7'
    """

    def __init__(self, headers=None, **kwargs):
        super(HTTPHeaderDict, self).__init__()
        self._container = OrderedDict()
        if headers is not None:
            if isinstance(headers, HTTPHeaderDict):
                self._copy_from(headers)
            else:
                self.extend(headers)
        if kwargs:
            self.extend(kwargs)

    def __setitem__(self, key, val):
        self._container[key.lower()] = [key, val]
        return self._container[key.lower()]

    def __getitem__(self, key):
        val = self._container[key.lower()]
        return ', '.join(val[1:])

    def __delitem__(self, key):
        del self._container[key.lower()]

    def __contains__(self, key):
        return key.lower() in self._container

    def __eq__(self, other):
        if not isinstance(other, Mapping) and not hasattr(other, 'keys'):
            return False
        if not isinstance(other, type(self)):
            other = type(self)(other)
        return (dict((k.lower(), v) for k, v in self.itermerged()) ==
                dict((k.lower(), v) for k, v in other.itermerged()))

    def __ne__(self, other):
        return not self.__eq__(other)

    if not PY3:  # Python 2
        iterkeys = MutableMapping.iterkeys
        itervalues = MutableMapping.itervalues

    __marker = object()

    def __len__(self):
        return len(self._container)

    def __iter__(self):
        # Only provide the originally cased names
        for vals in self._container.values():
            yield vals[0]

    def pop(self, key, default=__marker):
        '''D.pop(k[,d]) -> v, remove specified key and return the corresponding value.
          If key is not found, d is returned if given, otherwise KeyError is raised.
        '''
        # Using the MutableMapping function directly fails due to the private marker.
        # Using ordinary dict.pop would expose the internal structures.
        # So let's reinvent the wheel.
        try:
            value = self[key]
        except KeyError:
            if default is self.__marker:
                raise
            return default
        else:
            del self[key]
            return value

    def discard(self, key):
        try:
            del self[key]
        except KeyError:
            pass

    def add(self, key, val):
        """Adds a (name, value) pair, doesn't overwrite the value if it already
        exists.

        >>> headers = HTTPHeaderDict(foo='bar')
        >>> headers.add('Foo', 'baz')
        >>> headers['foo']
        'bar, baz'
        """
        key_lower = key.lower()
        new_vals = [key, val]
        # Keep the common case aka no item present as fast as possible
        vals = self._container.setdefault(key_lower, new_vals)
        if new_vals is not vals:
            vals.append(val)

    def extend(self, *args, **kwargs):
        """Generic import function for any type of header-like object.
        Adapted version of MutableMapping.update in order to insert items
        with self.add instead of self.__setitem__
        """
        if len(args) > 1:
            raise TypeError("extend() takes at most 1 positional "
                            "arguments ({0} given)".format(len(args)))
        other = args[0] if len(args) >= 1 else ()

        if isinstance(other, HTTPHeaderDict):
            for key, val in other.iteritems():
                self.add(key, val)
        elif isinstance(other, Mapping):
            for key in other:
                self.add(key, other[key])
        elif hasattr(other, "keys"):
            for key in other.keys():
                self.add(key, other[key])
        else:
            for key, value in other:
                self.add(key, value)

        for key, value in kwargs.items():
            self.add(key, value)

    def getlist(self, key, default=__marker):
        """Returns a list of all the values for the named field. Returns an
        empty list if the key doesn't exist."""
        try:
            vals = self._container[key.lower()]
        except KeyError:
            if default is self.__marker:
                return []
            return default
        else:
            return vals[1:]

    # Backwards compatibility for httplib
    getheaders = getlist
    getallmatchingheaders = getlist
    iget = getlist

    # Backwards compatibility for http.cookiejar
    get_all = getlist

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, dict(self.itermerged()))

    def _copy_from(self, other):
        for key in other:
            val = other.getlist(key)
            if isinstance(val, list):
                # Don't need to convert tuples
                val = list(val)
            self._container[key.lower()] = [key] + val

    def copy(self):
        clone = type(self)()
        clone._copy_from(self)
        return clone

    def iteritems(self):
        """Iterate over all header lines, including duplicate ones."""
        for key in self:
            vals = self._container[key.lower()]
            for val in vals[1:]:
                yield vals[0], val

    def itermerged(self):
        """Iterate over all headers, merging duplicate ones together."""
        for key in self:
            val = self._container[key.lower()]
            yield val[0], ', '.join(val[1:])

    def items(self):
        return list(self.iteritems())

    @classmethod
    def from_httplib(cls, message):  # Python 2
        """Read headers from a Python 2 httplib message object."""
        # python2.7 does not expose a proper API for exporting multiheaders
        # efficiently. This function re-reads raw lines from the message
        # object and extracts the multiheaders properly.
        headers = []

        for line in message.headers:
            if line.startswith((' ', '\t')):
                key, value = headers[-1]
                headers[-1] = (key, value + '\r\n' + line.rstrip())
                continue

            key, value = line.split(':', 1)
            headers.append((key, value.strip()))

        return cls(headers)

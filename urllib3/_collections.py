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
from .packages.six import iterkeys, itervalues, PY3


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
            values = list(itervalues(self._container))
            self._container.clear()

        if self.dispose_func:
            for value in values:
                self.dispose_func(value)

    def keys(self):
        with self.lock:
            return list(iterkeys(self._container))


_dict_setitem = dict.__setitem__
_dict_getitem = dict.__getitem__
_dict_delitem = dict.__delitem__
_dict_contains = dict.__contains__
_dict_setdefault = dict.setdefault


class HTTPHeaderDict(dict):
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
        dict.__init__(self)
        if headers is not None:
            self.update(headers)
        if kwargs:
            self.update(kwargs)

    def __setitem__(self, key, val):
        return _dict_setitem(self, key.lower(), (key, val))

    def __getitem__(self, key):
        val = _dict_getitem(self, key.lower())
        return ', '.join(val[1:])

    def __delitem__(self, key):
        return _dict_delitem(self, key.lower())

    def __contains__(self, key):
        return _dict_contains(self, key.lower())

    def __eq__(self, other):
        if not isinstance(other, Mapping):
            return False
        if not isinstance(other, type(self)):
            other = type(self)(other)
        return dict((k1, self[k1]) for k1 in self) == dict((k2, other[k2]) for k2 in other)

    values = MutableMapping.values
    get = MutableMapping.get
    pop = MutableMapping.pop
    update = MutableMapping.update
    
    if not PY3: # Python 2:
        iterkeys = MutableMapping.iterkeys
        itervalues = MutableMapping.itervalues

    def add(self, key, val):
        """Adds a (name, value) pair, doesn't overwrite the value if it already
        exists.

        >>> headers = HTTPHeaderDict(foo='bar')
        >>> headers.add('Foo', 'baz')
        >>> headers['foo']
        'bar, baz'
        """
        key_lower = key.lower()
        new_vals = key, val
        # Keep the common case aka no item present as fast as possible
        vals = _dict_setdefault(self, key_lower, new_vals)
        if new_vals is not vals:
            # The item was not inserted, as there was a previous one
            if isinstance(vals, list):
                # If already several items got inserted, we have a list
                vals.append(val)
            else:
                # Only one item so far, need to convert the tuple to list
                _dict_setitem(self, key_lower, [vals[0], vals[1], val])

    def update_add(*args, **kwds):
        """Generic import function for any type of header-like object.
        Adapted version of MutableMapping.update in order to insert items
        with self.add instead of self.__setitem__
        """
        if len(args) > 2:
            raise TypeError("update() takes at most 2 positional "
                            "arguments ({} given)".format(len(args)))
        elif not args:
            raise TypeError("update() takes at least 1 argument (0 given)")
        self = args[0]
        other = args[1] if len(args) >= 2 else ()
        
        if isinstance(other, Mapping):
            for key in other:
                self.add(key, other[key])
        elif hasattr(other, "keys"):
            for key in other.keys():
                self.add(key, other[key])
        else:
            for key, value in other:
                self.add(key, value)

        for key, value in kwds.items():
            self.add(key, value)

    def getlist(self, key):
        """Returns a list of all the values for the named field. Returns an
        empty list if the key doesn't exist."""
        try:
            vals = _dict_getitem(self, key.lower())
        except KeyError:
            return []
        else:
            if isinstance(vals, tuple):
                return [vals[1]]
            else:
                return vals[1:]

    # Backwards compatibility for httplib
    getheaders = getlist
    getallmatchingheaders = getlist
    iget = getlist

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, self.compatible_dict())

    def copy(self):
        clone = type(self)()
        for key in self:
            val = _dict_getitem(self, key)
            if isinstance(val, list):
                # Don't need to convert tuples
                val = list(val)
            _dict_setitem(clone, key, val)
        return clone
    
    def iteritems(self):
        # Extration of the original headers
        for key in self:
            val = _dict_getitem(self, key)
            yield val[0], ', '.join(val[1:])

    def items(self):
        return list(self.iteritems())

    def compatible_dict(self):
        """
        If the client performing the request is not adjusted for this class, this function
        can create a backwards and standards compatible version containing comma joined
        strings instead of lists for multiple headers.
        """
        return dict(self.iteritems())
    
    @classmethod
    def from_httplib(cls, headers):
        ret = cls()
        ret.update_add(headers)
        return ret

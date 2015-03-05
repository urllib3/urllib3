from collections import Mapping, MutableMapping
try:
    from threading import RLock
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


__all__ = ['RecentlyUsedContainer', 'HTTPHeaderDict']


NON_JOINABLE_HEADERS = frozenset(['set-cookie', 'set-cookie2'])
SEMICOLON_JOINABLE = frozenset(['cookie'])
SPECIAL_CASE_MULTIPLE_HEADERS = NON_JOINABLE_HEADERS.union(SEMICOLON_JOINABLE)

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
            self.extend(headers)
        if kwargs:
            self.extend(kwargs)

    def __setitem__(self, key, val):
        if key in self:
            del self[key]
        self.add(key, val)
        return val

    def __getitem__(self, key):
        key_lower = key.lower()
        _, values = _dict_getitem(self, key_lower)
        if key_lower in SPECIAL_CASE_MULTIPLE_HEADERS:
            if key_lower in SEMICOLON_JOINABLE:
                return '; '.join(values)
            else:
                # NOTE(sigmavirus24): Should we return something else?
                return values[0]
        return ', '.join(values)

    def __delitem__(self, key):
        return _dict_delitem(self, key.lower())

    def __contains__(self, key):
        return _dict_contains(self, key.lower())

    def __eq__(self, other):
        if not isinstance(other, Mapping) and not hasattr(other, 'keys'):
            return False
        if not isinstance(other, type(self)):
            other = type(self)(other)
        getlist = self.getlist
        otherlist = other.getlist
        return (dict((k1.lower(), getlist(k1)) for k1 in self) ==
                dict((k2.lower(), otherlist(k2)) for k2 in other))

    def __ne__(self, other):
        return not (self == other)

    values = MutableMapping.values
    get = MutableMapping.get
    update = MutableMapping.update

    if not PY3:  # Python 2
        iterkeys = MutableMapping.iterkeys
        itervalues = MutableMapping.itervalues

    __marker = object()

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
        new_vals = key, [val]
        # Keep the common case aka no item present as fast as possible
        vals = _dict_setdefault(self, key_lower, new_vals)
        if new_vals is not vals:
            # If already several items got inserted, we have a list
            vals[1].append(val)

    def add_multi(self, key, values):
        """Add multiple header values at once for a key.

        >>> headers = HTTPHeaderDict(foo='bar')
        >>> headers.add_multi('foo', ['biz', 'baz'])
        >>> headers['foo']
        'bar, biz, baz'
        >>> headers.add('my-header', ['my-value0', 'my-value1'])
        >>> headers['my-header']
        'my-value0, my-value1'
        """
        if not isinstance(values, (tuple, list)):
            raise ValueError('Header values must be a list or tuple')
        key_lower = key.lower()
        new_vals = key, values
        vals = _dict_setdefault(self, key_lower, new_vals)
        if new_vals is not vals:
            # If it's already set, merely extend the existing list
            vals[1].extend(values)

    def extend(self, *args, **kwargs):
        """Generic import function for any type of header-like object.
        Adapted version of MutableMapping.update in order to insert items
        with self.add instead of self.__setitem__
        """
        if len(args) > 1:
            raise TypeError("update() takes at most 2 positional "
                            "arguments ({} given)".format(len(args)))
        # NOTE(sigmavirus24): A kwarg might be named "other", so we use *args
        # to avoid name collisions. This probably looks very suspect, but this
        # allows greater freedom in the use of kwargs when updating with
        # extend.
        other = args[0] if args else ()

        # NOTE(sigmavirus24): Abstract how we iterate over "other" to keep the
        # logic for updating self simple below.
        def _iter_values(other_dict):
            if hasattr(other_dict, 'getlist'):
                for key in other_dict:
                    yield key, other_dict.getlist(key)
            elif isinstance(other_dict, Mapping):
                for key in other_dict:
                    yield key, other_dict[key]
            elif hasattr(other_dict, 'keys'):
                for key in other_dict.keys():
                    yield key, other_dict[key]
            else:  # List or tuple of 2-tuples
                for key, value in other_dict:
                    yield key, value

        for key, value in _iter_values(other):
            if isinstance(value, list):
                self.add_multi(key, value)
            else:
                self.add(key, value)

        for key, value in kwargs.items():
            self.add(key, value)

    def getlist(self, key):
        """Returns a list of all the values for the named field. Returns an
        empty list if the key doesn't exist."""
        try:
            vals = _dict_getitem(self, key.lower())
        except KeyError:
            return []
        else:
            # Return a copy so users do not accidentally modify our copy
            return list(vals[1])

    # Backwards compatibility for httplib
    getheaders = getlist
    getallmatchingheaders = getlist
    iget = getlist

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, dict(self.itermerged()))

    def copy(self):
        clone = type(self)()
        for key in self:
            header, values = _dict_getitem(self, key)
            # Create a new list of values so we can append/extend
            _dict_setitem(clone, key, (header, list(values)))
        return clone

    def iteritems(self):
        """Iterate over all header lines, including duplicate ones."""
        for key in self:
            header, values = _dict_getitem(self, key)
            for val in values:
                yield header, val

    def itermerged(self):
        """Iterate over all headers, merging duplicate ones together."""
        for key in self:
            header, values = _dict_getitem(self, key)
            if header in SPECIAL_CASE_MULTIPLE_HEADERS:
                if header in SEMICOLON_JOINABLE:
                    yield header, '; '.join(values)
                else:
                    for cookie in values:
                        yield header, cookie
            else:
                yield header, ', '.join(values)

    def items(self):
        return list(self.iteritems())

    @classmethod
    def from_httplib(cls, message, duplicates=('set-cookie',)):  # Python 2
        """Read headers from a Python 2 httplib message object."""
        ret = cls(message.items())
        # ret now contains only the last header line for each duplicate.
        # Importing with all duplicates would be nice, but this would
        # mean to repeat most of the raw parsing already done, when the
        # message object was created. Extracting only the headers of interest
        # separately, the cookies, should be faster and requires less
        # extra code.
        for key in duplicates:
            ret.discard(key)
            for val in message.getheaders(key):
                ret.add(key, val)
            return ret

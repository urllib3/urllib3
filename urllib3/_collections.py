from __future__ import absolute_import

from collections import Mapping

from .util.typing import (
    Generic, TypeVar, List, Union, Tuple, Any,
)
from .util.typing import Callable  # noqa: unused in this module
from .util.typing import Iterable  # noqa: unused in this module
from .util.typing import Iterator  # noqa: unused in this module
from .util.typing import MutableMapping  # noqa: unused in this module
from .util.typing import Optional  # noqa: unused in this module
from types import TracebackType  # noqa: unused in this module

from .packages.six import iterkeys, itervalues, PY3

import collections
import sys
if sys.version_info >= (2, 7):
    from collections import OrderedDict
else:
    from .packages.ordered_dict import OrderedDict

try:
    from threading import RLock
except ImportError:  # Platform-specific: No threads available
    class RLock:
        def __enter__(self):
            # type: () -> RLock
            pass

        def __exit__(self, exc_type, exc_value, traceback):
            # type: (Optional[type], Optional[Exception], Optional[TracebackType]) -> bool
            pass

try:  # Platform-specific
    import typing   # noqa: unused in this module

    # TODO uncomment when mypy handle conditionals
    # if sys.version_info <= (2,):
    #     import httplib
    #     _MessageType = httplib.HTTPMessage
    # else:
    #     _MessageType = Any
    _MessageType = Any

    _T = TypeVar('_T')
    _K = TypeVar('_K')
    _V = TypeVar('_V')
    _HTTPHeaderVT = Union[Tuple[str, str], List[str]]
except ImportError:
    _K = None
    _V = None


__all__ = ['RecentlyUsedContainer', 'HTTPHeaderDict']


_Null = object()


class RecentlyUsedContainer(collections.MutableMapping, Generic[_K, _V]):
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

    # TODO be more precise about class type
    ContainerCls = OrderedDict  # type: type

    def __init__(self, maxsize=10, dispose_func=None):
        # type: (int, Optional[Callable[[_V], None]]) -> None
        self._maxsize = maxsize
        self.dispose_func = dispose_func

        self._container = self.ContainerCls()  # type: OrderedDict[_K, _V]
        self.lock = RLock()

    def __getitem__(self, key):
        # type: (_K) -> _V
        # Re-insert the item, moving it to the end of the eviction line.
        with self.lock:
            item = self._container.pop(key)
            self._container[key] = item
            return item

    def __setitem__(self, key, value):
        # type: (_K, _V) -> None
        evicted_value = _Null
        with self.lock:
            # Possibly evict the existing value of 'key'
            # TODO remove ignore when python/mypy#1576 and python/typeshed#223
            evicted_value = self._container.get(key, _Null)  # type: ignore
            self._container[key] = value

            # If we didn't evict an existing value, we might have to evict the
            # least recently used item from the beginning of the container.
            if len(self._container) > self._maxsize:
                _key, evicted_value = self._container.popitem(last=False)

        if self.dispose_func and evicted_value is not _Null:
            self.dispose_func(evicted_value)

    def __delitem__(self, key):
        # type: (_K) -> None
        with self.lock:
            value = self._container.pop(key)

        if self.dispose_func:
            self.dispose_func(value)

    def __len__(self):
        # type: () -> int
        with self.lock:
            return len(self._container)

    def __iter__(self):
        # type: () -> Iterator[_K]
        raise NotImplementedError('Iteration over this class is unlikely to be threadsafe.')

    def clear(self):
        # type: () -> None
        with self.lock:
            # Copy pointers to all values, then wipe the mapping
            values = list(itervalues(self._container))
            self._container.clear()

        if self.dispose_func:
            for value in values:
                self.dispose_func(value)

    def keys(self):
        # type: () -> List[_K]
        with self.lock:
            return list(iterkeys(self._container))


class HTTPHeaderDict(collections.MutableMapping):
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
        # type: (Optional[Iterable[Tuple[str, str]]], **str) -> None
        super(HTTPHeaderDict, self).__init__()
        self._container = OrderedDict()  # type: OrderedDict[str, _HTTPHeaderVT]
        if headers is not None:
            if isinstance(headers, HTTPHeaderDict):
                self._copy_from(headers)
            else:
                self.extend(headers)
        if kwargs:
            self.extend(kwargs)

    def __setitem__(self, key, val):
        # type: (str, str) -> Union[Tuple[str, str], List[str]]
        self._container[key.lower()] = (key, val)
        return self._container[key.lower()]

    def __getitem__(self, key):
        # type: (str) -> str
        val = self._container[key.lower()]
        # TODO remove ignore when python/mypy#1579
        return ', '.join(val[1:])  # type: ignore

    def __delitem__(self, key):
        # type: (str) -> None
        del self._container[key.lower()]

    def __contains__(self, key):
        # type: (Any) -> bool
        return key.lower() in self._container

    def __eq__(self, other):
        # type: (Any) -> bool
        if not isinstance(other, Mapping) and not hasattr(other, 'keys'):
            return False
        if not isinstance(other, type(self)):
            other = type(self)(other)
        return (dict((k.lower(), v) for k, v in self.itermerged()) ==
                dict((k.lower(), v) for k, v in other.itermerged()))

    def __ne__(self, other):
        # type: (Any) -> bool
        return not self.__eq__(other)

    if not PY3:  # Python 2
        iterkeys = collections.MutableMapping.iterkeys
        itervalues = collections.MutableMapping.itervalues

    __marker = object()

    def __len__(self):
        # type: () -> int
        return len(self._container)

    def __iter__(self):
        # type: () -> Iterator[str]
        # Only provide the originally cased names
        for vals in self._container.values():
            # TODO remove ignore when python/mypy#1579
            yield vals[0]  # type: ignore

    def pop(self, key, default=__marker):
        # type: (str, _T) -> Union[str, _T]
        # TODO will work when python/mypy#1576 and python/typeshed#223
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
        # type: (str) -> None
        try:
            del self[key]
        except KeyError:
            pass

    def add(self, key, val):
        # type: (str, str) -> None
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
        vals = self._container.setdefault(key_lower, new_vals)
        if new_vals is not vals:
            # new_vals was not inserted, as there was a previous one
            if isinstance(vals, list):
                # If already several items got inserted, we have a list
                vals.append(val)
            else:
                # vals should be a tuple then, i.e. only one item so far
                # Need to convert the tuple to list for further extension
                self._container[key_lower] = [vals[0], vals[1], val]

    def extend(self, *args, **kwargs):
        # type: (*Any, **str) -> None
        # TODO be more precise on accepted type of *args
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

    def getlist(self, key):
        # type: (str) -> List[str]
        """Returns a list of all the values for the named field. Returns an
        empty list if the key doesn't exist."""
        try:
            vals = self._container[key.lower()]
        except KeyError:
            return []
        else:
            if isinstance(vals, tuple):
                # TODO remove ignore when python/mypy#1579
                return [vals[1]]  # type: ignore
            else:
                return vals[1:]

    # Backwards compatibility for httplib
    getheaders = getlist
    getallmatchingheaders = getlist
    iget = getlist

    def __repr__(self):
        # type: () -> str
        return "%s(%s)" % (type(self).__name__, dict(self.itermerged()))

    def _copy_from(self, other):
        # type: (HTTPHeaderDict) -> None
        for key in other:
            val = other.getlist(key)
            if isinstance(val, list):
                # Don't need to convert tuples
                val = list(val)
            self._container[key.lower()] = [key] + val

    def copy(self):
        # type: () -> HTTPHeaderDict
        clone = type(self)()
        clone._copy_from(self)
        return clone

    def iteritems(self):
        # type: () -> Iterator[Tuple[str, str]]
        """Iterate over all header lines, including duplicate ones."""
        for key in self:
            vals = self._container[key.lower()]
            for val in vals[1:]:
                # TODO remove ignore when python/mypy#1578
                yield vals[0], val  # type: ignore

    def itermerged(self):
        # type: () -> Iterator[Tuple[str, str]]
        """Iterate over all headers, merging duplicate ones together."""
        for key in self:
            val = self._container[key.lower()]
            # TODO remove ignore when python/mypy#1579
            yield val[0], ', '.join(val[1:])  # type: ignore

    def items(self):
        # type: () -> List[Tuple[str, str]]
        return list(self.iteritems())

    @classmethod
    def from_httplib(cls, message):  # Python 2
        # type: (_MessageType) -> 'HTTPHeaderDict'
        """Read headers from a Python 2 httplib message object."""
        # python2.7 does not expose a proper API for exporting multiheaders
        # efficiently. This function re-reads raw lines from the message
        # object and extracts the multiheaders properly.
        headers = []  # type: List[Tuple[str, str]]

        for line in message.headers:
            if line.startswith((' ', '\t')):
                key, value = headers[-1]
                # TODO remove ignore when python/mypy#1578
                headers[-1] = (key, value + '\r\n' + line.rstrip())  # type: ignore
                continue

            key, value = line.split(':', 1)
            headers.append((key, value.strip()))

        return cls(headers)

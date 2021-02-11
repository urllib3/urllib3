import sys
from collections import OrderedDict
from types import TracebackType
from typing import (
    Any,
    Callable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    NoReturn,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

try:
    from threading import RLock
except ImportError:  # Platform-specific: No threads available

    class RLock:  # type: ignore
        def __enter__(self) -> None:
            pass

        def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_value: Optional[BaseException],
            traceback: Optional[TracebackType],
        ) -> None:
            pass


# Starting in Python 3.7 the 'dict' class is guaranteed to be
# ordered by insertion. This behavior was an implementation
# detail in Python 3.6. OrderedDict is implemented in C in
# later Python versions but still requires a lot more memory
# due to being implemented as a linked list.
if sys.version_info >= (3, 7):
    _ordered_dict = dict
else:
    _ordered_dict = OrderedDict


__all__ = ["RecentlyUsedContainer", "HTTPHeaderDict"]


_Null = object()

_KT = TypeVar("_KT")
_VT = TypeVar("_VT")


class RecentlyUsedContainer(MutableMapping[_KT, _VT]):
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
    _container: "OrderedDict[_KT, _VT]"
    dispose_func: Optional[Callable[[_VT], None]]
    _maxsize: int
    lock: RLock

    def __init__(
        self, maxsize: int = 10, dispose_func: Optional[Callable[[_VT], None]] = None
    ) -> None:
        self._maxsize = maxsize
        self.dispose_func = dispose_func
        self._container = self.ContainerCls()
        self.lock = RLock()

    def __getitem__(self, key: _KT) -> _VT:
        # Re-insert the item, moving it to the end of the eviction line.
        with self.lock:
            item = self._container.pop(key)
            self._container[key] = item
            return item

    def __setitem__(self, key: _KT, value: _VT) -> None:
        evicted_value: Optional[_VT] = None
        with self.lock:
            # Possibly evict the existing value of 'key'
            evicted_value = self._container.get(key, None)
            self._container[key] = value

            # If we didn't evict an existing value, we might have to evict the
            # least recently used item from the beginning of the container.
            if len(self._container) > self._maxsize:
                _key, evicted_value = self._container.popitem(last=False)

        if self.dispose_func and evicted_value is not None:
            self.dispose_func(evicted_value)

    def __delitem__(self, key: _KT) -> None:
        with self.lock:
            value = self._container.pop(key)

        if self.dispose_func:
            self.dispose_func(value)

    def __len__(self) -> int:
        with self.lock:
            return len(self._container)

    def __iter__(self) -> NoReturn:
        raise NotImplementedError(
            "Iteration over this class is unlikely to be threadsafe."
        )

    def clear(self) -> None:
        with self.lock:
            # Copy pointers to all values, then wipe the mapping
            values = list(self._container.values())
            self._container.clear()

        if self.dispose_func:
            for value in values:
                self.dispose_func(value)

    def keys(self) -> List[_KT]:  # type: ignore
        with self.lock:
            return list(self._container.keys())


class HTTPHeaderDict(MutableMapping[str, str]):
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

    _container: MutableMapping[str, List[str]]

    def __init__(
        self,
        headers: Optional[
            Union[
                "HTTPHeaderDict",
                Mapping[str, str],
                Iterator[Tuple[str, str]],
            ]
        ] = None,
        **kwargs: str,
    ) -> None:
        super().__init__()
        self._container = _ordered_dict()
        if headers is not None:
            if isinstance(headers, HTTPHeaderDict):
                self._copy_from(headers)
            else:
                self.extend(headers)
        if kwargs:
            self.extend(kwargs)

    def __setitem__(self, key: str, val: str) -> None:
        self._container[key.lower()] = [key, val]

    def __getitem__(self, key: str) -> str:
        val = self._container[key.lower()]
        return ", ".join(val[1:])

    def __delitem__(self, key: str) -> None:
        del self._container[key.lower()]

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            return key.lower() in self._container
        else:
            return False

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Mapping) and not hasattr(other, "keys"):
            return False
        if not isinstance(other, type(self)):
            other = type(self)(other)
        return {k.lower(): v for k, v in self.itermerged()} == {
            k.lower(): v for k, v in other.itermerged()
        }

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __len__(self) -> int:
        return len(self._container)

    def __iter__(self) -> Iterator[str]:
        # Only provide the originally cased names
        for vals in self._container.values():
            yield vals[0]

    def discard(self, key: str) -> None:
        try:
            del self[key]
        except KeyError:
            pass

    def add(self, key: str, val: str) -> None:
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

    def extend(
        self,
        *args: Union[
            "HTTPHeaderDict",
            Mapping[str, str],
            Iterator[Tuple[str, str]],
        ],
        **kwargs: str,
    ) -> None:
        """Generic import function for any type of header-like object.
        Adapted version of MutableMapping.update in order to insert items
        with self.add instead of self.__setitem__
        """
        if len(args) > 1:
            raise TypeError(
                f"extend() takes at most 1 positional arguments ({len(args)} given)"
            )
        other = args[0] if len(args) >= 1 else ()

        if isinstance(other, HTTPHeaderDict):
            for key, val in other.iteritems():
                self.add(key, val)
        elif isinstance(other, Mapping):
            for key in other:
                self.add(key, other[key])
        elif hasattr(other, "keys"):
            for key in other.keys():  # type: ignore
                self.add(key, other[key])  # type: ignore
        else:
            for key, value in other:
                self.add(key, value)

        for key, value in kwargs.items():
            self.add(key, value)

    def getlist(self, key: str, default: Optional[List[str]] = None) -> List[str]:
        """Returns a list of all the values for the named field. Returns an
        empty list if the key doesn't exist."""
        try:
            vals = self._container[key.lower()]
        except KeyError:
            if default is None:
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

    def __repr__(self) -> str:
        return f"{type(self).__name__}({dict(self.itermerged())})"

    def _copy_from(self, other: "HTTPHeaderDict") -> None:
        for key in other:
            val = other.getlist(key)
            if isinstance(val, list):
                # Don't need to convert tuples
                val = list(val)
            self._container[key.lower()] = [key] + val

    def copy(self) -> "HTTPHeaderDict":
        clone = type(self)()
        clone._copy_from(self)
        return clone

    def iteritems(self) -> Iterator[Tuple[str, str]]:
        """Iterate over all header lines, including duplicate ones."""
        for key in self:
            vals = self._container[key.lower()]
            for val in vals[1:]:
                yield vals[0], val

    def itermerged(self) -> Iterator[Tuple[str, str]]:
        """Iterate over all headers, merging duplicate ones together."""
        for key in self:
            val = self._container[key.lower()]
            yield val[0], ", ".join(val[1:])

    def items(self) -> List[Tuple[str, str]]:  # type: ignore
        return list(self.iteritems())

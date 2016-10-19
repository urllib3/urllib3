# Backport of selectors.py from Python 3.5+ to support Python < 3.4
# Also has the behavior specified in PEP 475 which is to retry syscalls
# in the case of an EINTR error. This module is required because selectors34
# does not follow this behavior and instead returns that no dile descriptor
# events have occurred rather than retry the syscall. The decision to drop
# support for select.devpoll is made to maintain 100% test coverage.

import errno
import select
import six
from collections import namedtuple, Mapping

import time
try:
    monotonic = time.monotonic
except AttributeError:
    monotonic = time.time

EVENT_READ = (1 << 0)
EVENT_WRITE = (1 << 1)

HAS_SELECT = True  # Variable that shows whether the platform has a selector.
_SYSCALL_SENTINEL = object()  # Sentinel in case a system call returns None.


def _fileobj_to_fd(fileobj):
    """ Return a file descriptor from a file object. If
    given an integer will simply return that integer back. """
    if isinstance(fileobj, six.integer_types):
        fd = fileobj
    else:
        try:
            fd = int(fileobj.fileno())
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Invalid file object: {0!r}".format(fileobj))
    if fd < 0:
        raise ValueError("Invalid file descriptor: {0}".format(fd))
    return fd


def _syscall_wrapper(func, syscall_timeout, *args, **kwargs):
    """ Wrapper function for syscalls that could fail due to EINTR.
    All functions should be retried if there is time left in the timeout
    in accordance with PEP 475. """
    if syscall_timeout is None:
        expires = None
    else:
        timeout = float(syscall_timeout)
        if timeout < 0.0:
            expires = None
        else:
            expires = monotonic() + timeout

    result = _SYSCALL_SENTINEL
    while result is _SYSCALL_SENTINEL:
        try:
            result = func(*args, **kwargs)
            break
        except OSError as e:
            if e.errno == errno.EINTR:
                if expires is not None and monotonic() > expires:
                    raise OSError(errno=errno.ETIMEDOUT)
                continue
            raise
    return result


SelectorKey = namedtuple('SelectorKey', ['fileobj', 'fd', 'events', 'data'])


class _SelectorMapping(Mapping):
    """ Mapping of file objects to selector keys """

    def __init__(self, selector):
        self._selector = selector

    def __len__(self):
        return len(self._selector._fd_to_key)

    def __getitem__(self, fileobj):
        try:
            fd = self._selector._fileobj_lookup(fileobj)
            return self._selector._fd_to_key[fd]
        except KeyError:
            raise KeyError("{0!r} is not registered.".format(fileobj))

    def __iter__(self):
        return iter(self._selector._fd_to_key)


class BaseSelector:
    """ Abstract Selector class

    A select supports registering file objects to be monitored
    for specific I/O events.

    A file object is a file descriptor or any object with a
    `fileno()` method. An arbitrary object can be attaced to the
    file object which can be used for example to store context info,
    a callback, etc.

    A selector can use various implementations (select(), poll(), epoll(),
    and kqueue()) depending on the platform. The 'DefaultSelector' class uses
    the most efficient implementation for the current platform.
    """
    def __init__(self):
        # Maps file descriptors to keys.
        self._fd_to_key = {}

        # Read-only mapping returned by get_map()
        self._map = _SelectorMapping(self)

    def _fileobj_lookup(self, fileobj):
        """ Return a file descriptor from a file object.
        This wraps _fileobj_to_fd() to do an exhaustive
        search in case the object is invalid but we still
        have it in our map. Used by unregister() so we can
        unregister an object that was previously registered
        even if it is closed. It is also used by _SelectorMapping
        """
        try:
            return _fileobj_to_fd(fileobj)
        except ValueError:

            # Search through all our mapped keys.
            for key in self._fd_to_key.values():
                if key.fileobj is fileobj:
                    return key.fd

            # Raise ValueError after all
            raise

    def register(self, fileobj, events, data=None):
        """ Register a file object for a set of events to monitor. """
        if (not events) or (events & ~(EVENT_READ | EVENT_WRITE)):
            raise ValueError("Invalid events: {0!r}".format(events))

        key = SelectorKey(fileobj, self._fileobj_lookup(fileobj), events, data)

        if key.fd in self._fd_to_key:
            raise KeyError("{0!r} (FD {1}) is already registered"
                           .format(fileobj, key.fd))

        self._fd_to_key[key.fd] = key
        return key

    def unregister(self, fileobj):
        """ Unregister a file object from being monitored. """
        try:
            key = self._fd_to_key.pop(self._fileobj_lookup(fileobj))
        except KeyError:
            raise KeyError("{0!r} is not registered".format(fileobj))
        return key

    def modify(self, fileobj, events, data=None):
        """ Change a registered file object monitored events and data. """
        # NOTE: Some subclasses optimize this operation even further.
        try:
            key = self._fd_to_key[self._fileobj_lookup(fileobj)]
        except KeyError:
            raise KeyError("{0!r} is not registered".format(fileobj))

        if events != key.events:
            self.unregister(fileobj)
            key = self.register(fileobj, events, data)

        elif data != key.data:
            # Use a shortcut to update the data.
            key = key._replace(data=data)
            self._fd_to_key[key.fd] = key

        return key

    def select(self, timeout=None):
        """ Perform the actual selection until soime monitored file objects
        are ready or the timeout expires. """
        raise NotImplementedError()

    def close(self):
        """ Close the selector. This must be called to insure that all
        underlying resources are freed. """
        self._fd_to_key.clear()
        self._map = None

    def get_key(self, fileobj):
        """ Return the key associated with a registered file object. """
        mapping = self.get_map()
        if mapping is None:
            raise RuntimeError("Selector is closed")
        try:
            return mapping[fileobj]
        except KeyError:
            raise KeyError("{0!r} is not registered".format(fileobj))

    def get_map(self):
        """ Return a mapping of file objects to selector keys """
        return self._map

    def _key_from_fd(self, fd):
        """ Return the key associated to a given file descriptor
         Return None if it is not found. """
        try:
            return self._fd_to_key[fd]
        except KeyError:
            return None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


if hasattr(select, "select"):
    class SelectSelector(BaseSelector):
        """ Select-based selector. """
        def __init__(self):
            super(SelectSelector, self).__init__()
            self._readers = set()
            self._writers = set()

        def register(self, fileobj, events, data=None):
            key = super(SelectSelector, self).register(fileobj, events, data)
            if events & EVENT_READ:
                self._readers.add(key.fd)
            if events & EVENT_WRITE:
                self._writers.add(key.fd)
            return key

        def unregister(self, fileobj):
            key = super(SelectSelector, self).unregister(fileobj)
            self._readers.discard(key.fd)
            self._writers.discard(key.fd)
            return key

        def select(self, timeout=None):
            timeout = None if timeout is None else max(timeout, 0.0)
            ready = []
            r, w, _ = _syscall_wrapper(select.select, timeout,
                                self._readers, self._writers, [], timeout)
            r = set(r)
            w = set(w)
            for fd in r | w:
                events = 0
                if fd in r:
                    events |= EVENT_READ
                if fd in w:
                    events |= EVENT_WRITE

                key = self._key_from_fd(fd)
                if key:
                    ready.append((key, events & key.events))
            return ready


# Choose the best implementation, roughly:
# kqueue == epoll > poll > select. Devpoll not supported. (See above)
# select() also can't accept a FD > FD_SETSIZE (usually around 1024)
if 'KqueueSelector' in globals():
    DefaultSelector = KqueueSelector
elif 'EpollSelector' in globals():
    DefaultSelector = EpollSelector
elif 'PollSelector' in globals():
    DefaultSelector = PollSelector
elif 'SelectSelector' in globals():
    DefaultSelector = SelectSelector
else:
    def no_selector():
        raise ValueError("Platform does not have a selector")
    DefaultSelector = no_selector
    HAS_SELECT = False

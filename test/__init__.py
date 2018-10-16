import warnings
import sys
import errno
import functools
import logging
import socket

import pytest

from urllib3.exceptions import HTTPWarning
from urllib3.packages import six
from urllib3.util import ssl_

# We need a host that will not immediately close the connection with a TCP
# Reset. SO suggests this hostname
TARPIT_HOST = '10.255.255.1'

# (Arguments for socket, is it IPv6 address?)
VALID_SOURCE_ADDRESSES = [(('::1', 0), True), (('127.0.0.1', 0), False)]
# RFC 5737: 192.0.2.0/24 is for testing only.
# RFC 3849: 2001:db8::/32 is for documentation only.
INVALID_SOURCE_ADDRESSES = [('192.0.2.255', 0), ('2001:db8::1', 0)]


def clear_warnings(cls=HTTPWarning):
    new_filters = []
    for f in warnings.filters:
        if issubclass(f[2], cls):
            continue
        new_filters.append(f)
    warnings.filters[:] = new_filters


def setUp():
    clear_warnings()
    warnings.simplefilter('ignore', HTTPWarning)


def onlyPy279OrNewer(test):
    """Skips this test unless you are on Python 2.7.9 or later."""

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        msg = "{name} requires Python 2.7.9+ to run".format(name=test.__name__)
        if sys.version_info < (2, 7, 9):
            pytest.skip(msg)
        return test(*args, **kwargs)
    return wrapper


def onlyPy2(test):
    """Skips this test unless you are on Python 2.x"""

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        msg = "{name} requires Python 2.x to run".format(name=test.__name__)
        if six.PY3:
            pytest.skip(msg)
        return test(*args, **kwargs)
    return wrapper


def onlyPy3(test):
    """Skips this test unless you are on Python3.x"""

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        msg = "{name} requires Python3.x to run".format(name=test.__name__)
        if not six.PY3:
            pytest.skip(msg)
        return test(*args, **kwargs)
    return wrapper


def notSecureTransport(test):
    """Skips this test when SecureTransport is in use."""

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        msg = "{name} does not run with SecureTransport".format(name=test.__name__)
        if ssl_.IS_SECURETRANSPORT:
            pytest.skip(msg)
        return test(*args, **kwargs)
    return wrapper


_requires_network_has_route = None


def requires_network(test):
    """Helps you skip tests that require the network"""

    def _is_unreachable_err(err):
        return getattr(err, 'errno', None) in (errno.ENETUNREACH,
                                               errno.EHOSTUNREACH)  # For OSX

    def _has_route():
        try:
            sock = socket.create_connection((TARPIT_HOST, 80), 0.0001)
            sock.close()
            return True
        except socket.timeout:
            return True
        except socket.error as e:
            if _is_unreachable_err(e):
                return False
            else:
                raise

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        global _requires_network_has_route

        if _requires_network_has_route is None:
            _requires_network_has_route = _has_route()

        if _requires_network_has_route:
            return test(*args, **kwargs)
        else:
            msg = "Can't run {name} because the network is unreachable".format(
                name=test.__name__)
            pytest.skip(msg)
    return wrapper


class _ListHandler(logging.Handler):
    def __init__(self):
        super(_ListHandler, self).__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class LogRecorder(object):
    def __init__(self, target=logging.root):
        super(LogRecorder, self).__init__()
        self._target = target
        self._handler = _ListHandler()

    @property
    def records(self):
        return self._handler.records

    def install(self):
        self._target.addHandler(self._handler)

    def uninstall(self):
        self._target.removeHandler(self._handler)

    def __enter__(self):
        self.install()
        return self.records

    def __exit__(self, exc_type, exc_value, traceback):
        self.uninstall()
        return False

import contextlib
import errno
import functools
import socket
import sys
import warnings

from nose.plugins.skip import SkipTest

from urllib3.exceptions import MaxRetryError, HTTPWarning
from urllib3.packages import six

VALID_SOURCE_ADDRESSES = [('::1', 0), ('127.0.0.1', 0)]
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


def onlyPy26OrOlder(test):
    """Skips this test unless you are on Python2.6.x or earlier."""

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        msg = "{name} only runs on Python2.6.x or older".format(name=test.__name__)
        if sys.version_info >= (2, 7):
            raise SkipTest(msg)
        return test(*args, **kwargs)
    return wrapper

def onlyPy27OrNewer(test):
    """Skips this test unless you are on Python 2.7.x or later."""

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        msg = "{name} requires Python 2.7.x+ to run".format(name=test.__name__)
        if sys.version_info < (2, 7):
            raise SkipTest(msg)
        return test(*args, **kwargs)
    return wrapper

def onlyPy3(test):
    """Skips this test unless you are on Python3.x"""

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        msg = "{name} requires Python3.x to run".format(name=test.__name__)
        if not six.PY3:
            raise SkipTest(msg)
        return test(*args, **kwargs)
    return wrapper

def requires_network(test):
    """Helps you skip tests that require the network"""

    def _is_unreachable_err(err):
        return getattr(err, 'errno', None) in (errno.ENETUNREACH,
                                               errno.EHOSTUNREACH) # For OSX

    @functools.wraps(test)
    def wrapper(*args, **kwargs):
        msg = "Can't run {name} because the network is unreachable".format(
            name=test.__name__)
        try:
            return test(*args, **kwargs)
        except socket.error as e:
            # This test needs an initial network connection to attempt the
            # connection to the TARPIT_HOST. This fails if you are in a place
            # without an Internet connection, so we skip the test in that case.
            if _is_unreachable_err(e):
                raise SkipTest(msg)
            raise
        except MaxRetryError as e:
            if _is_unreachable_err(e.reason):
                raise SkipTest(msg)
            raise
    return wrapper

class MockSocket(socket.socket):
    def connect(self, *args):
        raise socket.timeout('timed out')

@contextlib.contextmanager
def mocked_socket_module():
    """Return a socket which times out on connect.

    This is borrowed from test_socket in the CPython standard library. Use this
    to mock a connection that times out.
    """
    old_socket = socket.socket
    socket.socket = MockSocket
    try:
        yield
    finally:
        socket.socket = old_socket

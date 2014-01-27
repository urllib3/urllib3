import errno
import functools
import socket

from nose.plugins.skip import SkipTest

from urllib3.exceptions import MaxRetryError


def requires_network(test):
    """Helps you skip tests that require the network"""

    def _is_unreachable_err(err):
        return hasattr(err, 'errno') and err.errno == errno.ENETUNREACH

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
            if (isinstance(e.reason, socket.error) and
                _is_unreachable_err(e.reason)):
                raise SkipTest(msg)
            raise
    return wrapper

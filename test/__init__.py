import errno
import functools
import socket
import unittest

from nose.plugins.skip import SkipTest

from urllib3.exceptions import MaxRetryError
from urllib3.packages import six
from urllib3.util import base_ssl

import backports.ssl as backports_ssl # this will be vendored soon


def multi_ssl():
    def inner(cls):
        cls.__test__ = False

        def get_impl(name, impl):
            class TestImpl(cls):
                __test__ = True
                ssl = impl
            TestImpl.__name__ = '%s_%s' % (cls.__name__, name)
            if not hasattr(impl, 'wrap_socket'):
                TestImpl = unittest.skip('SSL implementation unavailable')(TestImpl)
            return TestImpl

        cls.ssl_impls = [
            get_impl('BaseSSL', base_ssl),
            get_impl('BackportsSSL', backports_ssl),
        ]
        return cls
    return inner

def onlyPY3(test):
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
            if (isinstance(e.reason, socket.error) and
                _is_unreachable_err(e.reason)):
                raise SkipTest(msg)
            raise
    return wrapper

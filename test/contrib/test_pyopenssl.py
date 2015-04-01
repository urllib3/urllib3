from nose.plugins.skip import SkipTest
from urllib4.packages import six

if six.PY3:
    raise SkipTest('Testing of PyOpenSSL disabled on PY3')

try:
    from urllib4.contrib.pyopenssl import (inject_into_urllib4,
                                           extract_from_urllib4)
except ImportError as e:
    raise SkipTest('Could not import PyOpenSSL: %r' % e)


from ..with_dummyserver.test_https import TestHTTPS, TestHTTPS_TLSv1
from ..with_dummyserver.test_socketlevel import TestSNI, TestSocketClosing


def setup_module():
    inject_into_urllib4()


def teardown_module():
    extract_from_urllib4()

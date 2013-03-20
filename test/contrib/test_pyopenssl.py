try:
    from urllib3.contrib.pyopenssl import (inject_into_urllib3,
                                           extract_from_urllib3)
except ImportError as e:
    from nose.plugins.skip import SkipTest
    raise SkipTest('Could not import pyopenssl: %r' % e)

from ..with_dummyserver.test_https import TestHTTPS, TestHTTPS_TLSv1
from ..with_dummyserver.test_socketlevel import TestSNI, TestSocketClosing


def setup_module():
    inject_into_urllib3()


def teardown_module():
    extract_from_urllib3()

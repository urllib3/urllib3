# -*- coding: utf-8 -*-
import pytest

try:
    from urllib3.contrib.securetransport import (inject_into_urllib3,
                                                 extract_from_urllib3)
    HAS_SECURETRANSPORT = True
except ImportError as e:
    HAS_SECURETRANSPORT = False

from ..with_dummyserver.test_https import TestHTTPS, TestHTTPS_TLSv1  # noqa: F401
from ..with_dummyserver.test_socketlevel import (  # noqa: F401
    TestSNI, TestSocketClosing, TestClientCerts
)


def setup_module(module):
    if not HAS_SECURETRANSPORT:
        pytest.skip('Tests require SecureTransport.')
    inject_into_urllib3()


def teardown_module(module):
    extract_from_urllib3()

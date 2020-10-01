# -*- coding: utf-8 -*-
import contextlib
import inspect
import socket
import ssl

import mock
import pytest

try:
    from urllib3.contrib.securetransport import WrappedSocket
except ImportError:
    pass

from .socketsig_helper import socket_signature_validators


def setup_module():
    try:
        from urllib3.contrib.securetransport import inject_into_urllib3

        inject_into_urllib3()
    except ImportError as e:
        pytest.skip("Could not import SecureTransport: %r" % e)


def teardown_module():
    try:
        from urllib3.contrib.securetransport import extract_from_urllib3

        extract_from_urllib3()
    except ImportError:
        pass


from ..test_util import TestUtilSSL  # noqa: E402, F401

# SecureTransport does not support TLSv1.3
# https://github.com/urllib3/urllib3/issues/1674
from ..with_dummyserver.test_https import TestHTTPS  # noqa: E402, F401
from ..with_dummyserver.test_https import (
    TestHTTPS_TLSv1,
    TestHTTPS_TLSv1_1,
    TestHTTPS_TLSv1_2,
)
from ..with_dummyserver.test_socketlevel import (  # noqa: E402, F401
    TestClientCerts,
    TestSNI,
    TestSocketClosing,
    TestSSL,
)


def test_no_crash_with_empty_trust_bundle():
    with contextlib.closing(socket.socket()) as s:
        ws = WrappedSocket(s)
        with pytest.raises(ssl.SSLError):
            ws._custom_validate(True, b"")


def test_socket_signature():
    """
    Check WrappedSocket methods match corresponding socket.socket
    method signatures.
    """
    with contextlib.closing(socket.socket()) as sock:
        validators = socket_signature_validators()
        wrapper = WrappedSocket(sock)

        # iterate through all WrappedSocket methods and check
        # the ones that override socket.socket (heuristic: same
        # name but don't start with an underscore)
        for name, method in inspect.getmembers(wrapper, inspect.ismethod):
            if name.startswith("_"):
                continue
            if not hasattr(sock, name):
                continue

            # test fails here if WrappedSocket defines overrides
            # socket.socket but there is no corresponding validator
            # defined in sockesig_helper
            assert name in validators

            print("Check function signature: WrappedSocket.{}".format(name))

            # the trick here is to avoid calling WrappedSocket
            # method directly because we don't have a proper
            # fixture. Instead create a mock with the same signature
            # (autospec) and call the validator on it.
            setattr(wrapper, name, mock.create_autospec(getattr(wrapper, name)))
            for counter, m_call in enumerate(
                [m for group in validators[name] for m in group]
            ):
                print("    WrappedSocket.{} test call #{}".format(name, counter))

                # test fails here if WrapperSocket method does
                # not match socket.socket method signature
                m_call(wrapper)

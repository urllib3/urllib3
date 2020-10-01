# -*- coding: utf-8 -*-
import contextlib
import inspect
import os
import socket

import mock
import pytest

from .socketsig_helper import socket_signature_validators

try:
    from cryptography import x509
    from OpenSSL.crypto import FILETYPE_PEM, load_certificate

    from urllib3.contrib.pyopenssl import (
        WrappedSocket,
        _dnsname_to_stdlib,
        get_subj_alt_name,
    )
except ImportError:
    pass


def setup_module():
    try:
        from urllib3.contrib.pyopenssl import inject_into_urllib3

        inject_into_urllib3()
    except ImportError as e:
        pytest.skip("Could not import PyOpenSSL: %r" % e)


def teardown_module():
    try:
        from urllib3.contrib.pyopenssl import extract_from_urllib3

        extract_from_urllib3()
    except ImportError:
        pass


from ..test_util import TestUtilSSL  # noqa: E402, F401
from ..with_dummyserver.test_https import (  # noqa: E402, F401
    TestHTTPS,
    TestHTTPS_IPSAN,
    TestHTTPS_IPv6Addr,
    TestHTTPS_IPV6SAN,
    TestHTTPS_NoSAN,
    TestHTTPS_TLSv1,
    TestHTTPS_TLSv1_1,
    TestHTTPS_TLSv1_2,
    TestHTTPS_TLSv1_3,
)
from ..with_dummyserver.test_socketlevel import (  # noqa: E402, F401
    TestClientCerts,
    TestSNI,
    TestSocketClosing,
    TestSSL,
)


class TestPyOpenSSLHelpers(object):
    """
    Tests for PyOpenSSL helper functions.
    """

    def test_dnsname_to_stdlib_simple(self):
        """
        We can convert a dnsname to a native string when the domain is simple.
        """
        name = u"उदाहरण.परीक"
        expected_result = "xn--p1b6ci4b4b3a.xn--11b5bs8d"

        assert _dnsname_to_stdlib(name) == expected_result

    def test_dnsname_to_stdlib_leading_period(self):
        """
        If there is a . in front of the domain name we correctly encode it.
        """
        name = u".उदाहरण.परीक"
        expected_result = ".xn--p1b6ci4b4b3a.xn--11b5bs8d"

        assert _dnsname_to_stdlib(name) == expected_result

    def test_dnsname_to_stdlib_leading_splat(self):
        """
        If there's a wildcard character in the front of the string we handle it
        appropriately.
        """
        name = u"*.उदाहरण.परीक"
        expected_result = "*.xn--p1b6ci4b4b3a.xn--11b5bs8d"

        assert _dnsname_to_stdlib(name) == expected_result

    @mock.patch("urllib3.contrib.pyopenssl.log.warning")
    def test_get_subj_alt_name(self, mock_warning):
        """
        If a certificate has two subject alternative names, cryptography raises
        an x509.DuplicateExtension exception.
        """
        path = os.path.join(os.path.dirname(__file__), "duplicate_san.pem")
        with open(path, "r") as fp:
            cert = load_certificate(FILETYPE_PEM, fp.read())

        assert get_subj_alt_name(cert) == []

        assert mock_warning.call_count == 1
        assert isinstance(mock_warning.call_args[0][1], x509.DuplicateExtension)

    def test_socket_signature(self):
        """
        Check WrappedSocket methods match corresponding socket.socket
        method signatures.
        """
        with contextlib.closing(socket.socket()) as sock:
            validators = socket_signature_validators()
            wrapper = WrappedSocket(None, sock)

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

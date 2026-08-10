from __future__ import annotations

import os
import ssl
from unittest import mock

import pytest

try:
    from cryptography import x509
    from OpenSSL.crypto import FILETYPE_PEM, load_certificate

    from urllib3.contrib.pyopenssl import _dnsname_to_stdlib, get_subj_alt_name
except ImportError:
    pass


def setup_module() -> None:
    try:
        from urllib3.contrib.pyopenssl import inject_into_urllib3

        inject_into_urllib3()
    except ImportError as e:
        pytest.skip(f"Could not import PyOpenSSL: {e!r}")


def teardown_module() -> None:
    try:
        from urllib3.contrib.pyopenssl import extract_from_urllib3

        extract_from_urllib3()
    except ImportError:
        pass


from ..test_ssl import TestSSL  # noqa: E402, F401
from ..test_util import TestUtilSSL  # noqa: E402, F401
from ..with_dummyserver.test_https import (  # noqa: E402, F401
    TestHTTPS_IPV4SAN,
    TestHTTPS_IPV6SAN,
    TestHTTPS_TLSv1,
    TestHTTPS_TLSv1_1,
    TestHTTPS_TLSv1_2,
    TestHTTPS_TLSv1_3,
)
from ..with_dummyserver.test_socketlevel import (  # noqa: E402, F401
    TestClientCerts,
    TestSNI,
    TestSocketClosing,
)
from ..with_dummyserver.test_socketlevel import (  # noqa: E402, F401
    TestSSL as TestSocketSSL,
)


class TestPyOpenSSLContextReuse:
    """
    Regression tests for issue #5107: ``PyOpenSSLContext.wrap_socket`` must
    not crash on the second connection from a single pool. pyOpenSSL's
    ``OpenSSL.SSL.Context`` is single-use: once a ``Connection`` has been
    created from it, the same context cannot be reused. The wrapper has to
    rebuild a fresh underlying context with the user's customisations so
    the second connection succeeds.
    """

    def _make_fake_sock(self):
        from socket import socket

        s = socket()
        s.settimeout(0.01)
        return s

    def test_wrap_socket_rebuilds_ctx_on_reuse(self) -> None:
        """
        Second ``wrap_socket`` call triggers a context rebuild and
        succeeds even when the underlying pyOpenSSL context has been
        marked as used.
        """
        from unittest import mock

        import OpenSSL.SSL

        from urllib3.contrib.pyopenssl import PyOpenSSLContext

        ctx = PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")

        real_connection = OpenSSL.SSL.Connection
        # Capture the original underlying context so we can detect
        # when the wrapper passes the SAME spent context back to
        # ``OpenSSL.SSL.Connection`` (which is what the wrapper is
        # supposed to detect and rebuild around).
        original_ctx = ctx._ctx

        # Pretend pyOpenSSL's Context is single-use: re-using the
        # same underlying context for a second ``Connection`` raises
        # the exact error reported in #5107. After the wrapper
        # rebuilds, the new context is different, so the second
        # ``Connection`` call must succeed.
        def fake_connection(c, sock, *args, **kwargs):
            if c is original_ctx and getattr(ctx, "_ctx_used", False):
                raise ValueError(
                    "Context has already been used to create a Connection, "
                    "it cannot be mutated again"
                )
            conn = real_connection(c, sock, *args, **kwargs)
            # Stub the handshake to avoid hitting a real network — the
            # point of the test is the Connection construction path,
            # not the TLS handshake.
            conn.do_handshake = mock.Mock()  # type: ignore[method-assign]
            return conn

        with mock.patch.object(OpenSSL.SSL, "Connection", side_effect=fake_connection):
            ctx.wrap_socket(self._make_fake_sock())  # first
            ctx.wrap_socket(self._make_fake_sock())  # second - must not crash

        assert ctx._ctx_used is True
        # The underlying context must have been replaced after the
        # second call.
        assert ctx._ctx is not original_ctx

    def test_rebuild_ctx_preserves_customisations(self) -> None:
        """
        ``_rebuild_ctx`` must replay every customisation the user set
        on the wrapper so the second connection keeps the same TLS
        profile as the first.
        """
        from urllib3.contrib.pyopenssl import PyOpenSSLContext

        ctx = PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.set_alpn_protocols(["h2", "http/1.1"])
        ctx.set_default_verify_paths()

        rebuilt = ctx._rebuild_ctx()

        # The rebuilt context is a fresh OpenSSL.Context, not the
        # original instance.
        assert rebuilt is not ctx._ctx
        # Verify mode and protocol are applied.
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx._verify_mode_value == ssl.CERT_REQUIRED
        # ALPN is replayed.
        assert ctx._alpn_protocols == ["h2", "http/1.1"]
        # Ciphers are stored.
        assert ctx._ciphers == b"DEFAULT@SECLEVEL=1"
        # Default verify paths flag is set.
        assert ctx._default_verify_paths_set is True


class TestPyOpenSSLHelpers:
    """
    Tests for PyOpenSSL helper functions.
    """

    def test_dnsname_to_stdlib_simple(self) -> None:
        """
        We can convert a dnsname to a native string when the domain is simple.
        """
        name = "उदाहरण.परीक"
        expected_result = "xn--p1b6ci4b4b3a.xn--11b5bs8d"

        assert _dnsname_to_stdlib(name) == expected_result

    def test_dnsname_to_stdlib_leading_period(self) -> None:
        """
        If there is a . in front of the domain name we correctly encode it.
        """
        name = ".उदाहरण.परीक"
        expected_result = ".xn--p1b6ci4b4b3a.xn--11b5bs8d"

        assert _dnsname_to_stdlib(name) == expected_result

    def test_dnsname_to_stdlib_leading_splat(self) -> None:
        """
        If there's a wildcard character in the front of the string we handle it
        appropriately.
        """
        name = "*.उदाहरण.परीक"
        expected_result = "*.xn--p1b6ci4b4b3a.xn--11b5bs8d"

        assert _dnsname_to_stdlib(name) == expected_result

    @mock.patch("urllib3.contrib.pyopenssl.log.warning")
    def test_get_subj_alt_name(self, mock_warning: mock.MagicMock) -> None:
        """
        If a certificate has two subject alternative names, cryptography raises
        an x509.DuplicateExtension exception.
        """
        path = os.path.join(os.path.dirname(__file__), "duplicate_san.pem")
        with open(path, "rb") as fp:
            cert = load_certificate(FILETYPE_PEM, fp.read())

        assert get_subj_alt_name(cert) == []

        assert mock_warning.call_count == 1
        assert isinstance(mock_warning.call_args[0][1], x509.DuplicateExtension)

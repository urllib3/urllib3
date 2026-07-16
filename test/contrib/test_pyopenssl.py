from __future__ import annotations

import os
from unittest import mock

import pytest

try:
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from OpenSSL.crypto import FILETYPE_PEM, load_certificate

    from urllib3.contrib.pyopenssl import (
        _common_name,
        _dnsname_to_stdlib,
        get_subj_alt_name,
    )
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

    def _make_cert(self, common_name: str | None) -> Any:
        """
        Builds a minimal, self-signed, in-memory certificate for exercising
        _common_name(), optionally with no commonName attribute at all.
        """
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
            if common_name is not None
            else []
        )
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        return load_certificate(FILETYPE_PEM, cert.public_bytes(Encoding.PEM))

    def test_common_name(self) -> None:
        """
        _common_name() reads the commonName off a certificate's subject via
        cryptography's X.509 API, without going through the pyOpenSSL
        get_subject() API deprecated in pyOpenSSL 26.3.0.
        """
        cert = self._make_cert("example.com")
        assert _common_name(cert) == "example.com"

    def test_common_name_missing(self) -> None:
        """
        _common_name() returns None for a certificate with no commonName,
        matching the previous get_subject().CN behaviour.
        """
        cert = self._make_cert(None)
        assert _common_name(cert) is None

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

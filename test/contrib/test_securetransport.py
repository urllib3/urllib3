from __future__ import annotations

import base64
import contextlib
import socket
import ssl

import pytest

try:
    from urllib3.contrib.securetransport import WrappedSocket
except ImportError:
    pass


def setup_module() -> None:
    try:
        from urllib3.contrib.securetransport import inject_into_urllib3

        inject_into_urllib3()
    except ImportError as e:
        pytest.skip(f"Could not import SecureTransport: {repr(e)}")


def teardown_module() -> None:
    try:
        from urllib3.contrib.securetransport import extract_from_urllib3

        extract_from_urllib3()
    except ImportError:
        pass


from ..test_util import TestUtilSSL  # noqa: E402, F401

# SecureTransport does not support TLSv1.3
# https://github.com/urllib3/urllib3/issues/1674
from ..with_dummyserver.test_https import (  # noqa: E402, F401
    TestHTTPS,
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


def test_no_crash_with_empty_trust_bundle() -> None:
    with contextlib.closing(socket.socket()) as s:
        ws = WrappedSocket(s)
        with pytest.raises(ssl.SSLError):
            ws._custom_validate(True, b"")


def test_no_crash_with_invalid_trust_bundle() -> None:
    invalid_cert = base64.b64encode(b"invalid-cert")
    cert_bundle = (
        b"-----BEGIN CERTIFICATE-----\n" + invalid_cert + b"\n-----END CERTIFICATE-----"
    )

    with contextlib.closing(socket.socket()) as s:
        ws = WrappedSocket(s)
        with pytest.raises(ssl.SSLError):
            ws._custom_validate(True, cert_bundle)

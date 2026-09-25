from __future__ import annotations

import os
import ssl
import threading
from unittest import mock

import pytest

try:
    import OpenSSL.SSL
    from cryptography import x509
    from OpenSSL.crypto import FILETYPE_PEM, load_certificate

    from urllib3.contrib.pyopenssl import (
        _PYOPENSSL_CONTEXT_IS_IMMUTABLE,
        PyOpenSSLContext,
        _dnsname_to_stdlib,
        get_subj_alt_name,
    )
    from urllib3.util import ssl_ as ssl_util
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

from ..with_dummyserver.test_socketlevel import (  # noqa: E402, F401  # isort: skip
    TestClientCerts,
    TestSNI,
    TestSSL as TestSocketSSL,
    TestSocketClosing,
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


class TestPyOpenSSLContext:
    def context(self) -> PyOpenSSLContext:
        return PyOpenSSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def configuration(self) -> ssl_util._SSLContextConfig:
        return ssl_util._SSLContextConfig(
            cert_reqs=ssl.CERT_REQUIRED,
            ca_certs=None,
            ca_cert_dir=None,
            ca_cert_data=None,
            certfile=None,
            keyfile=None,
            key_password=None,
            load_default_certs=False,
            alpn_protocols=("http/1.1",),
        )

    @pytest.mark.skipif(
        not _PYOPENSSL_CONTEXT_IS_IMMUTABLE,
        reason="requires immutable pyOpenSSL contexts",
    )
    def test_same_configuration_is_set_up_once(self) -> None:
        context = self.context()
        configuration = self.configuration()

        with (
            mock.patch(
                "urllib3.util.ssl_._configure_context",
                wraps=ssl_util._configure_context,
            ) as configure_context,
            mock.patch.object(context, "_wrap_socket", return_value=mock.sentinel.sock),
        ):
            first = context._urllib3_wrap_socket(
                None, None, configuration  # type: ignore[arg-type]
            )
            second = context._urllib3_wrap_socket(
                None, None, configuration  # type: ignore[arg-type]
            )

        assert first is mock.sentinel.sock
        assert second is mock.sentinel.sock
        configure_context.assert_called_once_with(context, configuration)

    @pytest.mark.skipif(
        not _PYOPENSSL_CONTEXT_IS_IMMUTABLE,
        reason="requires immutable pyOpenSSL contexts",
    )
    def test_different_configuration_is_rejected(self) -> None:
        context = self.context()
        first_configuration = self.configuration()
        second_configuration = first_configuration._replace(cert_reqs=ssl.CERT_NONE)

        with (
            mock.patch(
                "urllib3.util.ssl_._configure_context",
                wraps=ssl_util._configure_context,
            ) as configure_context,
            mock.patch.object(context, "_wrap_socket", return_value=mock.sentinel.sock),
        ):
            context._urllib3_wrap_socket(
                None, None, first_configuration  # type: ignore[arg-type]
            )
            with pytest.raises(ValueError, match="different urllib3 TLS configuration"):
                context._urllib3_wrap_socket(
                    None, None, second_configuration  # type: ignore[arg-type]
                )

        configure_context.assert_called_once_with(context, first_configuration)

    @pytest.mark.skipif(
        not _PYOPENSSL_CONTEXT_IS_IMMUTABLE,
        reason="requires immutable pyOpenSSL contexts",
    )
    def test_context_used_outside_urllib3_is_rejected(self) -> None:
        context = self.context()
        OpenSSL.SSL.Connection(context._ctx, None)

        with (
            mock.patch("urllib3.util.ssl_._configure_context") as configure_context,
            pytest.raises(ValueError, match="already used outside urllib3"),
        ):
            context._urllib3_wrap_socket(
                None,  # type: ignore[arg-type]
                None,
                self.configuration(),
            )

        configure_context.assert_not_called()

    def test_mutable_context_is_set_up_each_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        context = self.context()
        monkeypatch.setattr(context, "_urllib3_context_is_immutable", False)

        with (
            mock.patch(
                "urllib3.util.ssl_._configure_context",
                wraps=ssl_util._configure_context,
            ) as configure_context,
            mock.patch(
                "urllib3.util.ssl_._ssl_wrap_socket_impl",
                return_value=mock.sentinel.sock,
            ),
        ):
            ssl_util.ssl_wrap_socket(
                mock.Mock(), ssl_context=context  # type: ignore[call-overload]
            )
            ssl_util.ssl_wrap_socket(
                mock.Mock(), ssl_context=context  # type: ignore[call-overload]
            )

        assert configure_context.call_count == 2

    @pytest.mark.skipif(
        not _PYOPENSSL_CONTEXT_IS_IMMUTABLE,
        reason="requires immutable pyOpenSSL contexts",
    )
    def test_setup_and_connection_creation_are_atomic(self) -> None:
        context = self.context()
        configuration = self.configuration()
        setup_started = threading.Event()
        release_setup = threading.Event()
        second_finished = threading.Event()
        errors: list[BaseException] = []

        def setup(*_: object) -> None:
            setup_started.set()
            if not release_setup.wait(1):
                raise AssertionError("Timed out waiting to release context setup")

        def wrap(second: bool) -> None:
            try:
                context._urllib3_wrap_socket(
                    None, None, configuration  # type: ignore[arg-type]
                )
            except BaseException as e:
                errors.append(e)
            finally:
                if second:
                    second_finished.set()

        with (
            mock.patch("urllib3.util.ssl_._configure_context", side_effect=setup),
            mock.patch.object(context, "_wrap_socket", return_value=mock.sentinel.sock),
        ):
            first_thread = threading.Thread(target=wrap, args=(False,))
            second_thread = threading.Thread(target=wrap, args=(True,))
            first_thread.start()
            assert setup_started.wait(1)
            second_thread.start()
            assert not second_finished.wait(0.1)
            release_setup.set()
            first_thread.join(1)
            second_thread.join(1)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert errors == []

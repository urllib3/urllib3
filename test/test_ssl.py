import mock
import pytest
from urllib3.util import ssl_
from urllib3.exceptions import SNIMissingWarning


@pytest.mark.parametrize('addr', [
    '::1',
    '::',
    '127.0.0.1',
    '8.8.8.8',
    b'127.0.0.1'
])
def test_is_ipaddress_true(addr):
    assert ssl_.is_ipaddress(addr)


@pytest.mark.parametrize('addr', [
    'www.python.org',
    b'www.python.org'
])
def test_is_ipaddress_false(addr):
    assert not ssl_.is_ipaddress(addr)


@pytest.mark.parametrize(
    ['has_sni', 'server_hostname', 'uses_sni'],
    [(True, '127.0.0.1', False),
     (False, 'www.python.org', False),
     (False, '0.0.0.0', False),
     (True, 'www.google.com', True),
     (True, None, False),
     (False, None, False)]
)
def test_context_sni_with_ip_address(monkeypatch, has_sni, server_hostname, uses_sni):
    monkeypatch.setattr(ssl_, 'HAS_SNI', has_sni)

    sock = mock.Mock()
    context = mock.create_autospec(ssl_.SSLContext)

    ssl_.ssl_wrap_socket(sock, server_hostname=server_hostname, ssl_context=context)

    if uses_sni:
        context.wrap_socket.assert_called_with(sock, server_hostname=server_hostname)
    else:
        context.wrap_socket.assert_called_with(sock)


@pytest.mark.parametrize(
    ['has_sni', 'server_hostname', 'should_warn'],
    [(True, 'www.google.com', False),
     (True, '127.0.0.1', False),
     (False, '127.0.0.1', False),
     (False, 'www.google.com', True),
     (True, None, False),
     (False, None, False)]
)
def test_sni_missing_warning_with_ip_addresses(monkeypatch, has_sni, server_hostname, should_warn):
    monkeypatch.setattr(ssl_, 'HAS_SNI', has_sni)

    sock = mock.Mock()
    context = mock.create_autospec(ssl_.SSLContext)

    with mock.patch('warnings.warn') as warn:
        ssl_.ssl_wrap_socket(sock, server_hostname=server_hostname, ssl_context=context)

    if should_warn:
        assert warn.call_count >= 1
        warnings = [call[0][1] for call in warn.call_args_list]
        assert SNIMissingWarning in warnings
    else:
        assert warn.call_count == 0


@pytest.mark.parametrize(
    ["ciphers", "expected_ciphers"],
    [(None, ssl_.DEFAULT_CIPHERS),
     ("ECDH+AESGCM:ECDH+CHACHA20", "ECDH+AESGCM:ECDH+CHACHA20")]
)
def test_create_urllib3_context_set_ciphers(monkeypatch, ciphers, expected_ciphers):

    context = mock.create_autospec(ssl_.SSLContext)
    context.set_ciphers = mock.Mock()
    context.options = 0
    monkeypatch.setattr(ssl_, "SSLContext", lambda *_, **__: context)

    assert ssl_.create_urllib3_context(ciphers=ciphers) is context

    assert context.set_ciphers.call_count == 1
    assert context.set_ciphers.call_args == mock.call(expected_ciphers)

import pytest
from six import b
from urllib3.util import ssl_


@pytest.mark.parametrize('addr', [
    '::1',
    '::',
    '127.0.0.1',
    '8.8.8.8',
    b('127.0.0.1')
])
def test_is_ipaddress_true(addr):
    assert ssl_.is_ipaddress(addr)


@pytest.mark.parametrize('addr', [
    'www.python.org',
    b('www.python.org')
])
def test_is_ipaddress_false(addr):
    assert not ssl_.is_ipaddress(addr)

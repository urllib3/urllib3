import pytest

from urllib3.poolmanager import ProxyManager


class TestProxyManager(object):
    def test_proxy_headers(self):
        url = 'http://pypi.python.org/test'
        with ProxyManager('http://something:1234') as p:

            # Verify default headers
            default_headers = {'Accept': '*/*',
                               'Host': 'pypi.python.org'}
            headers = p._set_proxy_headers(url)

            assert headers == default_headers

            # Verify default headers don't overwrite provided headers
            provided_headers = {'Accept': 'application/json',
                                'custom': 'header',
                                'Host': 'test.python.org'}
            headers = p._set_proxy_headers(url, provided_headers)

            assert headers == provided_headers

            # Verify proxy with nonstandard port
            provided_headers = {'Accept': 'application/json'}
            expected_headers = provided_headers.copy()
            expected_headers.update({'Host': 'pypi.python.org:8080'})
            url_with_port = 'http://pypi.python.org:8080/test'
            headers = p._set_proxy_headers(url_with_port, provided_headers)

            assert headers == expected_headers

    def test_default_port(self):
        with ProxyManager('http://something') as p:
            assert p.proxy.port == 80
        with ProxyManager('https://something') as p:
            assert p.proxy.port == 443

    def test_invalid_scheme(self):
        with pytest.raises(AssertionError):
            ProxyManager('invalid://host/p')
        with pytest.raises(ValueError):
            ProxyManager('invalid://host/p')

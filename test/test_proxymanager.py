import unittest

from urllib3.poolmanager import ProxyManager


class TestProxyManager(unittest.TestCase):
    def test_proxy_headers(self):
        p = ProxyManager('http://something:1234')
        url = 'http://pypi.python.org/test'

        # Verify default headers
        default_headers = {'Accept': '*/*',
                           'Host': 'pypi.python.org'}
        headers = p._set_proxy_headers(url)

        self.assertEqual(headers, default_headers)

        # Verify default headers don't overwrite provided headers
        provided_headers = {'Accept': 'application/json',
                            'custom': 'header',
                            'Host': 'test.python.org'}
        headers = p._set_proxy_headers(url, provided_headers)

        self.assertEqual(headers, provided_headers)

        # Verify proxy with nonstandard port
        provided_headers = {'Accept': 'application/json'}
        expected_headers = provided_headers.copy()
        expected_headers.update({'Host': 'pypi.python.org:8080'})
        url_with_port = 'http://pypi.python.org:8080/test'
        headers = p._set_proxy_headers(url_with_port, provided_headers)

        self.assertEqual(headers, expected_headers)

    def test_default_port(self):
        p = ProxyManager('http://something')
        self.assertEqual(p.proxy.port, 80)
        p = ProxyManager('https://something')
        self.assertEqual(p.proxy.port, 443)

    def test_invalid_scheme(self):
        self.assertRaises(AssertionError, ProxyManager, 'invalid://host/p')
        self.assertRaises(ValueError, ProxyManager, 'invalid://host/p')


if __name__ == '__main__':
    unittest.main()

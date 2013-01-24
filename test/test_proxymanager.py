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

    def test_default_port(self):
        p = ProxyManager('http://something')
        self.assertEqual(p.proxy.port, 80)
        p = ProxyManager('https://something')
        self.assertEqual(p.proxy.port, 443)



if __name__ == '__main__':
    unittest.main()

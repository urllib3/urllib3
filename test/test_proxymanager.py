import unittest

from urllib3.poolmanager import ProxyManager


class TestProxyManager(unittest.TestCase):
    def test_proxy_headers(self):
        p = ProxyManager(None)

        # Verify default headers
        default_headers = {'Accept': '*/*'}
        headers = p._set_proxy_headers()

        self.assertEqual(headers, default_headers)

        # Verify default headers don't overwrite provided headers
        provided_headers = {'Accept': 'application/json', 'custom': 'header'}
        headers = p._set_proxy_headers(provided_headers)

        self.assertEqual(headers, provided_headers)

if __name__ == '__main__':
    unittest.main()

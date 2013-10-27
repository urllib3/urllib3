import unittest

from urllib3.poolmanager import ProxyManager


class TestProxyManager(unittest.TestCase):
    def test_default_port(self):
        p = ProxyManager('http://something')
        self.assertEqual(p.proxy.port, 80)
        p = ProxyManager('https://something')
        self.assertEqual(p.proxy.port, 443)


if __name__ == '__main__':
    unittest.main()

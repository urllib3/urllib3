import unittest

from urllib3.transport_security import parse_header, TransportSecurityManager, TransportSecurityStore


class TSMTest(unittest.TestCase):

    def test_parse_header(self):
        self.assertEqual(parse_header("foo=1; bar=a"), dict(foo="1", bar="a"))

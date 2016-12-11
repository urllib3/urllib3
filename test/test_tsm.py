import unittest

from urllib3.transport_security import parse_header, TransportSecurityManager, TransportSecurityStore


class TSMTest(unittest.TestCase):

    def test_parse_header(self):
        self.assertEqual(parse_header("foo=1"), [("foo", "1")])
        self.assertEqual(parse_header(" foo=1;  "), [("foo", "1")])
        self.assertEqual(parse_header("foo=1 ;  bar=a "), [("foo", "1"), ("bar", "a")])
        self.assertEqual(parse_header("foo=1; bar"), [("foo", "1"), ("bar", None)])
        self.assertEqual(parse_header('''max-age=2592000;
        pin-sha256="E9CZ9INDbd+2eRQozYqqbQ2yXLVKB9+xcprMF+44U1g=";
        pin-sha256="LPJNul+wow4m6DsqxbninhsWHlwfp0JecwQzYpOLmCQ=";
        report-uri="http://example.com/pkp-report"'''),
                         [("max-age", "2592000"),
                          ("pin-sha256", "E9CZ9INDbd+2eRQozYqqbQ2yXLVKB9+xcprMF+44U1g="),
                          ("pin-sha256", "LPJNul+wow4m6DsqxbninhsWHlwfp0JecwQzYpOLmCQ="),
                          ("report-uri", "http://example.com/pkp-report")])
        self.assertEqual(parse_header("max-age=15768000 ; includeSubDomains"),
                         [("max-age", "15768000"), ("includeSubDomains", None)])
        self.assertRaises(IndexError, parse_header, None)

import unittest

from urllib3.transport_security import parse_header, TransportSecurityManager, TransportSecurityStore
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.response import HTTPResponse
from urllib3.exceptions import HSTSError
from urllib3.poolmanager import PoolManager


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

    def assert_hsts_on(self, tsm, domain):
        self.assertRaises(HSTSError, tsm.validate_hsts, HTTPConnection(domain))
        tsm.validate_hsts(HTTPSConnection(domain))

    def assert_hsts_off(self, tsm, domain):
        tsm.validate_hsts(HTTPConnection(domain))
        tsm.validate_hsts(HTTPSConnection(domain))

    def test_hsts(self):
        def HSTSResponse(value):
            return HTTPResponse(headers={"strict-transport-security": value})
        tsm = TransportSecurityManager()
        self.assert_hsts_off(tsm, "example.com")
        tsm.process_response(HTTPResponse(), HTTPSConnection("example.com"))

        # HSTS header over plain HTTP is ignored
        tsm.process_response(HSTSResponse("max-age=9000"), HTTPConnection("example.com"))
        self.assert_hsts_off(tsm, "example.com")

        # HSTS header over HTTPS is honored
        tsm.process_response(HSTSResponse("max-age=9000"), HTTPSConnection("example.com"))
        self.assert_hsts_on(tsm, "example.com")

        # Subdomains default to N/A
        self.assert_hsts_off(tsm, "subdomain.example.com")

        # Quoted HSTS header with subdomains directive and unrecognized directives is honored
        tsm.process_response(HSTSResponse('Max-Age="31536000"; IncludeSubDomains; preload'),
                             HTTPSConnection("example.com"))
        self.assert_hsts_on(tsm, "sub-domain.example.com")
        self.assert_hsts_on(tsm, "sub.subdomain.example.com")

        # Sibling and superdomains are unaffected
        self.assert_hsts_off(tsm, "com")
        self.assert_hsts_off(tsm, "example2.com")

        # Malformed HSTS headers are ignored
        for bad_header_value in ("foo bar", "xyz", "max-age=0; max-age=9000", "max-age='0'"):
            tsm.process_response(HSTSResponse(bad_header_value), HTTPSConnection("example.com"))
            self.assert_hsts_on(tsm, "example.com")

        # Zero max-age (remove) HSTS header is honored
        tsm.process_response(HSTSResponse("max-age=0"), HTTPSConnection("subdomain.example.com"))
        tsm.process_response(HSTSResponse("max-age=900"), HTTPSConnection("subdomain.example.com"))
        tsm.process_response(HSTSResponse("max-age=0"), HTTPSConnection("example.com"))
        self.assert_hsts_off(tsm, "example.com")
        self.assert_hsts_on(tsm, "subdomain.example.com")
        tsm.process_response(HSTSResponse("max-age=0"), HTTPSConnection("subdomain.example.com"))
        self.assert_hsts_off(tsm, "subdomain.example.com")

        # HSTS is ignored for IP addresses and non-dot-separated names
        for addr in ("2001:db8:85a3::8a2e:370:7334", "1.2.3.4", "example"):
            tsm.process_response(HSTSResponse("max-age=9000"), HTTPSConnection(addr))
            self.assert_hsts_off(tsm, addr)

        # Expired HSTS records are invalidated
        tsm.process_response(HSTSResponse("max-age=9000"), HTTPSConnection("example.com"))
        self.assert_hsts_on(tsm, "example.com")
        for record in tsm._tss._store.values():
            record["expires"] = 1
        self.assert_hsts_off(tsm, "example.com")

        # PoolManager automatically retries on HSTS error, rewrites ports per spec
        tsm = TransportSecurityManager()
        tsm.process_response(HSTSResponse("max-age=9000"), HTTPSConnection("example.com"))
        pm = PoolManager(transport_security_manager=tsm)
        pm.urlopen("GET", "http://example.com")
        self.assert_poolmanager_connected_to(pm, "https", "example.com", 443)
        pm = PoolManager(transport_security_manager=tsm)
        pm.urlopen("GET", "http://example.com:80")
        self.assert_poolmanager_connected_to(pm, "https", "example.com", 443)
        pm = PoolManager(transport_security_manager=tsm)
        pm.urlopen("GET", "http://example.com:443")
        self.assert_poolmanager_connected_to(pm, "https", "example.com", 443)

    def assert_poolmanager_connected_to(self, pm, scheme, host, port):
        self.assertTrue(any(pool_key.scheme == scheme and pool_key.host == host
                            and pool_key.port == port
                            for pool_key in pm.pools._container.keys()))

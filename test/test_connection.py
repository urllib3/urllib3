import unittest

import mock

from urllib3.connection import (
    CertificateError,
    VerifiedHTTPSConnection,
    _match_hostname,
)


class TestConnection(unittest.TestCase):
    """
    Tests in this suite should not make any network requests or connections.
    """
    def test_match_hostname_no_cert(self):
        cert = None
        asserted_hostname = 'foo'
        self.assertRaises(ValueError, _match_hostname, cert, asserted_hostname)

    def test_match_hostname_empty_cert(self):
        cert = {}
        asserted_hostname = 'foo'
        self.assertRaises(ValueError, _match_hostname, cert, asserted_hostname)

    def test_match_hostname_match(self):
        cert = {'subjectAltName': [('DNS', 'foo')]}
        asserted_hostname = 'foo'
        _match_hostname(cert, asserted_hostname)

    def test_match_hostname_mismatch(self):
        cert = {'subjectAltName': [('DNS', 'foo')]}
        asserted_hostname = 'bar'
        try:
            with mock.patch('urllib3.connection.log.error') as mock_log:
                _match_hostname(cert, asserted_hostname)
        except CertificateError as e:
            self.assertEqual(str(e), "hostname 'bar' doesn't match 'foo'")
            mock_log.assert_called_once_with(
                'Certificate did not match expected hostname: %s. '
                'Certificate: %s',
                'bar', {'subjectAltName': [('DNS', 'foo')]}
            )
            self.assertEqual(e._peer_cert, cert)


if __name__ == '__main__':
    unittest.main()

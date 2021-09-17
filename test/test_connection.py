import datetime

import mock
import pytest

from urllib3.connection import RECENT_DATE, CertificateError, _match_hostname


class TestConnection(object):
    """
    Tests in this suite should not make any network requests or connections.
    """

    def test_match_hostname_no_cert(self):
        cert = None
        asserted_hostname = "foo"
        with pytest.raises(ValueError):
            _match_hostname(cert, asserted_hostname)

    def test_match_hostname_empty_cert(self):
        cert = {}
        asserted_hostname = "foo"
        with pytest.raises(ValueError):
            _match_hostname(cert, asserted_hostname)

    def test_match_hostname_match(self):
        cert = {"subjectAltName": [("DNS", "foo")]}
        asserted_hostname = "foo"
        _match_hostname(cert, asserted_hostname)

    def test_match_hostname_mismatch(self):
        cert = {"subjectAltName": [("DNS", "foo")]}
        asserted_hostname = "bar"
        try:
            with mock.patch("urllib3.connection.log.warning") as mock_log:
                _match_hostname(cert, asserted_hostname)
        except CertificateError as e:
            assert "hostname 'bar' doesn't match 'foo'" in str(e)
            mock_log.assert_called_once_with(
                "Certificate did not match expected hostname: %s. Certificate: %s",
                "bar",
                {"subjectAltName": [("DNS", "foo")]},
            )
            assert e._peer_cert == cert

    def test_match_hostname_ip_address_ipv6(self):
        cert = {"subjectAltName": (("IP Address", "1:2::2:1"),)}
        asserted_hostname = "1:2::2:2"
        try:
            with mock.patch("urllib3.connection.log.warning") as mock_log:
                _match_hostname(cert, asserted_hostname)
        except CertificateError as e:
            assert "hostname '1:2::2:2' doesn't match '1:2::2:1'" in str(e)
            mock_log.assert_called_once_with(
                "Certificate did not match expected hostname: %s. Certificate: %s",
                "1:2::2:2",
                {"subjectAltName": (("IP Address", "1:2::2:1"),)},
            )
            assert e._peer_cert == cert

    def test_match_hostname_dns_with_brackets_doesnt_match(self):
        cert = {
            "subjectAltName": (
                ("DNS", "localhost"),
                ("IP Address", "localhost"),
            )
        }
        asserted_hostname = "[localhost]"
        with pytest.raises(CertificateError) as e:
            _match_hostname(cert, asserted_hostname)
        assert (
            "hostname '[localhost]' doesn't match either of 'localhost', 'localhost'"
            in str(e.value)
        )

    def test_match_hostname_ip_address_ipv6_brackets(self):
        cert = {"subjectAltName": (("IP Address", "1:2::2:1"),)}
        asserted_hostname = "[1:2::2:1]"
        # Assert no error is raised
        _match_hostname(cert, asserted_hostname)

    def test_recent_date(self):
        # This test is to make sure that the RECENT_DATE value
        # doesn't get too far behind what the current date is.
        # When this test fails update urllib3.connection.RECENT_DATE
        # according to the rules defined in that file.
        two_years = datetime.timedelta(days=365 * 2)
        assert RECENT_DATE > (datetime.datetime.today() - two_years).date()

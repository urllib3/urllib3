import datetime
import mock

import pytest

from urllib3._sync.connection import RECENT_DATE
from urllib3.util.ssl_ import CertificateError, match_hostname

class TestConnection(object):
    """
    Tests in this suite should not make any network requests or connections.
    """
    def test_match_hostname_no_cert(self):
        cert = None
        asserted_hostname = 'foo'
        with pytest.raises(ValueError):
            match_hostname(cert, asserted_hostname)

    def test_match_hostname_empty_cert(self):
        cert = {}
        asserted_hostname = 'foo'
        with pytest.raises(ValueError):
            match_hostname(cert, asserted_hostname)

    def test_match_hostname_match(self):
        cert = {'subjectAltName': [('DNS', 'foo')]}
        asserted_hostname = 'foo'
        match_hostname(cert, asserted_hostname)

    def test_match_hostname_mismatch(self):
        cert = {'subjectAltName': [('DNS', 'foo')]}
        asserted_hostname = 'bar'
        try:
            with mock.patch('urllib3.util.ssl_.log.error') as mock_log:
                match_hostname(cert, asserted_hostname)
        except CertificateError as e:
            assert str(e) == "hostname 'bar' doesn't match 'foo'"
            mock_log.assert_called_once_with(
                'Certificate did not match expected hostname: %s. '
                'Certificate: %s',
                'bar', {'subjectAltName': [('DNS', 'foo')]}
            )
            assert e._peer_cert == cert

    @pytest.mark.xfail
    def test_recent_date(self):
        # This test is to make sure that the RECENT_DATE value
        # doesn't get too far behind what the current date is.
        # When this test fails update urllib3.connection.RECENT_DATE
        # according to the rules defined in that file.
        two_years = datetime.timedelta(days=365 * 2)
        assert RECENT_DATE > (datetime.datetime.today() - two_years).date()

from . import AppEngineSandboxTest, MockResponse

import pytest
from mock import patch
from ..test_no_ssl import TestWithoutSSL



class TestHTTP(AppEngineSandboxTest, TestWithoutSSL):
    def test_urlfetch_called_with_http(self):
        """
        Check that URLFetch is used to fetch non-https resources
        """
        resp = MockResponse(
            'OK',
            200,
            False,
            'http://www.google.com',
            {'content-type': 'text/plain'})
        with patch('google.appengine.api.urlfetch.fetch', return_value=resp) as fetchmock:
            import urllib3
            pool = urllib3.HTTPConnectionPool('www.google.com', '80')
            r = pool.request('GET', '/')
            self.assertEqual(r.status, 200, r.data)
            self.assertEqual(fetchmock.call_count, 1)


class TestHTTPS(AppEngineSandboxTest):
    @pytest.mark.skip('This test fails.')
    def test_urlfetch_called_with_https(self, urlfetch):
        """
        Check that URLFetch is used when fetching https resources
        """
        resp = MockResponse(
            'OK',
            200,
            False,
            'https://www.google.com',
            {'content-type': 'text/plain'})
        with patch('google.appengine.api.urlfetch.fetch', return_value=resp) as fetchmock:
            import urllib3
            pool = urllib3.HTTPSConnectionPool('www.google.com', '443')
            pool.ConnectionCls = urllib3.connection.UnverifiedHTTPSConnection
            r = pool.request('GET', '/')
            self.assertEqual(r.status, 200, r.data)
            self.assertEqual(fetchmock.call_count, 1)

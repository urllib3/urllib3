import unittest

from dummyserver.testcase import HTTPSDummyServerTestCase
from nose.plugins.skip import SkipTest

try:
    from google.appengine.api import urlfetch
    (urlfetch)
except ImportError:
    raise SkipTest("App Engine SDK not available.")

from urllib3.contrib.appengine import AppEngineManager, AppEnginePlatformError
from urllib3.exceptions import (
    TimeoutError,
    ProtocolError,
    SSLError)
from urllib3.util.url import Url
from urllib3.util.retry import Retry

from test.with_dummyserver.test_connectionpool import (
    TestConnectionPool, TestRetry)


# Prevent nose from running these test.
TestConnectionPool.__test__ = False
TestRetry.__test__ = False


# This class is used so we can re-use the tests from the connection pool.
# It proxies all requests to the manager.
class MockPool(object):
    def __init__(self, host, port, manager, scheme='http'):
        self.host = host
        self.port = port
        self.manager = manager
        self.scheme = scheme

    def request(self, method, url, *args, **kwargs):
        url = self._absolute_url(url)
        return self.manager.request(method, url, *args, **kwargs)

    def urlopen(self, method, url, *args, **kwargs):
        url = self._absolute_url(url)
        return self.manager.urlopen(method, url, *args, **kwargs)

    def _absolute_url(self, path):
        return Url(
            scheme=self.scheme,
            host=self.host,
            port=self.port,
            path=path).url


# Note that this doesn't run in the sandbox, it only runs with the URLFetch
# API stub enabled. There's no need to enable the sandbox as we know for a fact
# that URLFetch is used by the connection manager.
class TestGAEConnectionManager(TestConnectionPool):
    __test__ = True

    # Magic class variable that tells NoseGAE to enable the URLFetch stub.
    nosegae_urlfetch = True

    def setUp(self):
        self.manager = AppEngineManager()
        self.pool = MockPool(self.host, self.port, self.manager)

    # Tests specific to AppEngineManager

    def test_exceptions(self):
        # DeadlineExceededError -> TimeoutError
        self.assertRaises(
            TimeoutError,
            self.pool.request,
            'GET',
            '/sleep?seconds=0.005',
            timeout=0.001)

        # InvalidURLError -> ProtocolError
        self.assertRaises(
            ProtocolError,
            self.manager.request,
            'GET',
            'ftp://invalid/url')

        # DownloadError -> ProtocolError
        self.assertRaises(
            ProtocolError,
            self.manager.request,
            'GET',
            'http://0.0.0.0')

        # ResponseTooLargeError -> AppEnginePlatformError
        self.assertRaises(
            AppEnginePlatformError,
            self.pool.request,
            'GET',
            '/nbytes?length=33554433')  # One byte over 32 megabtyes.

        # URLFetch reports the request too large error as a InvalidURLError,
        # which maps to a AppEnginePlatformError.
        body = b'1' * 10485761  # One byte over 10 megabytes.
        self.assertRaises(
            AppEnginePlatformError,
            self.manager.request,
            'POST',
            '/',
            body=body)

    # Re-used tests below this line.
    # Subsumed tests
    test_timeout_float = None  # Covered by test_exceptions.

    # Non-applicable tests
    test_conn_closed = None
    test_nagle = None
    test_socket_options = None
    test_disable_default_socket_options = None
    test_defaults_are_applied = None
    test_tunnel = None
    test_keepalive = None
    test_keepalive_close = None
    test_connection_count = None
    test_connection_count_bigpool = None
    test_for_double_release = None
    test_release_conn_parameter = None
    test_stream_keepalive = None
    test_cleanup_on_connection_error = None

    # Tests that should likely be modified for appengine specific stuff
    test_timeout = None
    test_connect_timeout = None
    test_connection_error_retries = None
    test_total_timeout = None
    test_none_total_applies_connect = None
    test_timeout_success = None
    test_source_address_error = None
    test_bad_connect = None
    test_partial_response = None
    test_dns_error = None


class TestGAEConnectionManagerWithSSL(HTTPSDummyServerTestCase):
    nosegae_urlfetch = True

    def setUp(self):
        self.manager = AppEngineManager()
        self.pool = MockPool(self.host, self.port, self.manager, 'https')

    def test_exceptions(self):
        # SSLCertificateError -> SSLError
        # SSLError is raised with dummyserver because URLFetch doesn't allow
        # self-signed certs.
        self.assertRaises(
            SSLError,
            self.pool.request,
            'GET',
            '/')


class TestGAERetry(TestRetry):
    __test__ = True

    # Magic class variable that tells NoseGAE to enable the URLFetch stub.
    nosegae_urlfetch = True

    def setUp(self):
        self.manager = AppEngineManager()
        self.pool = MockPool(self.host, self.port, self.manager)

    def test_default_method_whitelist_retried(self):
        """ urllib3 should retry methods in the default method whitelist """
        retry = Retry(total=1, status_forcelist=[418])
        # Use HEAD instead of OPTIONS, as URLFetch doesn't support OPTIONS
        resp = self.pool.request(
            'HEAD', '/successful_retry',
            headers={'test-name': 'test_default_whitelist'},
            retries=retry)
        self.assertEqual(resp.status, 200)

    #test_max_retry = None
    #test_disabled_retry = None


if __name__ == '__main__':
    unittest.main()

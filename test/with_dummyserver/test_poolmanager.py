import unittest
import io
import json
import time

import pytest

from dummyserver.server import HAS_IPV6
from dummyserver.testcase import (HTTPDummyServerTestCase,
                                  IPv6HTTPDummyServerTestCase)
from urllib3.base import DEFAULT_PORTS
from urllib3.poolmanager import PoolManager
from urllib3.exceptions import (
    MaxRetryError, NewConnectionError, UnrewindableBodyError
)
from urllib3.util.retry import Retry, RequestHistory


class TestPoolManager(HTTPDummyServerTestCase):

    def setUp(self):
        self.base_url = 'http://%s:%d' % (self.host, self.port)
        self.base_url_alt = 'http://%s:%d' % (self.host_alt, self.port)

    def test_redirect(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_redirect_twice(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/redirect' % self.base_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/redirect?target=%s/' % (self.base_url,
                                                                       self.base_url)})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_redirect_to_relative_url(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '/redirect'},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '/redirect'})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_cross_host_redirect(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        cross_host_location = '%s/echo?a=b' % self.base_url_alt
        try:
            http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': cross_host_location},
                         timeout=1, retries=0)
            self.fail("Request succeeded instead of raising an exception like it should.")

        except MaxRetryError:
            pass

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/echo?a=b' % self.base_url_alt},
                         timeout=1, retries=1)

        self.assertEqual(r._pool.host, self.host_alt)

    def test_too_many_redirects(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        try:
            r = http.request('GET', '%s/redirect' % self.base_url,
                             fields={'target': '%s/redirect?target=%s/' % (self.base_url,
                                                                           self.base_url)},
                             retries=1)
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

        try:
            r = http.request('GET', '%s/redirect' % self.base_url,
                             fields={'target': '%s/redirect?target=%s/' % (self.base_url,
                                                                           self.base_url)},
                             retries=Retry(total=None, redirect=1))
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

    def test_redirect_cross_host_remove_headers(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/headers' % self.base_url_alt},
                         headers={'Authorization': 'foo'})

        self.assertEqual(r.status, 200)

        data = json.loads(r.data.decode('utf-8'))

        self.assertNotIn('Authorization', data)

    def test_redirect_cross_host_no_remove_headers(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/headers' % self.base_url_alt},
                         headers={'Authorization': 'foo'},
                         retries=Retry(remove_headers_on_redirect=[]))

        self.assertEqual(r.status, 200)

        data = json.loads(r.data.decode('utf-8'))

        self.assertEqual(data['Authorization'], 'foo')

    def test_redirect_cross_host_set_removed_headers(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/headers' % self.base_url_alt},
                         headers={'X-API-Secret': 'foo',
                                  'Authorization': 'bar'},
                         retries=Retry(remove_headers_on_redirect=['X-API-Secret']))

        self.assertEqual(r.status, 200)

        data = json.loads(r.data.decode('utf-8'))

        self.assertNotIn('X-API-Secret', data)
        self.assertEqual(data['Authorization'], 'bar')

    def test_raise_on_redirect(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/redirect?target=%s/' % (self.base_url,
                                                                       self.base_url)},
                         retries=Retry(total=None, redirect=1, raise_on_redirect=False))

        self.assertEqual(r.status, 303)

    def test_raise_on_status(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        try:
            # the default is to raise
            r = http.request('GET', '%s/status' % self.base_url,
                             fields={'status': '500 Internal Server Error'},
                             retries=Retry(total=1, status_forcelist=range(500, 600)))
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

        try:
            # raise explicitly
            r = http.request('GET', '%s/status' % self.base_url,
                             fields={'status': '500 Internal Server Error'},
                             retries=Retry(total=1,
                                           status_forcelist=range(500, 600),
                                           raise_on_status=True))
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

        # don't raise
        r = http.request('GET', '%s/status' % self.base_url,
                         fields={'status': '500 Internal Server Error'},
                         retries=Retry(total=1,
                                       status_forcelist=range(500, 600),
                                       raise_on_status=False))

        self.assertEqual(r.status, 500)

    def test_missing_port(self):
        # Can a URL that lacks an explicit port like ':80' succeed, or
        # will all such URLs fail with an error?

        http = PoolManager()
        self.addCleanup(http.clear)

        # By globally adjusting `DEFAULT_PORTS` we pretend for a moment
        # that HTTP's default port is not 80, but is the port at which
        # our test server happens to be listening.
        DEFAULT_PORTS['http'] = self.port
        try:
            r = http.request('GET', 'http://%s/' % self.host, retries=0)
        finally:
            DEFAULT_PORTS['http'] = 80

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_headers(self):
        http = PoolManager(headers={'Foo': 'bar'})
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/headers' % self.base_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')

        r = http.request('POST', '%s/headers' % self.base_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')

        r = http.request_encode_url('GET', '%s/headers' % self.base_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')

        r = http.request_encode_body('POST', '%s/headers' % self.base_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')

        r = http.request_encode_url('GET', '%s/headers' % self.base_url, headers={'Baz': 'quux'})
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), None)
        self.assertEqual(returned_headers.get('Baz'), 'quux')

        r = http.request_encode_body('GET', '%s/headers' % self.base_url, headers={'Baz': 'quux'})
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), None)
        self.assertEqual(returned_headers.get('Baz'), 'quux')

    def test_http_with_ssl_keywords(self):
        http = PoolManager(ca_certs='REQUIRED')
        self.addCleanup(http.clear)

        r = http.request('GET', 'http://%s:%s/' % (self.host, self.port))
        self.assertEqual(r.status, 200)

    def test_http_with_ca_cert_dir(self):
        http = PoolManager(ca_certs='REQUIRED', ca_cert_dir='/nosuchdir')
        self.addCleanup(http.clear)

        r = http.request('GET', 'http://%s:%s/' % (self.host, self.port))
        self.assertEqual(r.status, 200)

    @pytest.mark.xfail
    def test_cleanup_on_connection_error(self):
        '''
        Test that connections are recycled to the pool on
        connection errors where no http response is received.
        '''
        poolsize = 3

        with PoolManager(maxsize=poolsize, block=True) as http:
            pool = http.connection_from_host(self.host, self.port)
            self.assertEqual(pool.pool.qsize(), poolsize)

            # force a connection error by supplying a non-existent
            # url. We won't get a response for this  and so the
            # conn won't be implicitly returned to the pool.
            url = "%s/redirect" % self.base_url
            self.assertRaises(MaxRetryError,
                              http.request,
                              'GET', url,
                              fields={'target': '/'}, retries=0)

            r = http.request('GET', url,
                             fields={'target': '/'},
                             retries=1)
            r.release_conn()

            # the pool should still contain poolsize elements
            self.assertEqual(pool.pool.qsize(), poolsize)


class TestRetry(HTTPDummyServerTestCase):

    def setUp(self):
        self.base_url = 'http://%s:%d' % (self.host, self.port)
        self.base_url_alt = 'http://%s:%d' % (self.host_alt, self.port)

    def test_max_retry(self):
        with PoolManager() as http:
            try:
                r = http.request('GET', '%s/redirect' % self.base_url,
                                 fields={'target': '/'},
                                 retries=0)
                self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
            except MaxRetryError:
                pass

    def test_disabled_retry(self):
        """ Disabled retries should disable redirect handling. """
        with PoolManager() as http:
            r = http.request('GET', '%s/redirect' % self.base_url,
                             fields={'target': '/'},
                             retries=False)
            self.assertEqual(r.status, 303)

            r = http.request('GET', '%s/redirect' % self.base_url,
                             fields={'target': '/'},
                             retries=Retry(redirect=False))
            self.assertEqual(r.status, 303)

            self.assertRaises(NewConnectionError, http.request,
                              'GET', 'http://thishostdoesnotexist.invalid/',
                              timeout=0.001, retries=False)

    def test_read_retries(self):
        """ Should retry for status codes in the whitelist """
        retry = Retry(read=1, status_forcelist=[418])

        with PoolManager() as http:
            resp = http.request('GET', '%s/successful_retry' % self.base_url,
                                headers={'test-name': 'test_read_retries'},
                                retries=retry)
            self.assertEqual(resp.status, 200)

    def test_read_total_retries(self):
        """ HTTP response w/ status code in the whitelist should be retried """
        headers = {'test-name': 'test_read_total_retries'}
        retry = Retry(total=1, status_forcelist=[418])

        with PoolManager() as http:
            resp = http.request('GET', '%s/successful_retry' % self.base_url,
                                headers=headers, retries=retry)
            self.assertEqual(resp.status, 200)

    def test_retries_wrong_whitelist(self):
        """HTTP response w/ status code not in whitelist shouldn't be retried"""
        retry = Retry(total=1, status_forcelist=[202])

        with PoolManager() as http:
            resp = http.request('GET', '%s/successful_retry' % self.base_url,
                                headers={'test-name': 'test_wrong_whitelist'},
                                retries=retry)
            self.assertEqual(resp.status, 418)

    def test_default_method_whitelist_retried(self):
        """ urllib3 should retry methods in the default method whitelist """
        retry = Retry(total=1, status_forcelist=[418])

        with PoolManager() as http:
            resp = http.request('OPTIONS', '%s/successful_retry' % self.base_url,
                                headers={'test-name': 'test_default_whitelist'},
                                retries=retry)
            self.assertEqual(resp.status, 200)

    def test_retries_wrong_method_list(self):
        """Method not in our whitelist should not be retried, even if code matches"""
        headers = {'test-name': 'test_wrong_method_whitelist'}
        retry = Retry(total=1, status_forcelist=[418],
                      method_whitelist=['POST'])

        with PoolManager() as http:
            resp = http.request('GET', '%s/successful_retry' % self.base_url,
                                headers=headers, retries=retry)
            self.assertEqual(resp.status, 418)

    def test_read_retries_unsuccessful(self):
        headers = {'test-name': 'test_read_retries_unsuccessful'}

        with PoolManager() as http:
            resp = http.request('GET', '%s/successful_retry' % self.base_url,
                                headers=headers, retries=1)
            self.assertEqual(resp.status, 418)

    def test_retry_reuse_safe(self):
        """ It should be possible to reuse a Retry object across requests """
        headers = {'test-name': 'test_retry_safe'}
        retry = Retry(total=1, status_forcelist=[418])

        with PoolManager() as http:
            resp = http.request('GET', '%s/successful_retry' % self.base_url,
                                headers=headers, retries=retry)
            self.assertEqual(resp.status, 200)
            resp = http.request('GET', '%s/successful_retry' % self.base_url,
                                headers=headers, retries=retry)
            self.assertEqual(resp.status, 200)

    def test_retry_return_in_response(self):
        headers = {'test-name': 'test_retry_return_in_response'}
        retry = Retry(total=2, status_forcelist=[418])

        with PoolManager() as http:
            resp = http.request('GET', '%s/successful_retry' % self.base_url,
                                headers=headers, retries=retry)
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.retries.total, 1)
            self.assertEqual(resp.retries.history,
                             (RequestHistory('GET', '/successful_retry', None, 418, None),))

    def test_retry_redirect_history(self):
        with PoolManager() as http:
            resp = http.request('GET', '%s/redirect' % self.base_url, fields={'target': '/'})
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.retries.history,
                             (RequestHistory('GET',
                                             self.base_url + '/redirect?target=%2F',
                                             None,
                                             303,
                                             '/'),))

    def test_multi_redirect_history(self):
        with PoolManager() as http:
            r = http.request('GET', '%s/multi_redirect' % self.base_url,
                             fields={'redirect_codes': '303,302,200'},
                             redirect=False)
            self.assertEqual(r.status, 303)
            self.assertEqual(r.retries.history, tuple())

            r = http.request('GET', '%s/multi_redirect' % self.base_url, retries=10,
                             fields={'redirect_codes': '303,302,301,307,302,200'})
            self.assertEqual(r.status, 200)
            self.assertEqual(r.data, b'Done redirecting')

            expected = [(303, '/multi_redirect?redirect_codes=302,301,307,302,200'),
                        (302, '/multi_redirect?redirect_codes=301,307,302,200'),
                        (301, '/multi_redirect?redirect_codes=307,302,200'),
                        (307, '/multi_redirect?redirect_codes=302,200'),
                        (302, '/multi_redirect?redirect_codes=200')]
            actual = [(history.status, history.redirect_location) for history in r.retries.history]
            self.assertEqual(actual, expected)

    def test_redirect_put_file(self):
        """PUT with file object should work with a redirection response"""
        retry = Retry(total=3, status_forcelist=[418])
        # httplib reads in 8k chunks; use a larger content length
        content_length = 65535
        data = b'A' * content_length
        uploaded_file = io.BytesIO(data)
        headers = {'test-name': 'test_redirect_put_file',
                   'Content-Length': str(content_length)}
        url = '%s/redirect?target=/echo&status=307' % self.base_url

        with PoolManager() as http:
            resp = http.urlopen('PUT', url,
                                headers=headers,
                                retries=retry,
                                body=uploaded_file)
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.data, data)


class TestRetryAfter(HTTPDummyServerTestCase):
    def setUp(self):
        self.base_url = 'http://%s:%d' % (self.host, self.port)
        self.base_url_alt = 'http://%s:%d' % (self.host_alt, self.port)

    def test_retry_after(self):
        url = "%s/retry_after" % self.base_url
        with PoolManager() as http:
            # Request twice in a second to get a 429 response.
            r = http.request('GET', url,
                             fields={'status': '429 Too Many Requests'},
                             retries=False)
            r = http.request('GET', url,
                             fields={'status': '429 Too Many Requests'},
                             retries=False)
            self.assertEqual(r.status, 429)

            r = http.request('GET', url,
                             fields={'status': '429 Too Many Requests'},
                             retries=True)
            self.assertEqual(r.status, 200)

            # Request twice in a second to get a 503 response.
            r = http.request('GET', url,
                             fields={'status': '503 Service Unavailable'},
                             retries=False)
            r = http.request('GET', url,
                             fields={'status': '503 Service Unavailable'},
                             retries=False)
            self.assertEqual(r.status, 503)

            r = http.request('GET', url,
                             fields={'status': '503 Service Unavailable'},
                             retries=True)
            self.assertEqual(r.status, 200)

            # Ignore Retry-After header on status which is not defined in
            # Retry.RETRY_AFTER_STATUS_CODES.
            r = http.request('GET', url,
                             fields={'status': "418 I'm a teapot"},
                             retries=True)
            self.assertEqual(r.status, 418)

    def test_redirect_after(self):
        with PoolManager() as http:
            r = http.request('GET', '%s/redirect_after' % self.base_url, retries=False)
            self.assertEqual(r.status, 303)

            t = time.time()
            r = http.request('GET', '%s/redirect_after' % self.base_url)
            self.assertEqual(r.status, 200)
            delta = time.time() - t
            self.assertTrue(delta >= 1)

            t = time.time()
            timestamp = t + 2
            r = http.request('GET', self.base_url + '/redirect_after?date=' + str(timestamp))
            self.assertEqual(r.status, 200)
            delta = time.time() - t
            self.assertTrue(delta >= 1)

            # Retry-After is past
            t = time.time()
            timestamp = t - 1
            r = http.request('GET', self.base_url + '/redirect_after?date=' + str(timestamp))
            delta = time.time() - t
            self.assertEqual(r.status, 200)
            self.assertTrue(delta < 1)


class TestFileBodiesOnRetryOrRedirect(HTTPDummyServerTestCase):
    def setUp(self):
        self.base_url = 'http://%s:%d' % (self.host, self.port)
        self.base_url_alt = 'http://%s:%d' % (self.host_alt, self.port)

    def test_retries_put_filehandle(self):
        """HTTP PUT retry with a file-like object should not timeout"""
        retry = Retry(total=3, status_forcelist=[418])
        # httplib reads in 8k chunks; use a larger content length
        content_length = 65535
        data = b'A' * content_length
        uploaded_file = io.BytesIO(data)
        headers = {'test-name': 'test_retries_put_filehandle',
                   'Content-Length': str(content_length)}

        with PoolManager() as http:
            resp = http.urlopen('PUT', '%s/successful_retry' % self.base_url,
                                headers=headers,
                                retries=retry,
                                body=uploaded_file,
                                redirect=False)
            self.assertEqual(resp.status, 200)

    def test_redirect_with_failed_tell(self):
        """Abort request if failed to get a position from tell()"""
        class BadTellObject(io.BytesIO):

            def tell(self):
                raise IOError

        body = BadTellObject(b'the data')
        url = '%s/redirect?target=/successful_retry' % self.base_url
        # httplib uses fileno if Content-Length isn't supplied,
        # which is unsupported by BytesIO.
        headers = {'Content-Length': '8'}

        with PoolManager() as http:
            try:
                http.urlopen('PUT', url, headers=headers, body=body)
                self.fail('PUT successful despite failed rewind.')
            except UnrewindableBodyError as e:
                self.assertTrue('Unable to record file position for' in str(e))


@pytest.mark.skipif(
    not HAS_IPV6,
    reason='IPv6 is not supported on this system'
)
class TestIPv6PoolManager(IPv6HTTPDummyServerTestCase):

    def setUp(self):
        self.base_url = 'http://[%s]:%d' % (self.host, self.port)

    def test_ipv6(self):
        http = PoolManager()
        self.addCleanup(http.clear)
        http.request('GET', self.base_url)


if __name__ == '__main__':
    unittest.main()

import logging
import sys
import unittest
import urllib

from urllib3 import (
    encode_multipart_formdata,
    HTTPConnectionPool,
    TimeoutError,
    MaxRetryError)


HOST = "localhost"
PORT = 8081

log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))


class TestConnectionPool(unittest.TestCase):

    @staticmethod
    def _setUp(test_id, test_type):
        # Create connection pool and test for dummy server...
        http_pool = HTTPConnectionPool(HOST, PORT)
        try:
            r = http_pool.get_url('/set_up', retries=1,
                                  fields={'test_id': test_id,
                                          'test_type': test_type})
            if r.data != "Dummy server is ready!":
                raise Exception("Got unexpected response: %s" % r.data)
            return http_pool
        except Exception, e:
            raise Exception("Dummy server not running, make sure HOST and PORT "
                            "correspond to the dummy server: %s" % e.message)

    @classmethod
    def setUpClass(cls):
        cls._setUp(cls.__name__, test_type='suite')

    def setUp(self):
        self.http_pool = self._setUp(self.id(), test_type='case')

    def test_get_url(self):
        r = self.http_pool.get_url('/specific_method',
                                   fields={'method': 'GET'})
        self.assertEqual(r.status, 200, r.data)

    def test_post_url(self):
        r = self.http_pool.post_url('/specific_method',
                                    fields={'method': 'POST'})
        self.assertEqual(r.status, 200, r.data)

    def test_urlopen_put(self):
        r = self.http_pool.urlopen('PUT', '/specific_method?method=PUT')
        self.assertEqual(r.status, 200, r.data)

    def test_wrong_specific_method(self):
        # To make sure the dummy server is actually returning failed responses
        r = self.http_pool.get_url('/specific_method',
                                   fields={'method': 'POST'})
        self.assertEqual(r.status, 400, r.data)

        r = self.http_pool.post_url('/specific_method',
                                    fields={'method': 'GET'})
        self.assertEqual(r.status, 400, r.data)

    def test_upload(self):
        data = "I'm in ur multipart form-data, hazing a cheezburgr"
        fields = {
            'upload_param': 'filefield',
            'upload_filename': 'lolcat.txt',
            'upload_size': len(data),
            'filefield': ('lolcat.txt', data),
        }

        r = self.http_pool.post_url('/upload', fields=fields)
        self.assertEqual(r.status, 200, r.data)

    def test_unicode_upload(self):
        fieldname = u'myfile'
        filename = u'\xe2\x99\xa5.txt'
        data = u'\xe2\x99\xa5'.encode('utf8')
        size = len(data)

        fields = {
            u'upload_param': fieldname,
            u'upload_filename': filename,
            u'upload_size': size,
            fieldname: (filename, data),
        }

        r = self.http_pool.post_url('/upload', fields=fields)
        self.assertEqual(r.status, 200, r.data)

    def test_timeout(self):
        pool = HTTPConnectionPool(HOST, PORT, timeout=0.01)
        try:
            pool.get_url('/sleep',
                         fields={'seconds': '0.02'})
            self.fail("Failed to raise TimeoutError exception")
        except TimeoutError:
            pass

    def test_redirect(self):
        r = self.http_pool.get_url('/redirect',
                                   fields={'target': '/'},
                                   redirect=False)
        self.assertEqual(r.status, 303)

        r = self.http_pool.get_url('/redirect',
                                   fields={'target': '/'})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, 'Dummy server!')

    def test_maxretry(self):
        try:
            self.http_pool.get_url('/redirect',
                                   fields={'target': '/'},
                                   retries=0)
            self.fail("Failed to raise MaxRetryError exception")
        except MaxRetryError:
            pass

    def test_keepalive(self):
        # First with close
        r = self.http_pool.get_url('/keepalive?close=1', retries=0,
                                   headers={"Connection": "close"})
        self.assertEqual(r.status, 200)

        # The dummyserver will have responded with Connection:close,
        # and httplib will properly cleanup the socket.

        # We grab the HTTPConnection object straight from the Queue,
        # because _get_conn() is where the check & reset occurs
        # pylint: disable-msg=W0212
        conn = self.http_pool.pool.get()
        self.assertEqual(conn.sock, None)
        self.http_pool._put_conn(conn)

        # Now with keep-alive
        r = self.http_pool.get_url('/keepalive?close=0', retries=0,
                                   headers={"Connection": "keep-alive",
                                            "Keep-alive": "1"})
        self.assertEqual(r.status, 200)

        # The dummyserver responded with Connection:keep-alive, but
        # the base implementation automatically closes it anyway. Perfect
        # test case!

        conn = self.http_pool.pool.get()
        self.assertNotEqual(conn.sock, None)
        self.http_pool._put_conn(conn)

        # ... and with close again
        # NOTE: This is the one that should get auto-cleaned-up!
        r = self.http_pool.get_url('/keepalive?close=1', retries=0,
                                   headers={"Connection": "close"})
        self.assertEqual(r.status, 200)

        conn = self.http_pool.pool.get()
        self.assertEqual(conn.sock, None)
        self.http_pool._put_conn(conn)

    def test_post_with_urlencode(self):
        data = {'banana': 'hammock', 'lol': 'cat'}
        r = self.http_pool.post_url('/echo',
                                    fields=data,
                                    encode_multipart=False)
        self.assertEqual(r.data, urllib.urlencode(data))

    def test_post_with_multipart(self):
        data = {'banana': 'hammock', 'lol': 'cat'}
        r = self.http_pool.post_url('/echo',
                                    fields=data,
                                    encode_multipart=True)
        body = r.data.split('\r\n')

        encoded_data = encode_multipart_formdata(data)[0]
        expected_body = encoded_data.split('\r\n')

        # TODO: Get rid of extra parsing stuff when you can specify
        # a custom boundary to encode_multipart_formdata
        """
        We need to loop the return lines because a timestamp is attached
        from within encode_multipart_formdata. When the server echos back
        the data, it has the timestamp from when the data was encoded, which
        is not equivalent to when we run encode_multipart_formdata on
        the data again.
        """
        for i, line in enumerate(body):
            if line.startswith('--'):
                continue

            self.assertEqual(body[i], expected_body[i])

    def test_check_gzip(self):
        r = self.http_pool.get_url('/encodingrequest',
                                   headers={'accept-encoding': 'gzip'})
        self.assertEqual(r.headers.get('content-encoding'), 'gzip')
        self.assertEqual(r.data, 'hello, world!')

    def test_check_deflate(self):
        r = self.http_pool.get_url('/encodingrequest',
                                   headers={'accept-encoding': 'deflate'})
        self.assertEqual(r.headers.get('content-encoding'), 'deflate')
        self.assertEqual(r.data, 'hello, world!')

    def test_partial_response(self):
        http_pool = HTTPConnectionPool(HOST, PORT, maxsize=1)

        req_data = {'lol': 'cat'}
        resp_data = urllib.urlencode(req_data)

        r = http_pool.get_url('/echo', fields=req_data)

        self.assertEqual(r.read(5), resp_data[:5])
        self.assertEqual(r.read(), resp_data[5:])

    def test_lazy_load_twice(self):
        http_pool = HTTPConnectionPool(HOST, PORT, block=True, maxsize=1, timeout=2)

        payload_size = 1024 * 512
        first_chunk = 512

        boundary = 'foo'

        req_data = {'count': 'a' * payload_size}
        resp_data = encode_multipart_formdata(req_data, boundary=boundary)[0]

        req2_data = {'count': 'b' * payload_size}
        resp2_data = encode_multipart_formdata(req2_data, boundary=boundary)[0]

        r1 = http_pool.post_url('/echo', fields=req_data, multipart_boundary=boundary)

        self.assertEqual(r1.read(first_chunk), resp_data[:first_chunk])

        r2 = http_pool.post_url('/echo', fields=req2_data, multipart_boundary=boundary)

        self.assertEqual(r2.read(first_chunk), resp2_data[:first_chunk])

        self.assertEqual(r1.read(), resp_data[first_chunk:])
        self.assertEqual(r2.read(), resp2_data[first_chunk:])

        self.assertEqual(http_pool.num_connections, 1)
        self.assertEqual(http_pool.num_requests, 2)



if __name__ == '__main__':
    unittest.main()

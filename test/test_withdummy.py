import unittest
import sys

import urllib

from urllib3 import HTTPConnectionPool, TimeoutError, MaxRetryError, encode_multipart_formdata

HOST="localhost"
PORT=8081

import logging
log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))

class TestConnectionPool(unittest.TestCase):
    def __init__(self, *args, **kw):
        # Test for dummy server...
        self.http_pool = HTTPConnectionPool(HOST, PORT)
        try:
            r = self.http_pool.get_url('/', retries=1)
            if r.data != "Dummy server!":
                raise Exception("Got unexpected response: %s" % r.data)
        except Exception, e:
            raise Exception("Dummy server not running, make sure HOST and PORT correspond to the dummy server: %s" % e.message)

        return super(TestConnectionPool, self).__init__(*args, **kw)

    def test_get_url(self):
        r = self.http_pool.get_url('/specific_method', fields={'method': 'GET'})
        self.assertEquals(r.status, 200, r.data)

    def test_post_url(self):
        r = self.http_pool.post_url('/specific_method', fields={'method': 'POST'})
        self.assertEquals(r.status, 200, r.data)

    def test_urlopen_put(self):
        r = self.http_pool.urlopen('PUT', '/specific_method?method=PUT')

    def test_wrong_specific_method(self):
        # To make sure the dummy server is actually returning failed responses
        r = self.http_pool.get_url('/specific_method', fields={'method': 'POST'})
        self.assertEquals(r.status, 400, r.data)

        r = self.http_pool.post_url('/specific_method', fields={'method': 'GET'})
        self.assertEquals(r.status, 400, r.data)

    def test_upload(self):
        data = "I'm in ur multipart form-data, hazing a cheezburgr"
        fields = {
            'upload_param': 'filefield',
            'upload_filename': 'lolcat.txt',
            'upload_size': len(data),
            'filefield': ('lolcat.txt', data),
        }

        r = self.http_pool.post_url('/upload', fields=fields)
        self.assertEquals(r.status, 200, r.data)

    def test_unicode_upload(self):
        fieldname = u'myfile'
        filename = u'\xe2\x99\xa5.txt'
        data = u'\xe2\x99\xa5'.encode('utf8')
        size = len(data)

        fields = {
            u'upload_param': fieldname,
            u'upload_filename': filename,
            u'upload_size': len(data),
            fieldname: (filename, data),
        }

        r = self.http_pool.post_url('/upload', fields=fields)
        self.assertEquals(r.status, 200, r.data)

    def test_timeout(self):
        pool = HTTPConnectionPool(HOST, PORT, timeout=0.1)
        try:
            r = pool.get_url('/sleep', fields={'seconds': '0.2'})
            self.fail("Failed to raise TimeoutError exception")
        except TimeoutError, e:
            pass

    def test_redirect(self):
        r = self.http_pool.get_url('/redirect', fields={'target': '/'}, redirect=False)
        self.assertEquals(r.status, 303)

        r = self.http_pool.get_url('/redirect', fields={'target': '/'})
        self.assertEquals(r.status, 200)
        self.assertEquals(r.data, 'Dummy server!')

    def test_maxretry(self):
        try:
            r = self.http_pool.get_url('/redirect', fields={'target': '/'}, retries=0)
            self.fail("Failed to raise MaxRetryError exception")
        except MaxRetryError, e:
            pass

    def test_keepalive(self):
        # First with close
        r = self.http_pool.get_url('/keepalive?close=1', retries=0,
                                   headers={"Connection": "close"})
        self.assertEquals(r.status, 200)

        # The dummyserver will have responded with Connection:close,
        # and httplib will properly cleanup the socket.

        # We grab the HTTPConnection object straight from the Queue,
        # because _get_conn() is where the check & reset occurs
        conn = self.http_pool.pool.get()
        self.assertEquals(conn.sock, None)
        self.http_pool._put_conn(conn)

        # Now with keep-alive
        r = self.http_pool.get_url('/keepalive?close=0', retries=0,
                                   headers={"Connection": "keep-alive",
                                            "Keep-alive": "1"})
        self.assertEquals(r.status, 200)

        # The dummyserver responded with Connection:keep-alive, but
        # the base implementation automatically closes it anyway. Perfect
        # test case!

        conn = self.http_pool.pool.get()
        self.assertNotEquals(conn.sock, None)
        self.http_pool._put_conn(conn)

        # ... and with close again
        # NOTE: This is the one that should get auto-cleaned-up!
        r = self.http_pool.get_url('/keepalive?close=1', retries=0,
                                   headers={"Connection": "close"})
        self.assertEquals(r.status, 200)

        conn = self.http_pool.pool.get()
        self.assertEquals(conn.sock, None)
        self.http_pool._put_conn(conn)

    def test_post_with_urlencode(self):
        data = {'banana': 'hammock', 'lol': 'cat'}
        r = self.http_pool.post_url('/echo', fields=data, encode_multipart=False)
        self.assertEquals(r.data, urllib.urlencode(data))

    def test_post_with_multipart(self):
        data = {'banana': 'hammock', 'lol': 'cat'}
        r = self.http_pool.post_url('/echo', fields=data, encode_multipart=True)
        body = r.data.split('\r\n')

        encoded_data = encode_multipart_formdata(data)[0]
        expected_body = encoded_data.split('\r\n')

        # TODO: Get rid of extra parsing stuff when you can specify 
        # a custom boundary to encode_multipart_formdata
        """
        We need to loop the return lines because a timestamp is attached from within
        encode_multipart_formdata.  When the server echos back the data, it has the 
        timestamp from when the data was encoded, which is not equivalent to when we
        run encode_multipart_formdata on the data again.
        """
        for i, line in enumerate(body):
            if line.startswith('--'):
                continue

            self.assertEquals(body[i], expected_body[i])


if __name__ == '__main__':
    unittest.main()

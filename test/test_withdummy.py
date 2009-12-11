import unittest

import sys
sys.path.append('../')

from urllib3 import HTTPConnectionPool, TimeoutError, MaxRetryError

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
        fields = {'upload_param': 'filefield',
                'upload_filename': 'lolcat.txt',
                'upload_size': len(data),
                'filefield': ('lolcat.txt', data)}

        r = self.http_pool.post_url('/upload', fields=fields)
        self.assertEquals(r.status, 200, r.data)

    def test_timeout(self):
        pool = HTTPConnectionPool(HOST, PORT, timeout=0.1)
        try:
            r = pool.get_url('/sleep', fields={'seconds': 0.2})
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


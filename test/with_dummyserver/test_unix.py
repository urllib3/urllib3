import os

from dummyserver.testcase import HTTPDummyServerTestCase


class UnixHTTPDummyServerTestCase(HTTPDummyServerTestCase):
    host = '/tmp/dummyserver.sock'

    @classmethod
    def tearDownClass(cls):
        cls._stop_server()
        try:
            os.remove(cls.host)
        except OSError:
            pass


class TestUnixHTTPConnectionPool(UnixHTTPDummyServerTestCase):
    def test_hello(self):
        assert True

from __future__ import absolute_import

if str is bytes:
    import unittest2 as unittest
else:
    import unittest

from urllib3.connectionpool import HTTPConnection, HTTPConnectionPool
from urllib3.response import httplib, HTTPResponse
from urllib3.packages.six.moves import StringIO
from urllib3.packages.six.moves.http_client import HTTPMessage
from urllib3._collections import HTTPHeaderDict
from .test_response import MockChunkedEncodingResponse, MockSock

# HTTPMessage requires a file-like object as input in Python 2.x
if str is bytes:
    # Python 2
    def make_dummy_message():
        return HTTPMessage(StringIO())
else:
    # Python 3
    make_dummy_message = HTTPMessage



def make_custom_pool(pool_cls):
    """Instantiate the given custom pool class"""
    return pool_cls(host='localhost', maxsize=1, block=True)

def make_pool_request(pool, **request_kwds):
    """Make a request via the given pool without redirects or retries"""
    return pool.request('GET', '/',
                        redirect=False,
                        retries=False,
                        **request_kwds
    )


class CustomHTTPResponse(HTTPResponse):
    """Alternative HTTPResponse implementation"""
    @classmethod
    def from_httplib(cls, httplib_response, pool, connection, **kwds):
        """Pass through the pool and connection, ignore everything else"""
        return cls(pool=pool, connection=connection)


class DummyRequestPool(HTTPConnectionPool):
    """Connection pool that doesn't initiate any real network requests"""
    @staticmethod
    def _make_request(*args, **kwargs):
        """Construct a dummy httplib level request response"""
        # Note that this can also be used as "DummyRequestPool._make_request()"
        httplib_response = httplib.HTTPResponse(MockSock)
        httplib_response.fp = MockChunkedEncodingResponse([b'f', b'o', b'o'])
        httplib_response.msg = make_dummy_message()
        httplib_response.headers = HTTPHeaderDict()
        return httplib_response


class CustomConnection:
    """Mock out HTTPConnection well enough for customisation testing"""

    def __init__(self, *args, **kwds):
        # Ignore all settings and indicate no socket is available
        self.sock = None
        # Allow configuring the behaviour of getresponse()
        self.reject_buffering_arg = False
        # Track statistics about calls to getresponse()
        self.mocked_response_count = 0
        self.explicitly_buffered_call_count = 0
        self.rejected_call_count = 0

    # Allow close calls
    def close(self):
        pass

    # Don't actually issue any requests
    def request(self, *args, **kwds):
        pass

    # Return a mock response unless configured to fail
    def getresponse(self, buffering=None):
        self.mocked_response_count += 1
        if buffering is not None:
            self.explicitly_buffered_call_count += 1
            if self.reject_buffering_arg:
                self.rejected_call_count += 1
                raise TypeError("Buffering argument not supported!")
        return DummyRequestPool._make_request()

class DummyConnectionPool(HTTPConnectionPool):
    """Connection pool that doesn't create any real network connections"""
    ConnectionCls = CustomConnection
    ResponseCls = CustomHTTPResponse

    def _validate_conn(self, conn):
        return True

class TestCustomisedConnectionPool(unittest.TestCase):
    """
    Tests in this suite should exercise the ConnectionPool customisation
    functionality without actually making any network requests or
    connections.
    """
    def test_invalid_connection_class_fails(self):
        class BrokenConnectionPool(HTTPConnectionPool):
            ConnectionCls = None
        pool = make_custom_pool(BrokenConnectionPool)
        with self.assertRaises((TypeError, AttributeError)):
            make_pool_request(pool)

    def test_invalid_response_class_fails(self):
        class BrokenResponsePool(DummyRequestPool):
            ResponseCls = None
        pool = make_custom_pool(BrokenResponsePool)
        with self.assertRaises((TypeError, AttributeError)):
            make_pool_request(pool)

    def test_custom_http_response_class(self):
        class CustomResponsePool(DummyRequestPool):
            ResponseCls = CustomHTTPResponse

        pool = make_custom_pool(CustomResponsePool)
        response = make_pool_request(
            pool,
            chunked=True,
            preload_content=False
        )
        self.assertIsInstance(response, CustomHTTPResponse)

    # CPython 2.7 doesn't buffer responses by default, but will do so
    # if the undocumented "buffering" parameter is set to True.
    # ConnectionPool should try that initially, but then stop calling it
    # as soon as it raises TypeError on a given pool instance
    def test_getresponse_with_buffering_parameter(self):
        # Check the behaviour with the buffering parameter accepted
        # This also checks that the custom connection and response are used
        pool = make_custom_pool(DummyConnectionPool)
        response = make_pool_request(pool, release_conn=False)
        self.assertIsInstance(response, CustomHTTPResponse)
        conn = response.connection
        self.assertIsInstance(conn, CustomConnection)
        self.assertEqual(conn.mocked_response_count, 1)
        self.assertEqual(conn.explicitly_buffered_call_count, 1)
        self.assertEqual(conn.rejected_call_count, 0)
        response.release_conn()
        # Check the behaviour is maintained for subsequent requests
        response = make_pool_request(pool, release_conn=False)
        conn = response.connection
        self.assertEqual(conn.mocked_response_count, 2)
        self.assertEqual(conn.explicitly_buffered_call_count, 2)
        self.assertEqual(conn.rejected_call_count, 0)
        response.release_conn()

    def test_getresponse_without_buffering_parameter(self):
        # Set the pool's connection to reject the buffering parameter
        pool = make_custom_pool(DummyConnectionPool)
        response = make_pool_request(pool, release_conn=False)
        response.connection.reject_buffering_arg = True
        response.release_conn()
        # Check the behaviour with the buffering parameter rejected
        # is to try it, then fall back to leaving it out
        response = make_pool_request(pool, release_conn=False)
        conn = response.connection
        self.assertEqual(conn.mocked_response_count, 3)
        self.assertEqual(conn.explicitly_buffered_call_count, 2)
        self.assertEqual(conn.rejected_call_count, 1)
        response.release_conn()
        # Also check the argument isn't even supplied on subsequent calls
        response = make_pool_request(pool, release_conn=False)
        conn = response.connection
        self.assertEqual(conn.mocked_response_count, 4)
        self.assertEqual(conn.explicitly_buffered_call_count, 2)
        self.assertEqual(conn.rejected_call_count, 1)
        response.release_conn()

    def test_getresponse_with_broken_customisation(self):
        # Check TypeError is raised if a subclass creates a mismatch
        # between the connection type declared and the one actually used
        class BadConnectionPool(DummyConnectionPool):
            def _validate_conn(self, conn):
                self.ConnectionCls = HTTPConnection
                return True
        # Check the mismatch is tolerated when using the getresponse wrapper
        bad_pool = make_custom_pool(BadConnectionPool)
        response = make_pool_request(bad_pool, release_conn=False)
        response.connection.reject_buffering_arg = True
        response.release_conn()
        # Check it's disallowed when attempting to bypass the wrapper
        error_structure = 'expected.*HTTPConnection.*got.*CustomConnection'
        with self.assertRaisesRegex(TypeError, error_structure):
            make_pool_request(bad_pool)


if __name__ == '__main__':
    unittest.main()

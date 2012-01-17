import unittest
import socket
from threading import Event, Thread
from Queue import Queue

from urllib3.connectionpool import (
    connection_from_url,
    get_host,
    HTTPConnectionPool,
    make_headers)

from urllib3.exceptions import EmptyPoolError


class TestConnectionPool(unittest.TestCase):
    def test_get_host(self):
        url_host_map = {
            'http://google.com/mail': ('http', 'google.com', None),
            'http://google.com/mail/': ('http', 'google.com', None),
            'google.com/mail': ('http', 'google.com', None),
            'http://google.com/': ('http', 'google.com', None),
            'http://google.com': ('http', 'google.com', None),
            'http://www.google.com': ('http', 'www.google.com', None),
            'http://mail.google.com': ('http', 'mail.google.com', None),
            'http://google.com:8000/mail/': ('http', 'google.com', 8000),
            'http://google.com:8000': ('http', 'google.com', 8000),
            'https://google.com': ('https', 'google.com', None),
            'https://google.com:8000': ('https', 'google.com', 8000),
            'http://user:password@127.0.0.1:1234': ('http', '127.0.0.1', 1234),
        }
        for url, expected_host in url_host_map.iteritems():
            returned_host = get_host(url)
            self.assertEquals(returned_host, expected_host)

    def test_same_host(self):
        same_host = [
            ('http://google.com/', '/'),
            ('http://google.com/', 'http://google.com/'),
            ('http://google.com/', 'http://google.com'),
            ('http://google.com/', 'http://google.com/abra/cadabra'),
            ('http://google.com:42/', 'http://google.com:42/abracadabra'),
        ]

        for a, b in same_host:
            c = connection_from_url(a)
            self.assertTrue(c.is_same_host(b), "%s =? %s" % (a, b))

        not_same_host = [
            ('http://yahoo.com/', 'http://google.com/'),
            ('http://google.com:42', 'https://google.com/abracadabra'),
            ('http://google.com', 'https://google.net/'),
        ]

        for a, b in not_same_host:
            c = connection_from_url(a)
            self.assertFalse(c.is_same_host(b), "%s =? %s" % (a, b))

    def test_make_headers(self):
        self.assertEqual(
            make_headers(accept_encoding=True),
            {'accept-encoding': 'gzip,deflate'})

        self.assertEqual(
            make_headers(accept_encoding='foo,bar'),
            {'accept-encoding': 'foo,bar'})

        self.assertEqual(
            make_headers(accept_encoding=['foo', 'bar']),
            {'accept-encoding': 'foo,bar'})

        self.assertEqual(
            make_headers(accept_encoding=True, user_agent='banana'),
            {'accept-encoding': 'gzip,deflate', 'user-agent': 'banana'})

        self.assertEqual(
            make_headers(user_agent='banana'),
            {'user-agent': 'banana'})

    def test_max_connections(self):
        pool = HTTPConnectionPool(host='localhost', maxsize=1, block=True)

        pool._get_conn(timeout=0.01)

        try:
            pool._get_conn(timeout=0.01)
            self.fail("Managed to get a connection without EmptyPoolError")
        except EmptyPoolError:
            pass

        try:
            pool.get_url('/', pool_timeout=0.01)
            self.fail("Managed to get a connection without EmptyPoolError")
        except EmptyPoolError:
            pass

        self.assertEqual(pool.num_connections, 1)

    def test_recovery_when_server_closes_connection(self):
        # Does the pool work seamlessly if an open connection in the
        # connection pool gets hung up on by the server, then reaches
        # the front of the queue again?

        def server(listener):
            for i in 0, 1:
                sock = listener.accept()[0]
                read_request(sock)
                body = 'Response %d' % i
                sock.send('HTTP/1.1 200 OK\r\n'
                          'Content-Type: text/plain\r\n'
                          'Content-Length: %d\r\n'
                          '\r\n'
                          '%s' % (len(body), body))
                sock.close()  # simulate a server timing out, closing socket
                done_closing.set()  # let the test know it can proceed

        done_closing = Event()
        address = start_server(server)
        pool = HTTPConnectionPool(*address)

        response = pool.request('GET', '/', retries=0)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, 'Response 0')

        done_closing.wait()  # wait until the socket in our pool gets closed

        response = pool.request('GET', '/', retries=0)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, 'Response 1')

# Prepare to serve HTTP on localhost.

def read_request(sock):
    """Read `sock` until a double CR-LF, and return the data received."""
    s = ''
    while not s.endswith('\r\n\r\n'):
        s += sock.recv(65536)
    return s

def start_server(server_function):
    """Create a listening server socket and publish its port on a queue."""

    def server_thread():
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        address = sock.getsockname()
        sock.listen(1)  # Once listen() returns, the server socket is ready
        q.put(address)     # ... so we can safely tell the client to use it now
        server_function(sock)

    q = Queue()
    t = Thread(target=server_thread)
    t.daemon = True
    t.start()
    return q.get()  # Wait until the server has started up, then return.

# "python -m" command line support:

if __name__ == '__main__':
    unittest.main()

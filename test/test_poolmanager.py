import unittest

from urllib3.connectionpool import port_by_scheme
from urllib3.poolmanager import PoolManager
from urllib3 import connection_from_url

from threadserver import read_request, start_server

class TestPoolManager(unittest.TestCase):
    def test_same_url(self):
        # Convince ourselves that normally we don't get the same object
        conn1 = connection_from_url('http://localhost:8081/foo')
        conn2 = connection_from_url('http://localhost:8081/bar')

        self.assertNotEqual(conn1, conn2)

        # Now try again using the PoolManager
        p = PoolManager(1)

        conn1 = p.connection_from_url('http://localhost:8081/foo')
        conn2 = p.connection_from_url('http://localhost:8081/bar')

        self.assertEqual(conn1, conn2)

    def test_many_urls(self):
        urls = [
            "http://localhost:8081/foo",
            "http://www.google.com/mail",
            "http://localhost:8081/bar",
            "https://www.google.com/",
            "https://www.google.com/mail",
            "http://yahoo.com",
            "http://bing.com",
            "http://yahoo.com/",
        ]

        connections = set()

        p = PoolManager(10)

        for url in urls:
            conn = p.connection_from_url(url)
            connections.add(conn)

        self.assertEqual(len(connections), 5)

    def test_request_survives_missing_port_number(self):
        # Can a URL that lacks an explicit port like ':80' succeed, or
        # will all such URLs fail with an error?

        def server(listener):
            sock = listener.accept()[0]
            read_request(sock)
            sock.send('HTTP/1.1 200 OK\r\n'
                      'Content-Type: text/plain\r\n'
                      'Content-Length: 8\r\n'
                      '\r\n'
                      'Inspire.')
            sock.close()

        # By globally adjusting `port_by_scheme` we pretend for a moment
        # that HTTP's default port is not 80, but is the port at which
        # our test server happens to be listening.

        p = PoolManager()
        host, port = start_server(server)
        port_by_scheme['http'] = port
        try:
            response = p.request('GET', 'http://%s/' % host, retries=0)
        finally:
            port_by_scheme['http'] = 80
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, 'Inspire.')


if __name__ == '__main__':
    unittest.main()

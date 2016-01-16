# -*- coding: utf-8 -*-

from urllib3 import HTTPConnectionPool
from dummyserver.testcase import SocketDummyServerTestCase

from .. import onlyPy2, onlyPy3


class TestChunkedTransfer(SocketDummyServerTestCase):
    def _start_chunked_handler(self):
        self.buffer = b''

        def socket_handler(listener):
            sock = listener.accept()[0]

            while not self.buffer.endswith(b'\r\n0\r\n\r\n'):
                self.buffer += sock.recv(65536)

            sock.send(
               b'HTTP/1.1 200 OK\r\n'
               b'Content-type: text/plain\r\n'
               b'Content-Length: 0\r\n'
               b'\r\n')
            sock.close()

        self._start_server(socket_handler)

    def test_chunks(self):
        self._start_chunked_handler()
        chunks = ['foo', 'bar', '', 'bazzzzzz']
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        r = pool.urlopen('GET', '/', chunks, headers=dict(DNT='1'), chunked=True)

        self.assertTrue(b'Transfer-Encoding' in self.buffer)
        body = self.buffer.split(b'\r\n\r\n', 1)[1]
        lines = body.split(b'\r\n')
        # Empty chunks should have been skipped, as this could not be distinguished
        # from terminating the transmission
        for i, chunk in enumerate([c for c in chunks if c]):
            self.assertEqual(lines[i * 2], str(len(chunk)).encode('utf-8'))
            self.assertEqual(lines[i * 2 + 1], chunk.encode('utf-8'))

    def _test_body(self, data):
        self._start_chunked_handler()
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        r = pool.urlopen('GET', '/', data, chunked=True)
        header, body = self.buffer.split(b'\r\n\r\n', 1)

        self.assertTrue(b'Transfer-Encoding: chunked' in header.split(b'\r\n'))
        if data:
            self.assertTrue(b'\r\n' + data.encode('utf-8') + b'\r\n' in body)
            self.assertTrue(body.endswith(b'\r\n0\r\n\r\n'))
        else:
            self.assertEqual(body, b'0\r\n\r\n')
        return header, body

    def test_bytestring_body(self):
        self._test_body(b'thisshouldbeonechunk')

    @onlyPy2
    def test_unicode_body(self):
        self._test_body(u'thisshouldbeonechunk äöüß')

    @onlyPy3
    def test_unidoce_body_py3(self):
        self._test_body('thisshouldbeonechunk äöüß')

    def test_empty_body(self):
        header, body = self._test_body(None)

    def test_empty_string_body(self):
        header, body = self._test_body('')

    def test_empty_iterable_body(self):
        header, body = self._test_body([])

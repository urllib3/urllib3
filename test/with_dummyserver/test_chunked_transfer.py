# -*- coding: utf-8 -*-

from urllib3 import HTTPConnectionPool
from urllib3.packages import six
from dummyserver.testcase import SocketDummyServerTestCase


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
        chunks = ['foo', 'bar', '', 'bazzzzzzzzzzzzzzzzzzzzzz']
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        r = pool.urlopen('GET', '/', chunks, headers=dict(DNT='1'), chunked=True)

        self.assertTrue(b'Transfer-Encoding' in self.buffer)
        body = self.buffer.split(b'\r\n\r\n', 1)[1]
        lines = body.split(b'\r\n')
        # Empty chunks should have been skipped, as this could not be distinguished
        # from terminating the transmission
        for i, chunk in enumerate([c for c in chunks if c]):
            self.assertEqual(lines[i * 2], hex(len(chunk))[2:].encode('utf-8'))
            self.assertEqual(lines[i * 2 + 1], chunk.encode('utf-8'))

    def _test_body(self, data):
        self._start_chunked_handler()
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        r = pool.urlopen('GET', '/', data, chunked=True)
        header, body = self.buffer.split(b'\r\n\r\n', 1)

        self.assertTrue(b'Transfer-Encoding: chunked' in header.split(b'\r\n'))
        if data:
            bdata = data if isinstance(data, six.binary_type) else data.encode('utf-8')
            self.assertTrue(b'\r\n' + bdata + b'\r\n' in body)
            self.assertTrue(body.endswith(b'\r\n0\r\n\r\n'))

            len_str = body.split(b'\r\n', 1)[0]
            stated_len = int(len_str, 16)
            self.assertEqual(stated_len, len(bdata))
        else:
            self.assertEqual(body, b'0\r\n\r\n')

    def test_bytestring_body(self):
        self._test_body(b'thisshouldbeonechunk\r\nasdf')

    def test_unicode_body(self):
        # Define u'thisshouldbeonechunk\r\näöüß' in a way, so that python3.1
        # does not suffer a syntax error
        chunk = b'thisshouldbeonechunk\r\n\xc3\xa4\xc3\xb6\xc3\xbc\xc3\x9f'.decode('utf-8')
        self._test_body(chunk)

    def test_empty_body(self):
        self._test_body(None)

    def test_empty_string_body(self):
        self._test_body('')

    def test_empty_iterable_body(self):
        self._test_body([])

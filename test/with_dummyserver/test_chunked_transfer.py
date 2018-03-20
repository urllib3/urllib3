# -*- coding: utf-8 -*-

import pytest

from urllib3 import HTTPConnectionPool
from urllib3.exceptions import InvalidBodyError
from urllib3.packages import six
from dummyserver.testcase import SocketDummyServerTestCase


class TestChunkedTransfer(SocketDummyServerTestCase):
    def start_chunked_handler(self):
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

    @pytest.mark.skip
    def test_chunks(self):
        self.start_chunked_handler()
        chunks = [b'foo', b'bar', b'', b'bazzzzzzzzzzzzzzzzzzzzzz']
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        pool.urlopen('GET', '/', chunks, headers=dict(DNT='1'))
        self.addCleanup(pool.close)

        self.assertTrue(b'transfer-encoding' in self.buffer)
        body = self.buffer.split(b'\r\n\r\n', 1)[1]
        lines = body.split(b'\r\n')
        # Empty chunks should have been skipped, as this could not be distinguished
        # from terminating the transmission
        for i, chunk in enumerate([c for c in chunks if c]):
            self.assertEqual(lines[i * 2], hex(len(chunk))[2:].encode('utf-8'))
            self.assertEqual(lines[i * 2 + 1], chunk)

    def _test_body(self, data):
        self.start_chunked_handler()
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)

        pool.urlopen('GET', '/', data)
        header, body = self.buffer.split(b'\r\n\r\n', 1)

        self.assertTrue(b'transfer-encoding: chunked' in header.split(b'\r\n'))
        if data:
            bdata = data if isinstance(data, six.binary_type) else data.encode('utf-8')
            self.assertTrue(b'\r\n' + bdata + b'\r\n' in body)
            self.assertTrue(body.endswith(b'\r\n0\r\n\r\n'))

            len_str = body.split(b'\r\n', 1)[0]
            stated_len = int(len_str, 16)
            self.assertEqual(stated_len, len(bdata))
        else:
            self.assertEqual(body, b'0\r\n\r\n')

    @pytest.mark.skip
    def test_bytestring_body(self):
        self._test_body(b'thisshouldbeonechunk\r\nasdf')

    @pytest.mark.skip
    def test_unicode_body(self):
        # Unicode bodies are not supported.
        chunk = u'thisshouldbeonechunk\r\näöüß'
        self.assertRaises(InvalidBodyError, self._test_body, chunk)

    @pytest.mark.skip
    def test_empty_string_body(self):
        self._test_body(b'')

    @pytest.mark.skip
    def test_empty_iterable_body(self):
        self._test_body([])

    @pytest.mark.skip
    def test_removes_duplicate_host_header(self):
        self.start_chunked_handler()
        chunks = [b'foo', b'bar', b'', b'bazzzzzzzzzzzzzzzzzzzzzz']
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        pool.urlopen(
            'GET', '/', chunks, headers={'Host': 'test.org'}
        )

        header_block = self.buffer.split(b'\r\n\r\n', 1)[0].lower()
        header_lines = header_block.split(b'\r\n')[1:]

        host_headers = [x for x in header_lines if x.startswith(b'host')]
        self.assertEqual(len(host_headers), 1)

    @pytest.mark.skip
    def test_provides_default_host_header(self):
        self.start_chunked_handler()
        chunks = [b'foo', b'bar', b'', b'bazzzzzzzzzzzzzzzzzzzzzz']
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        pool.urlopen('GET', '/', chunks)

        header_block = self.buffer.split(b'\r\n\r\n', 1)[0].lower()
        header_lines = header_block.split(b'\r\n')[1:]

        host_headers = [x for x in header_lines if x.startswith(b'host')]
        self.assertEqual(len(host_headers), 1)

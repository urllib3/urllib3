from urllib3 import HTTPConnectionPool
from urllib3._collections import HTTPHeaderDict
from urllib3.response import httplib

from dummyserver.testcase import SocketDummyServerTestCase
from nose.plugins.skip import SkipTest
from .. import onlyPy3, LogRecorder

try:
    from mimetools import Message as MimeToolMessage
except ImportError:
    class MimeToolMessage(object):
        pass


class TestHeaders(SocketDummyServerTestCase):

    @onlyPy3
    def test_httplib_headers_case_insensitive(self):
        self.start_response_handler(
           b'HTTP/1.1 200 OK\r\n'
           b'Content-Length: 0\r\n'
           b'Content-type: text/plain\r\n'
           b'\r\n'
        )
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        HEADERS = {'Content-Length': '0', 'Content-type': 'text/plain'}
        r = pool.request('GET', '/')
        self.assertEqual(HEADERS, dict(r.headers.items()))  # to preserve case sensitivity

    def test_headers_are_sent_with_the_original_case(self):
        headers = {'foo': 'bar', 'bAz': 'quux'}
        parsed_headers = {}

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            headers_list = [header for header in buf.split(b'\r\n')[1:] if header]

            for header in headers_list:
                (key, value) = header.split(b': ')
                parsed_headers[key.decode()] = value.decode()

            # Send incomplete message (note Content-Length)
            sock.send((
                'HTTP/1.1 204 No Content\r\n'
                'Content-Length: 0\r\n'
                '\r\n').encode('utf-8'))

            sock.close()

        self._start_server(socket_handler)
        expected_headers = {'Accept-Encoding': 'identity',
                            'Host': '{0}:{1}'.format(self.host, self.port)}
        expected_headers.update(headers)

        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        pool.request('GET', '/', headers=HTTPHeaderDict(headers))
        self.assertEqual(expected_headers, parsed_headers)


class TestBrokenHeaders(SocketDummyServerTestCase):
    def setUp(self):
        if issubclass(httplib.HTTPMessage, MimeToolMessage):
            raise SkipTest('Header parsing errors not available')

        super(TestBrokenHeaders, self).setUp()

    def _test_broken_header_parsing(self, headers):
        self.start_response_handler((
           b'HTTP/1.1 200 OK\r\n'
           b'Content-Length: 0\r\n'
           b'Content-type: text/plain\r\n'
           ) + b'\r\n'.join(headers) + b'\r\n'
        )

        pool = HTTPConnectionPool(self.host, self.port, retries=False)

        with LogRecorder() as logs:
            pool.request('GET', '/')

        for record in logs:
            if 'Failed to parse headers' in record.msg and \
                    pool._absolute_url('/') == record.args[0]:
                return
        self.fail('Missing log about unparsed headers')

    def test_header_without_name(self):
        self._test_broken_header_parsing([
            b': Value\r\n',
            b'Another: Header\r\n',
        ])

    def test_header_without_name_or_value(self):
        self._test_broken_header_parsing([
            b':\r\n',
            b'Another: Header\r\n',
        ])

    def test_header_without_colon_or_value(self):
        self._test_broken_header_parsing([
            b'Broken Header',
            b'Another: Header',
        ])


class TestCookies(SocketDummyServerTestCase):

    def test_multi_setcookie(self):
        def multicookie_response_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            sock.send(b'HTTP/1.1 200 OK\r\n'
                      b'Set-Cookie: foo=1\r\n'
                      b'Set-Cookie: bar=1\r\n'
                      b'\r\n')
            sock.close()

        self._start_server(multicookie_response_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        r = pool.request('GET', '/', retries=0)
        self.assertEqual(r.headers, {'set-cookie': 'foo=1, bar=1'})
        self.assertEqual(r.headers.getlist('set-cookie'), ['foo=1', 'bar=1'])

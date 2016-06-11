import hashlib
import warnings
import logging
import unittest
import ssl
import socket
from itertools import chain

from mock import patch, Mock

from urllib3 import add_stderr_logger, disable_warnings
from urllib3.util.request import make_headers
from urllib3.util.timeout import Timeout
from urllib3.util.url import (
    get_host,
    parse_url,
    split_first,
    Url,
)
from urllib3.util.ssl_ import (
    resolve_cert_reqs,
    ssl_wrap_socket,
    _const_compare_digest_backport,
)
from urllib3.exceptions import (
    LocationParseError,
    TimeoutStateError,
    InsecureRequestWarning,
    SSLError,
    SNIMissingWarning,
)
from urllib3.util.connection import (
    allowed_gai_family,
    _has_ipv6
)
from urllib3.util import is_fp_closed, ssl_

from . import clear_warnings

# This number represents a time in seconds, it doesn't mean anything in
# isolation. Setting to a high-ish value to avoid conflicts with the smaller
# numbers used for timeouts
TIMEOUT_EPOCH = 1000

class TestUtil(unittest.TestCase):
    def test_get_host(self):
        url_host_map = {
            # Hosts
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
            'http://google.com/foo=http://bar:42/baz': ('http', 'google.com', None),
            'http://google.com?foo=http://bar:42/baz': ('http', 'google.com', None),
            'http://google.com#foo=http://bar:42/baz': ('http', 'google.com', None),

            # IPv4
            '173.194.35.7': ('http', '173.194.35.7', None),
            'http://173.194.35.7': ('http', '173.194.35.7', None),
            'http://173.194.35.7/test': ('http', '173.194.35.7', None),
            'http://173.194.35.7:80': ('http', '173.194.35.7', 80),
            'http://173.194.35.7:80/test': ('http', '173.194.35.7', 80),

            # IPv6
            '[2a00:1450:4001:c01::67]': ('http', '[2a00:1450:4001:c01::67]', None),
            'http://[2a00:1450:4001:c01::67]': ('http', '[2a00:1450:4001:c01::67]', None),
            'http://[2a00:1450:4001:c01::67]/test': ('http', '[2a00:1450:4001:c01::67]', None),
            'http://[2a00:1450:4001:c01::67]:80': ('http', '[2a00:1450:4001:c01::67]', 80),
            'http://[2a00:1450:4001:c01::67]:80/test': ('http', '[2a00:1450:4001:c01::67]', 80),

            # More IPv6 from http://www.ietf.org/rfc/rfc2732.txt
            'http://[FEDC:BA98:7654:3210:FEDC:BA98:7654:3210]:8000/index.html': ('http', '[FEDC:BA98:7654:3210:FEDC:BA98:7654:3210]', 8000),
            'http://[1080:0:0:0:8:800:200C:417A]/index.html': ('http', '[1080:0:0:0:8:800:200C:417A]', None),
            'http://[3ffe:2a00:100:7031::1]': ('http', '[3ffe:2a00:100:7031::1]', None),
            'http://[1080::8:800:200C:417A]/foo': ('http', '[1080::8:800:200C:417A]', None),
            'http://[::192.9.5.5]/ipng': ('http', '[::192.9.5.5]', None),
            'http://[::FFFF:129.144.52.38]:42/index.html': ('http', '[::FFFF:129.144.52.38]', 42),
            'http://[2010:836B:4179::836B:4179]': ('http', '[2010:836B:4179::836B:4179]', None),
        }
        for url, expected_host in url_host_map.items():
            returned_host = get_host(url)
            self.assertEqual(returned_host, expected_host)

    def test_invalid_host(self):
        # TODO: Add more tests
        invalid_host = [
            'http://google.com:foo',
            'http://::1/',
            'http://::1:80/',
        ]

        for location in invalid_host:
            self.assertRaises(LocationParseError, get_host, location)


    parse_url_host_map = {
        'http://google.com/mail': Url('http', host='google.com', path='/mail'),
        'http://google.com/mail/': Url('http', host='google.com', path='/mail/'),
        'http://google.com/mail': Url('http', host='google.com', path='mail'),
        'google.com/mail': Url(host='google.com', path='/mail'),
        'http://google.com/': Url('http', host='google.com', path='/'),
        'http://google.com': Url('http', host='google.com'),
        'http://google.com?foo': Url('http', host='google.com', path='', query='foo'),

        # Path/query/fragment
        '': Url(),
        '/': Url(path='/'),
        '#?/!google.com/?foo#bar': Url(path='', fragment='?/!google.com/?foo#bar'),
        '/foo': Url(path='/foo'),
        '/foo?bar=baz': Url(path='/foo', query='bar=baz'),
        '/foo?bar=baz#banana?apple/orange': Url(path='/foo', query='bar=baz', fragment='banana?apple/orange'),

        # Port
        'http://google.com/': Url('http', host='google.com', path='/'),
        'http://google.com:80/': Url('http', host='google.com', port=80, path='/'),
        'http://google.com:80': Url('http', host='google.com', port=80),

        # Auth
        'http://foo:bar@localhost/': Url('http', auth='foo:bar', host='localhost', path='/'),
        'http://foo@localhost/': Url('http', auth='foo', host='localhost', path='/'),
        'http://foo:bar@baz@localhost/': Url('http', auth='foo:bar@baz', host='localhost', path='/'),
        'http://@': Url('http', host=None, auth='')
    }

    non_round_tripping_parse_url_host_map = {
        # Path/query/fragment
        '?': Url(path='', query=''),
        '#': Url(path='', fragment=''),

        # Empty Port
        'http://google.com:': Url('http', host='google.com'),
        'http://google.com:/': Url('http', host='google.com', path='/'),

        }

    def test_parse_url(self):
        for url, expected_Url in chain(self.parse_url_host_map.items(), self.non_round_tripping_parse_url_host_map.items()):
            returned_Url = parse_url(url)
            self.assertEqual(returned_Url, expected_Url)

    def test_unparse_url(self):
        for url, expected_Url in self.parse_url_host_map.items():
            self.assertEqual(url, expected_Url.url)

    def test_parse_url_invalid_IPv6(self):
        self.assertRaises(ValueError, parse_url, '[::1')

    def test_Url_str(self):
        U = Url('http', host='google.com')
        self.assertEqual(str(U), U.url)

    def test_request_uri(self):
        url_host_map = {
            'http://google.com/mail': '/mail',
            'http://google.com/mail/': '/mail/',
            'http://google.com/': '/',
            'http://google.com': '/',
            '': '/',
            '/': '/',
            '?': '/?',
            '#': '/',
            '/foo?bar=baz': '/foo?bar=baz',
        }
        for url, expected_request_uri in url_host_map.items():
            returned_url = parse_url(url)
            self.assertEqual(returned_url.request_uri, expected_request_uri)

    def test_netloc(self):
        url_netloc_map = {
            'http://google.com/mail': 'google.com',
            'http://google.com:80/mail': 'google.com:80',
            'google.com/foobar': 'google.com',
            'google.com:12345': 'google.com:12345',
        }

        for url, expected_netloc in url_netloc_map.items():
            self.assertEqual(parse_url(url).netloc, expected_netloc)

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

        self.assertEqual(
            make_headers(keep_alive=True),
            {'connection': 'keep-alive'})

        self.assertEqual(
            make_headers(basic_auth='foo:bar'),
            {'authorization': 'Basic Zm9vOmJhcg=='})

        self.assertEqual(
            make_headers(proxy_basic_auth='foo:bar'),
            {'proxy-authorization': 'Basic Zm9vOmJhcg=='})

        self.assertEqual(
            make_headers(disable_cache=True),
            {'cache-control': 'no-cache'})

    def test_split_first(self):
        test_cases = {
            ('abcd', 'b'): ('a', 'cd', 'b'),
            ('abcd', 'cb'): ('a', 'cd', 'b'),
            ('abcd', ''): ('abcd', '', None),
            ('abcd', 'a'): ('', 'bcd', 'a'),
            ('abcd', 'ab'): ('', 'bcd', 'a'),
        }
        for input, expected in test_cases.items():
            output = split_first(*input)
            self.assertEqual(output, expected)

    def test_add_stderr_logger(self):
        handler = add_stderr_logger(level=logging.INFO) # Don't actually print debug
        logger = logging.getLogger('urllib3')
        self.assertTrue(handler in logger.handlers)

        logger.debug('Testing add_stderr_logger')
        logger.removeHandler(handler)

    def test_disable_warnings(self):
        with warnings.catch_warnings(record=True) as w:
            clear_warnings()
            warnings.warn('This is a test.', InsecureRequestWarning)
            self.assertEqual(len(w), 1)
            disable_warnings()
            warnings.warn('This is a test.', InsecureRequestWarning)
            self.assertEqual(len(w), 1)

    def _make_time_pass(self, seconds, timeout, time_mock):
        """ Make some time pass for the timeout object """
        time_mock.return_value = TIMEOUT_EPOCH
        timeout.start_connect()
        time_mock.return_value = TIMEOUT_EPOCH + seconds
        return timeout

    def test_invalid_timeouts(self):
        try:
            Timeout(total=-1)
            self.fail("negative value should throw exception")
        except ValueError as e:
            self.assertTrue('less than' in str(e))
        try:
            Timeout(connect=2, total=-1)
            self.fail("negative value should throw exception")
        except ValueError as e:
            self.assertTrue('less than' in str(e))

        try:
            Timeout(read=-1)
            self.fail("negative value should throw exception")
        except ValueError as e:
            self.assertTrue('less than' in str(e))

        # Booleans are allowed also by socket.settimeout and converted to the
        # equivalent float (1.0 for True, 0.0 for False)
        Timeout(connect=False, read=True)

        try:
            Timeout(read="foo")
            self.fail("string value should not be allowed")
        except ValueError as e:
            self.assertTrue('int or float' in str(e))


    @patch('urllib3.util.timeout.current_time')
    def test_timeout(self, current_time):
        timeout = Timeout(total=3)

        # make 'no time' elapse
        timeout = self._make_time_pass(seconds=0, timeout=timeout,
                                       time_mock=current_time)
        self.assertEqual(timeout.read_timeout, 3)
        self.assertEqual(timeout.connect_timeout, 3)

        timeout = Timeout(total=3, connect=2)
        self.assertEqual(timeout.connect_timeout, 2)

        timeout = Timeout()
        self.assertEqual(timeout.connect_timeout, Timeout.DEFAULT_TIMEOUT)

        # Connect takes 5 seconds, leaving 5 seconds for read
        timeout = Timeout(total=10, read=7)
        timeout = self._make_time_pass(seconds=5, timeout=timeout,
                                       time_mock=current_time)
        self.assertEqual(timeout.read_timeout, 5)

        # Connect takes 2 seconds, read timeout still 7 seconds
        timeout = Timeout(total=10, read=7)
        timeout = self._make_time_pass(seconds=2, timeout=timeout,
                                       time_mock=current_time)
        self.assertEqual(timeout.read_timeout, 7)

        timeout = Timeout(total=10, read=7)
        self.assertEqual(timeout.read_timeout, 7)

        timeout = Timeout(total=None, read=None, connect=None)
        self.assertEqual(timeout.connect_timeout, None)
        self.assertEqual(timeout.read_timeout, None)
        self.assertEqual(timeout.total, None)

        timeout = Timeout(5)
        self.assertEqual(timeout.total, 5)


    def test_timeout_str(self):
        timeout = Timeout(connect=1, read=2, total=3)
        self.assertEqual(str(timeout), "Timeout(connect=1, read=2, total=3)")
        timeout = Timeout(connect=1, read=None, total=3)
        self.assertEqual(str(timeout), "Timeout(connect=1, read=None, total=3)")


    @patch('urllib3.util.timeout.current_time')
    def test_timeout_elapsed(self, current_time):
        current_time.return_value = TIMEOUT_EPOCH
        timeout = Timeout(total=3)
        self.assertRaises(TimeoutStateError, timeout.get_connect_duration)

        timeout.start_connect()
        self.assertRaises(TimeoutStateError, timeout.start_connect)

        current_time.return_value = TIMEOUT_EPOCH + 2
        self.assertEqual(timeout.get_connect_duration(), 2)
        current_time.return_value = TIMEOUT_EPOCH + 37
        self.assertEqual(timeout.get_connect_duration(), 37)

    def test_resolve_cert_reqs(self):
        self.assertEqual(resolve_cert_reqs(None), ssl.CERT_NONE)
        self.assertEqual(resolve_cert_reqs(ssl.CERT_NONE), ssl.CERT_NONE)

        self.assertEqual(resolve_cert_reqs(ssl.CERT_REQUIRED), ssl.CERT_REQUIRED)
        self.assertEqual(resolve_cert_reqs('REQUIRED'), ssl.CERT_REQUIRED)
        self.assertEqual(resolve_cert_reqs('CERT_REQUIRED'), ssl.CERT_REQUIRED)

    def test_is_fp_closed_object_supports_closed(self):
        class ClosedFile(object):
            @property
            def closed(self):
                return True

        self.assertTrue(is_fp_closed(ClosedFile()))

    def test_is_fp_closed_object_has_none_fp(self):
        class NoneFpFile(object):
            @property
            def fp(self):
                return None

        self.assertTrue(is_fp_closed(NoneFpFile()))

    def test_is_fp_closed_object_has_fp(self):
        class FpFile(object):
            @property
            def fp(self):
                return True

        self.assertTrue(not is_fp_closed(FpFile()))

    def test_is_fp_closed_object_has_neither_fp_nor_closed(self):
        class NotReallyAFile(object):
            pass

        self.assertRaises(ValueError, is_fp_closed, NotReallyAFile())

    def test_ssl_wrap_socket_loads_the_cert_chain(self):
        socket = object()
        mock_context = Mock()
        ssl_wrap_socket(ssl_context=mock_context, sock=socket,
                        certfile='/path/to/certfile')

        mock_context.load_cert_chain.assert_called_once_with(
            '/path/to/certfile', None)

    def test_ssl_wrap_socket_loads_verify_locations(self):
        socket = object()
        mock_context = Mock()
        ssl_wrap_socket(ssl_context=mock_context, ca_certs='/path/to/pem',
                        sock=socket)
        mock_context.load_verify_locations.assert_called_once_with(
            '/path/to/pem', None)

    def test_ssl_wrap_socket_loads_certificate_directories(self):
        socket = object()
        mock_context = Mock()
        ssl_wrap_socket(ssl_context=mock_context, ca_cert_dir='/path/to/pems',
                        sock=socket)
        mock_context.load_verify_locations.assert_called_once_with(
            None, '/path/to/pems')

    def test_ssl_wrap_socket_with_no_sni(self):
        socket = object()
        mock_context = Mock()
        # Ugly preservation of original value
        HAS_SNI = ssl_.HAS_SNI
        ssl_.HAS_SNI = False
        ssl_wrap_socket(ssl_context=mock_context, sock=socket)
        mock_context.wrap_socket.assert_called_once_with(socket)
        ssl_.HAS_SNI = HAS_SNI

    def test_ssl_wrap_socket_with_no_sni_warns(self):
        socket = object()
        mock_context = Mock()
        # Ugly preservation of original value
        HAS_SNI = ssl_.HAS_SNI
        ssl_.HAS_SNI = False
        with patch('warnings.warn') as warn:
            ssl_wrap_socket(ssl_context=mock_context, sock=socket)
        mock_context.wrap_socket.assert_called_once_with(socket)
        ssl_.HAS_SNI = HAS_SNI
        self.assertTrue(warn.call_count >= 1)
        warnings = [call[0][1] for call in warn.call_args_list]
        self.assertTrue(SNIMissingWarning in warnings)

    def test_const_compare_digest_fallback(self):
        target = hashlib.sha256(b'abcdef').digest()
        self.assertTrue(_const_compare_digest_backport(target, target))

        prefix = target[:-1]
        self.assertFalse(_const_compare_digest_backport(target, prefix))

        suffix = target + b'0'
        self.assertFalse(_const_compare_digest_backport(target, suffix))

        incorrect = hashlib.sha256(b'xyz').digest()
        self.assertFalse(_const_compare_digest_backport(target, incorrect))

    def test_has_ipv6_disabled_on_compile(self):
        with patch('socket.has_ipv6', False):
            self.assertFalse(_has_ipv6('::1'))

    def test_has_ipv6_enabled_but_fails(self):
        with patch('socket.has_ipv6', True):
            with patch('socket.socket') as mock:
                instance = mock.return_value
                instance.bind = Mock(side_effect=Exception('No IPv6 here!'))
                self.assertFalse(_has_ipv6('::1'))

    def test_has_ipv6_enabled_and_working(self):
        with patch('socket.has_ipv6', True):
            with patch('socket.socket') as mock:
                instance = mock.return_value
                instance.bind.return_value = True
                self.assertTrue(_has_ipv6('::1'))

    def test_ip_family_ipv6_enabled(self):
        with patch('urllib3.util.connection.HAS_IPV6', True):
            self.assertEqual(allowed_gai_family(), socket.AF_UNSPEC)

    def test_ip_family_ipv6_disabled(self):
        with patch('urllib3.util.connection.HAS_IPV6', False):
            self.assertEqual(allowed_gai_family(), socket.AF_INET)

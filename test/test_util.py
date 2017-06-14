import hashlib
import warnings
import logging
import io
import ssl
import socket
from itertools import chain

from mock import patch, Mock
import pytest

from urllib3 import add_stderr_logger, disable_warnings
from urllib3.util.request import make_headers, rewind_body, _FAILEDTELL
from urllib3.util.retry import Retry
from urllib3.util.timeout import Timeout
from urllib3.util.url import (
    get_host,
    parse_url,
    split_first,
    Url,
)
from urllib3.util.ssl_ import (
    resolve_cert_reqs,
    resolve_ssl_version,
    ssl_wrap_socket,
    _const_compare_digest_backport,
)
from urllib3.exceptions import (
    LocationParseError,
    TimeoutStateError,
    InsecureRequestWarning,
    SNIMissingWarning,
    InvalidHeader,
    UnrewindableBodyError,
)
from urllib3.util.connection import (
    allowed_gai_family,
    _has_ipv6
)
from urllib3.util import is_fp_closed, ssl_
from urllib3.packages import six

from . import clear_warnings

# This number represents a time in seconds, it doesn't mean anything in
# isolation. Setting to a high-ish value to avoid conflicts with the smaller
# numbers used for timeouts
TIMEOUT_EPOCH = 1000


class TestUtil(object):

    url_host_map = [
        # Hosts
        ('http://google.com/mail', ('http', 'google.com', None)),
        ('http://google.com/mail/', ('http', 'google.com', None)),
        ('google.com/mail', ('http', 'google.com', None)),
        ('http://google.com/', ('http', 'google.com', None)),
        ('http://google.com', ('http', 'google.com', None)),
        ('http://www.google.com', ('http', 'www.google.com', None)),
        ('http://mail.google.com', ('http', 'mail.google.com', None)),
        ('http://google.com:8000/mail/', ('http', 'google.com', 8000)),
        ('http://google.com:8000', ('http', 'google.com', 8000)),
        ('https://google.com', ('https', 'google.com', None)),
        ('https://google.com:8000', ('https', 'google.com', 8000)),
        ('http://user:password@127.0.0.1:1234', ('http', '127.0.0.1', 1234)),
        ('http://google.com/foo=http://bar:42/baz', ('http', 'google.com', None)),
        ('http://google.com?foo=http://bar:42/baz', ('http', 'google.com', None)),
        ('http://google.com#foo=http://bar:42/baz', ('http', 'google.com', None)),

        # IPv4
        ('173.194.35.7', ('http', '173.194.35.7', None)),
        ('http://173.194.35.7', ('http', '173.194.35.7', None)),
        ('http://173.194.35.7/test', ('http', '173.194.35.7', None)),
        ('http://173.194.35.7:80', ('http', '173.194.35.7', 80)),
        ('http://173.194.35.7:80/test', ('http', '173.194.35.7', 80)),

        # IPv6
        ('[2a00:1450:4001:c01::67]', ('http', '[2a00:1450:4001:c01::67]', None)),
        ('http://[2a00:1450:4001:c01::67]', ('http', '[2a00:1450:4001:c01::67]', None)),
        ('http://[2a00:1450:4001:c01::67]/test', ('http', '[2a00:1450:4001:c01::67]', None)),
        ('http://[2a00:1450:4001:c01::67]:80', ('http', '[2a00:1450:4001:c01::67]', 80)),
        ('http://[2a00:1450:4001:c01::67]:80/test', ('http', '[2a00:1450:4001:c01::67]', 80)),

        # More IPv6 from http://www.ietf.org/rfc/rfc2732.txt
        ('http://[fedc:ba98:7654:3210:fedc:ba98:7654:3210]:8000/index.html', (
            'http', '[fedc:ba98:7654:3210:fedc:ba98:7654:3210]', 8000)),
        ('http://[1080:0:0:0:8:800:200c:417a]/index.html', (
            'http', '[1080:0:0:0:8:800:200c:417a]', None)),
        ('http://[3ffe:2a00:100:7031::1]', ('http', '[3ffe:2a00:100:7031::1]', None)),
        ('http://[1080::8:800:200c:417a]/foo', ('http', '[1080::8:800:200c:417a]', None)),
        ('http://[::192.9.5.5]/ipng', ('http', '[::192.9.5.5]', None)),
        ('http://[::ffff:129.144.52.38]:42/index.html', ('http', '[::ffff:129.144.52.38]', 42)),
        ('http://[2010:836b:4179::836b:4179]', ('http', '[2010:836b:4179::836b:4179]', None)),

        # Hosts
        ('HTTP://GOOGLE.COM/mail/', ('http', 'google.com', None)),
        ('GOogle.COM/mail', ('http', 'google.com', None)),
        ('HTTP://GoOgLe.CoM:8000/mail/', ('http', 'google.com', 8000)),
        ('HTTP://user:password@EXAMPLE.COM:1234', ('http', 'example.com', 1234)),
        ('173.194.35.7', ('http', '173.194.35.7', None)),
        ('HTTP://173.194.35.7', ('http', '173.194.35.7', None)),
        ('HTTP://[2a00:1450:4001:c01::67]:80/test', ('http', '[2a00:1450:4001:c01::67]', 80)),
        ('HTTP://[FEDC:BA98:7654:3210:FEDC:BA98:7654:3210]:8000/index.html', (
            'http', '[fedc:ba98:7654:3210:fedc:ba98:7654:3210]', 8000)),
        ('HTTPS://[1080:0:0:0:8:800:200c:417A]/index.html', (
            'https', '[1080:0:0:0:8:800:200c:417a]', None)),
        ('abOut://eXamPlE.com?info=1', ('about', 'eXamPlE.com', None)),
        ('http+UNIX://%2fvar%2frun%2fSOCKET/path', (
            'http+unix', '%2fvar%2frun%2fSOCKET', None)),
    ]

    @pytest.mark.parametrize('url, expected_host', url_host_map)
    def test_get_host(self, url, expected_host):
        returned_host = get_host(url)
        assert returned_host == expected_host

    # TODO: Add more tests
    @pytest.mark.parametrize('location', [
        'http://google.com:foo',
        'http://::1/',
        'http://::1:80/',
        'http://google.com:-80',
        six.u('http://google.com:\xb2\xb2'),  # \xb2 = ^2
    ])
    def test_invalid_host(self, location):
        with pytest.raises(LocationParseError):
            get_host(location)

    @pytest.mark.parametrize('url, expected_normalized_url', [
        ('HTTP://GOOGLE.COM/MAIL/', 'http://google.com/MAIL/'),
        ('HTTP://JeremyCline:Hunter2@Example.com:8080/',
         'http://JeremyCline:Hunter2@example.com:8080/'),
        ('HTTPS://Example.Com/?Key=Value', 'https://example.com/?Key=Value'),
        ('Https://Example.Com/#Fragment', 'https://example.com/#Fragment'),
    ])
    def test_parse_url_normalization(self, url, expected_normalized_url):
        """Assert parse_url normalizes the scheme/host, and only the scheme/host"""
        actual_normalized_url = parse_url(url).url
        assert actual_normalized_url == expected_normalized_url

    parse_url_host_map = [
        ('http://google.com/mail', Url('http', host='google.com', path='/mail')),
        ('http://google.com/mail/', Url('http', host='google.com', path='/mail/')),
        ('http://google.com/mail', Url('http', host='google.com', path='mail')),
        ('google.com/mail', Url(host='google.com', path='/mail')),
        ('http://google.com/', Url('http', host='google.com', path='/')),
        ('http://google.com', Url('http', host='google.com')),
        ('http://google.com?foo', Url('http', host='google.com', path='', query='foo')),

        # Path/query/fragment
        ('', Url()),
        ('/', Url(path='/')),
        ('#?/!google.com/?foo#bar', Url(path='', fragment='?/!google.com/?foo#bar')),
        ('/foo', Url(path='/foo')),
        ('/foo?bar=baz', Url(path='/foo', query='bar=baz')),
        ('/foo?bar=baz#banana?apple/orange', Url(path='/foo',
                                                 query='bar=baz',
                                                 fragment='banana?apple/orange')),

        # Port
        ('http://google.com/', Url('http', host='google.com', path='/')),
        ('http://google.com:80/', Url('http', host='google.com', port=80, path='/')),
        ('http://google.com:80', Url('http', host='google.com', port=80)),

        # Auth
        ('http://foo:bar@localhost/', Url('http', auth='foo:bar', host='localhost', path='/')),
        ('http://foo@localhost/', Url('http', auth='foo', host='localhost', path='/')),
        ('http://foo:bar@baz@localhost/', Url('http',
                                              auth='foo:bar@baz',
                                              host='localhost',
                                              path='/')),
        ('http://@', Url('http', host=None, auth=''))
    ]

    non_round_tripping_parse_url_host_map = [
        # Path/query/fragment
        ('?', Url(path='', query='')),
        ('#', Url(path='', fragment='')),

        # Empty Port
        ('http://google.com:', Url('http', host='google.com')),
        ('http://google.com:/', Url('http', host='google.com', path='/')),
    ]

    @pytest.mark.parametrize(
        'url, expected_url',
        chain(parse_url_host_map, non_round_tripping_parse_url_host_map)
    )
    def test_parse_url(self, url, expected_url):
        returned_url = parse_url(url)
        assert returned_url == expected_url

    @pytest.mark.parametrize('url, expected_url', parse_url_host_map)
    def test_unparse_url(self, url, expected_url):
        assert url == expected_url.url

    def test_parse_url_invalid_IPv6(self):
        with pytest.raises(ValueError):
            parse_url('[::1')

    def test_Url_str(self):
        U = Url('http', host='google.com')
        assert str(U) == U.url

    request_uri_map = [
        ('http://google.com/mail', '/mail'),
        ('http://google.com/mail/', '/mail/'),
        ('http://google.com/', '/'),
        ('http://google.com', '/'),
        ('', '/'),
        ('/', '/'),
        ('?', '/?'),
        ('#', '/'),
        ('/foo?bar=baz', '/foo?bar=baz'),
    ]

    @pytest.mark.parametrize('url, expected_request_uri', request_uri_map)
    def test_request_uri(self, url, expected_request_uri):
        returned_url = parse_url(url)
        assert returned_url.request_uri == expected_request_uri

    url_netloc_map = [
        ('http://google.com/mail', 'google.com'),
        ('http://google.com:80/mail', 'google.com:80'),
        ('google.com/foobar', 'google.com'),
        ('google.com:12345', 'google.com:12345'),
    ]

    @pytest.mark.parametrize('url, expected_netloc', url_netloc_map)
    def test_netloc(self, url, expected_netloc):
        assert parse_url(url).netloc == expected_netloc

    @pytest.mark.parametrize('kwargs, expected', [
        ({'accept_encoding': True},
         {'accept-encoding': 'gzip,deflate'}),
        ({'accept_encoding': 'foo,bar'},
         {'accept-encoding': 'foo,bar'}),
        ({'accept_encoding': ['foo', 'bar']},
         {'accept-encoding': 'foo,bar'}),
        ({'accept_encoding': True, 'user_agent': 'banana'},
         {'accept-encoding': 'gzip,deflate', 'user-agent': 'banana'}),
        ({'user_agent': 'banana'},
         {'user-agent': 'banana'}),
        ({'keep_alive': True},
         {'connection': 'keep-alive'}),
        ({'basic_auth': 'foo:bar'},
         {'authorization': 'Basic Zm9vOmJhcg=='}),
        ({'proxy_basic_auth': 'foo:bar'},
         {'proxy-authorization': 'Basic Zm9vOmJhcg=='}),
        ({'disable_cache': True},
         {'cache-control': 'no-cache'}),
    ])
    def test_make_headers(self, kwargs, expected):
        assert make_headers(**kwargs) == expected

    def test_rewind_body(self):
        body = io.BytesIO(b'test data')
        assert body.read() == b'test data'

        # Assert the file object has been consumed
        assert body.read() == b''

        # Rewind it back to just be b'data'
        rewind_body(body, 5)
        assert body.read() == b'data'

    def test_rewind_body_failed_tell(self):
        body = io.BytesIO(b'test data')
        body.read()  # Consume body

        # Simulate failed tell()
        body_pos = _FAILEDTELL
        with pytest.raises(UnrewindableBodyError):
            rewind_body(body, body_pos)

    def test_rewind_body_bad_position(self):
        body = io.BytesIO(b'test data')
        body.read()  # Consume body

        # Pass non-integer position
        with pytest.raises(ValueError):
            rewind_body(body, body_pos=None)
        with pytest.raises(ValueError):
            rewind_body(body, body_pos=object())

    def test_rewind_body_failed_seek(self):
        class BadSeek():

            def seek(self, pos, offset=0):
                raise IOError

        with pytest.raises(UnrewindableBodyError):
            rewind_body(BadSeek(), body_pos=2)

    @pytest.mark.parametrize('input, expected', [
        (('abcd', 'b'),  ('a', 'cd', 'b')),
        (('abcd', 'cb'), ('a', 'cd', 'b')),
        (('abcd', ''),   ('abcd', '', None)),
        (('abcd', 'a'),  ('', 'bcd', 'a')),
        (('abcd', 'ab'), ('', 'bcd', 'a')),
    ])
    def test_split_first(self, input, expected):
        output = split_first(*input)
        assert output == expected

    def test_add_stderr_logger(self):
        handler = add_stderr_logger(level=logging.INFO)  # Don't actually print debug
        logger = logging.getLogger('urllib3')
        assert handler in logger.handlers

        logger.debug('Testing add_stderr_logger')
        logger.removeHandler(handler)

    def test_disable_warnings(self):
        with warnings.catch_warnings(record=True) as w:
            clear_warnings()
            warnings.warn('This is a test.', InsecureRequestWarning)
            assert len(w) == 1
            disable_warnings()
            warnings.warn('This is a test.', InsecureRequestWarning)
            assert len(w) == 1

    def _make_time_pass(self, seconds, timeout, time_mock):
        """ Make some time pass for the timeout object """
        time_mock.return_value = TIMEOUT_EPOCH
        timeout.start_connect()
        time_mock.return_value = TIMEOUT_EPOCH + seconds
        return timeout

    @pytest.mark.parametrize('kwargs, message', [
        ({'total': -1},                 'less than'),
        ({'connect': 2, 'total': -1},   'less than'),
        ({'read': -1},                  'less than'),
        ({'connect': False},            'cannot be a boolean'),
        ({'read': True},                'cannot be a boolean'),
        ({'connect': 0},                'less than or equal'),
        ({'read': 'foo'},               'int, float or None')
    ])
    def test_invalid_timeouts(self, kwargs, message):
        with pytest.raises(ValueError) as e:
            Timeout(**kwargs)
        assert message in str(e.value)

    @patch('urllib3.util.timeout.current_time')
    def test_timeout(self, current_time):
        timeout = Timeout(total=3)

        # make 'no time' elapse
        timeout = self._make_time_pass(seconds=0, timeout=timeout,
                                       time_mock=current_time)
        assert timeout.read_timeout == 3
        assert timeout.connect_timeout == 3

        timeout = Timeout(total=3, connect=2)
        assert timeout.connect_timeout == 2

        timeout = Timeout()
        assert timeout.connect_timeout == Timeout.DEFAULT_TIMEOUT

        # Connect takes 5 seconds, leaving 5 seconds for read
        timeout = Timeout(total=10, read=7)
        timeout = self._make_time_pass(seconds=5, timeout=timeout,
                                       time_mock=current_time)
        assert timeout.read_timeout == 5

        # Connect takes 2 seconds, read timeout still 7 seconds
        timeout = Timeout(total=10, read=7)
        timeout = self._make_time_pass(seconds=2, timeout=timeout,
                                       time_mock=current_time)
        assert timeout.read_timeout == 7

        timeout = Timeout(total=10, read=7)
        assert timeout.read_timeout == 7

        timeout = Timeout(total=None, read=None, connect=None)
        assert timeout.connect_timeout is None
        assert timeout.read_timeout is None
        assert timeout.total is None

        timeout = Timeout(5)
        assert timeout.total == 5

    def test_timeout_str(self):
        timeout = Timeout(connect=1, read=2, total=3)
        assert str(timeout) == "Timeout(connect=1, read=2, total=3)"
        timeout = Timeout(connect=1, read=None, total=3)
        assert str(timeout) == "Timeout(connect=1, read=None, total=3)"

    @patch('urllib3.util.timeout.current_time')
    def test_timeout_elapsed(self, current_time):
        current_time.return_value = TIMEOUT_EPOCH
        timeout = Timeout(total=3)
        with pytest.raises(TimeoutStateError):
            timeout.get_connect_duration()

        timeout.start_connect()
        with pytest.raises(TimeoutStateError):
            timeout.start_connect()

        current_time.return_value = TIMEOUT_EPOCH + 2
        assert timeout.get_connect_duration() == 2
        current_time.return_value = TIMEOUT_EPOCH + 37
        assert timeout.get_connect_duration() == 37

    @pytest.mark.parametrize('candidate, requirements', [
        (None, ssl.CERT_NONE),
        (ssl.CERT_NONE, ssl.CERT_NONE),
        (ssl.CERT_REQUIRED, ssl.CERT_REQUIRED),
        ('REQUIRED', ssl.CERT_REQUIRED),
        ('CERT_REQUIRED', ssl.CERT_REQUIRED),
    ])
    def test_resolve_cert_reqs(self, candidate, requirements):
        assert resolve_cert_reqs(candidate) == requirements

    @pytest.mark.parametrize('candidate, version', [
        (ssl.PROTOCOL_TLSv1, ssl.PROTOCOL_TLSv1),
        ("PROTOCOL_TLSv1", ssl.PROTOCOL_TLSv1),
        ("TLSv1", ssl.PROTOCOL_TLSv1),
        (ssl.PROTOCOL_SSLv23, ssl.PROTOCOL_SSLv23),
    ])
    def test_resolve_ssl_version(self, candidate, version):
        assert resolve_ssl_version(candidate) == version

    def test_is_fp_closed_object_supports_closed(self):
        class ClosedFile(object):
            @property
            def closed(self):
                return True

        assert is_fp_closed(ClosedFile())

    def test_is_fp_closed_object_has_none_fp(self):
        class NoneFpFile(object):
            @property
            def fp(self):
                return None

        assert is_fp_closed(NoneFpFile())

    def test_is_fp_closed_object_has_fp(self):
        class FpFile(object):
            @property
            def fp(self):
                return True

        assert not is_fp_closed(FpFile())

    def test_is_fp_closed_object_has_neither_fp_nor_closed(self):
        class NotReallyAFile(object):
            pass

        with pytest.raises(ValueError):
            is_fp_closed(NotReallyAFile())

    def test_ssl_wrap_socket_loads_the_cert_chain(self):
        socket = object()
        mock_context = Mock()
        ssl_wrap_socket(ssl_context=mock_context, sock=socket,
                        certfile='/path/to/certfile')

        mock_context.load_cert_chain.assert_called_once_with(
            '/path/to/certfile', None
        )

    @patch('urllib3.util.ssl_.create_urllib3_context')
    def test_ssl_wrap_socket_creates_new_context(self,
                                                 create_urllib3_context):
        socket = object()
        ssl_wrap_socket(sock=socket, cert_reqs='CERT_REQUIRED')

        create_urllib3_context.assert_called_once_with(
            None, 'CERT_REQUIRED', ciphers=None
        )

    def test_ssl_wrap_socket_loads_verify_locations(self):
        socket = object()
        mock_context = Mock()
        ssl_wrap_socket(ssl_context=mock_context, ca_certs='/path/to/pem',
                        sock=socket)
        mock_context.load_verify_locations.assert_called_once_with(
            '/path/to/pem', None
        )

    def test_ssl_wrap_socket_loads_certificate_directories(self):
        socket = object()
        mock_context = Mock()
        ssl_wrap_socket(ssl_context=mock_context, ca_cert_dir='/path/to/pems',
                        sock=socket)
        mock_context.load_verify_locations.assert_called_once_with(
            None, '/path/to/pems'
        )

    def test_ssl_wrap_socket_with_no_sni_warns(self):
        socket = object()
        mock_context = Mock()
        # Ugly preservation of original value
        HAS_SNI = ssl_.HAS_SNI
        ssl_.HAS_SNI = False
        try:
            with patch('warnings.warn') as warn:
                ssl_wrap_socket(ssl_context=mock_context, sock=socket)
            mock_context.wrap_socket.assert_called_once_with(socket)
            assert warn.call_count >= 1
            warnings = [call[0][1] for call in warn.call_args_list]
            assert SNIMissingWarning in warnings
        finally:
            ssl_.HAS_SNI = HAS_SNI

    def test_const_compare_digest_fallback(self):
        target = hashlib.sha256(b'abcdef').digest()
        assert _const_compare_digest_backport(target, target)

        prefix = target[:-1]
        assert not _const_compare_digest_backport(target, prefix)

        suffix = target + b'0'
        assert not _const_compare_digest_backport(target, suffix)

        incorrect = hashlib.sha256(b'xyz').digest()
        assert not _const_compare_digest_backport(target, incorrect)

    def test_has_ipv6_disabled_on_compile(self):
        with patch('socket.has_ipv6', False):
            assert not _has_ipv6('::1')

    def test_has_ipv6_enabled_but_fails(self):
        with patch('socket.has_ipv6', True):
            with patch('socket.socket') as mock:
                instance = mock.return_value
                instance.bind = Mock(side_effect=Exception('No IPv6 here!'))
                assert not _has_ipv6('::1')

    def test_has_ipv6_enabled_and_working(self):
        with patch('socket.has_ipv6', True):
            with patch('socket.socket') as mock:
                instance = mock.return_value
                instance.bind.return_value = True
                assert _has_ipv6('::1')

    def test_ip_family_ipv6_enabled(self):
        with patch('urllib3.util.connection.HAS_IPV6', True):
            assert allowed_gai_family() == socket.AF_UNSPEC

    def test_ip_family_ipv6_disabled(self):
        with patch('urllib3.util.connection.HAS_IPV6', False):
            assert allowed_gai_family() == socket.AF_INET

    @pytest.mark.parametrize('value', [
        "-1",
        "+1",
        "1.0",
        six.u("\xb2"),  # \xb2 = ^2
    ])
    def test_parse_retry_after_invalid(self, value):
        retry = Retry()
        with pytest.raises(InvalidHeader):
            retry.parse_retry_after(value)

    @pytest.mark.parametrize('value, expected', [
        ("0", 0),
        ("1000", 1000),
        ("\t42 ", 42),
    ])
    def test_parse_retry_after(self, value, expected):
        retry = Retry()
        assert retry.parse_retry_after(value) == expected

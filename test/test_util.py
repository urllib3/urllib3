import unittest
import logging

from urllib3 import add_stderr_logger
from urllib3.util import get_host, make_headers, split_first
from urllib3.exceptions import LocationParseError


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
            '[2a00:1450:4001:c01::67]': ('http', '2a00:1450:4001:c01::67', None),
            'http://[2a00:1450:4001:c01::67]': ('http', '2a00:1450:4001:c01::67', None),
            'http://[2a00:1450:4001:c01::67]/test': ('http', '2a00:1450:4001:c01::67', None),
            'http://[2a00:1450:4001:c01::67]:80': ('http', '2a00:1450:4001:c01::67', 80),
            'http://[2a00:1450:4001:c01::67]:80/test': ('http', '2a00:1450:4001:c01::67', 80),

            # More IPv6 from http://www.ietf.org/rfc/rfc2732.txt
            'http://[FEDC:BA98:7654:3210:FEDC:BA98:7654:3210]:8000/index.html': ('http', 'FEDC:BA98:7654:3210:FEDC:BA98:7654:3210', 8000),
            'http://[1080:0:0:0:8:800:200C:417A]/index.html': ('http', '1080:0:0:0:8:800:200C:417A', None),
            'http://[3ffe:2a00:100:7031::1]': ('http', '3ffe:2a00:100:7031::1', None),
            'http://[1080::8:800:200C:417A]/foo': ('http', '1080::8:800:200C:417A', None),
            'http://[::192.9.5.5]/ipng': ('http', '::192.9.5.5', None),
            'http://[::FFFF:129.144.52.38]:42/index.html': ('http', '::FFFF:129.144.52.38', 42),
            'http://[2010:836B:4179::836B:4179]': ('http', '2010:836B:4179::836B:4179', None),
        }
        for url, expected_host in url_host_map.items():
            returned_host = get_host(url)
            self.assertEquals(returned_host, expected_host)

    def test_invalid_host(self):
        # TODO: Add more tests
        invalid_host = [
            'http://google.com:foo',
        ]

        for location in invalid_host:
            self.assertRaises(LocationParseError, get_host, location)


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


    def test_split_first(self):
        test_cases = {
            ('abcd', 'b'): ('a', 'cd'),
            ('abcd', 'cb'): ('a', 'cd'),
            ('abcd', ''): ('abcd', ''),
        }
        for input, expected in test_cases.iteritems():
            output = split_first(*input)
            self.assertEqual(output, expected)

    def test_add_stderr_logger(self):
        handler = add_stderr_logger(level=logging.INFO) # Don't actually print debug
        logger = logging.getLogger('urllib3')
        self.assertTrue(handler in logger.handlers)

        logger.debug('Testing add_stderr_logger')
        logger.removeHandler(handler)

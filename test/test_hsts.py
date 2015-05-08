import unittest

from urllib3.hsts import (HSTSManager, MemoryHSTSStore, match_domains,
                          parse_hsts_header, is_ipaddress)
from urllib3.util.url import parse_url


class HSTSTestCase(unittest.TestCase):
    def test_hsts_record_match(self):
        data = [
            # sub, super, include_subdomain, match
            ('example.com', 'example.com', False, True),
            ('foo.example.com', 'example.com', False, False),
            ('foo.example.com', 'xxxxxxx.com', False, False),
            ('example.com', 'foo.example.com', False, False),
            ('example.com', 'example.com', True, True),
            ('foo.example.com', 'example.com', True, True),
            ('foo.example.com', 'xxxxxxx.com', True, False),
            ('example.com', 'foo.example.com', True, False),
        ]

        for sub, sup, include_subdomain, match in data:
            self.assertEqual(match_domains(sub, sup, include_subdomain), match,
                             "{0} == {1} (subdomains: {2})".format(
                                sub, sup, include_subdomain))

    def test_rewrite_url(self):
        hsts_manager = HSTSManager(None)

        data = [
            # original, rewritten
            ('http://example.com/', 'https://example.com/'),
            ('http://example.com:80/', 'https://example.com:443/'),
            ('http://example.com:123/', 'https://example.com:123/'),
        ]

        for original, rewritten in data:
            self.assertEqual(
                    rewritten,
                    hsts_manager.rewrite_url(parse_url(original)).url)

    def test_parse_hsts_header(self):
        domain = 'example.com'

        data = [
                # raw, max_age, include_subdomains
                ('max-age=15', 15, False),
                ('max-age="15"', 15, False),
                ('MAX-AGE=15', 15, False),
                ('Max-Age=15', 15, False),
                ('max-age=15; includeSubdomains', 15, True),
                ('includeSubdomains; max-age=15', 15, True),
                ('max-age=15; INCLUDESUBDOMAINS', 15, True),
        ]

        for raw, max_age, include_subdomains in data:
            record = parse_hsts_header(raw, domain)

            self.assertEqual(record.max_age, max_age)
            self.assertEqual(record.include_subdomains, include_subdomains)

    def test_invalid_hsts_headers(self):
        domain = 'example.com'
        data = [
                'max-age=15; max-age=4',
                'max-age',
                'max-age=xxx',
                'max-age=-4',
                'some crap',
        ]

        for raw in data:
            print(raw)
            self.assertEqual(parse_hsts_header(raw, domain), None)

    def test_is_ipaddress(self):
        valid = [
                '1.1.1.1',
                '::1',
        ]
        invalid = [
                'foobar'
        ]

        for address in valid:
            self.assertTrue(is_ipaddress(address))

        for address in invalid:
            self.assertFalse(is_ipaddress(address))

    def test_hsts_manager_must_rewrite(self):
        m = HSTSManager(MemoryHSTSStore())
        m.process_header('example.com', 'https', 'max-age=15')
        self.assertTrue(m.check_domain('example.com'))
        self.assertFalse(m.check_domain('google.com'))

        m.process_header('google.com', 'https', 'max-age=15; includeSubdomains')
        self.assertTrue(m.check_domain('example.com'))
        self.assertTrue(m.check_domain('google.com'))
        self.assertTrue(m.check_domain('www.google.com'))
        self.assertFalse(m.check_domain('yahoo.com'))

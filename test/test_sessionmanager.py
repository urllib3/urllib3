import unittest

from urllib3.sessionmanager import SessionManager
from urllib3.poolmanager import ProxyManager, PoolManager
from urllib3.util.sessioncontext import SessionContext
from urllib3.contexthandlers import DefaultCookiePolicy, CookieJar, BasicAuthHandler, CookieHandler
from urllib3.packages import six
from urllib3.response import HTTPResponse
from urllib3.request import Request

cookielib = six.moves.http_cookiejar


class TestSessionManager(unittest.TestCase):

    def setUp(self):
        self.manager = SessionManager(PoolManager())

    def test_set_cookie_policy(self):
        policy = cookielib.DefaultCookiePolicy()
        self.assertNotEqual(policy, self.manager.context.handlers[0].cookie_jar._policy)
        self.manager.context.handlers[0].cookie_jar.set_policy(policy)
        self.assertTrue(policy is self.manager.context.handlers[0].cookie_jar._policy)

    def test_create_proxy_manager(self):
        manager = SessionManager(ProxyManager(proxy_url='http://none'))
        self.assertTrue(isinstance(manager.manager, ProxyManager))

    def test_with_external_jar(self):
        this_policy = cookielib.DefaultCookiePolicy()
        jar = CookieJar(policy=this_policy)
        context = SessionContext(handlers=[CookieHandler(cookie_jar=jar)])
        manager = SessionManager(PoolManager(), context=context)
        self.assertTrue(manager.context.handlers[0].cookie_jar is jar)


class TestSessionContextCookieHandling(unittest.TestCase):

    def setUp(self):
        self.context = SessionContext()

    def test_extract_cookie(self):
        self.assertFalse(self.context.handlers[0].cookie_jar)
        req = Request(method='GET', url='http://google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        self.assertTrue(self.context.handlers[0].cookie_jar)

    def test_apply_cookie(self):
        req = Request(method='GET', url='http://google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        req = Request(method='GET', url='http://google.com')
        self.context.apply_to(req)
        self.assertEqual(req.headers.get('Cookie'), 'cookiename=cookieval')

    def test_no_apply_cookie(self):
        req = Request(method='GET', url='http://google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        self.assertTrue(self.context.handlers[0].cookie_jar)
        req = Request(method='GET', url='http://evil.com')
        self.context.apply_to(req)
        self.assertTrue(req.headers.get('Cookie', None) is None)

    def test_unacceptable_cookie(self):
        self.assertFalse(self.context.handlers[0].cookie_jar)
        req = Request(method='GET', url='http://evil.com')
        headers = {'Set-Cookie': 'cookiename=cookieval; domain=.google.com'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        self.assertFalse(self.context.handlers[0].cookie_jar)

    def test_parent_domain(self):
        req = Request(method='GET', url='http://www.google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval; domain=.google.com'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        req = Request(method='GET', url='http://google.com')
        self.context.apply_to(req)
        self.assertEqual(req.headers.get('Cookie'), 'cookiename=cookieval')

    def test_sibling_domain(self):
        req = Request(method='GET', url='http://ww1.google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        req = Request(method='GET', url='http://ww2.google.com')
        self.context.apply_to(req)
        self.assertTrue(req.headers.get('Cookie') is None)

    def test_sibling_domain_with_wildcard(self):
        req = Request(method='GET', url='http://ww1.google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval; domain=.google.com'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        req = Request(method='GET', url='http://ww2.google.com')
        self.context.apply_to(req)
        self.assertEqual(req.headers.get('Cookie'), 'cookiename=cookieval')

class TestSessionContextAuthHandling(unittest.TestCase):

    def setUp(self):
        auth = BasicAuthHandler(domain='https://google.com', username='blah', password='alsoblah')
        self.context = SessionContext(handlers=[auth])

    def test_with_acceptable_domain(self):
        req = Request(method='GET', url='https://google.com')
        self.context.apply_to(req)
        self.assertEqual(req.headers['authorization'], 'Basic YmxhaDphbHNvYmxhaA==')

    def test_with_wrong_scheme(self):
        req = Request(method='GET', url='http://google.com')
        self.context.apply_to(req)
        self.assertFalse(req.has_header('authorization'))

    def test_no_auth_header(self):
        req = Request(method='GET', url='http://evil.com')
        self.context.apply_to(req)
        self.assertFalse(req.has_header('authorization'))
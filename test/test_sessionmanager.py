import unittest

from urllib3.sessionmanager import SessionManager
from urllib3.poolmanager import ProxyManager, PoolManager
from urllib3.util.sessioncontext import DefaultCookiePolicy, CookieJar, SessionContext
from urllib3.packages import six
from urllib3.response import HTTPResponse
from urllib3.request import Request

cookielib = six.moves.http_cookiejar


class TestSessionManager(unittest.TestCase):

    def setUp(self):
        self.manager = SessionManager(PoolManager())

    def test_set_cookie_policy(self):
        """
        Test that we're able to set the policy on the SessionManager's CookieJar
        """
        policy = cookielib.DefaultCookiePolicy()
        self.assertNotEqual(policy, self.manager.context.cookie_jar._policy)
        self.manager.context.cookie_jar.set_policy(policy)
        self.assertTrue(policy is self.manager.context.cookie_jar._policy)

    def test_create_proxy_manager(self):
        """
        Make sure that when we pass a ProxyManager in, we use it.
        """
        pm = ProxyManager(proxy_url='http://none')
        manager = SessionManager(pm)
        self.assertTrue(manager.manager is pm)

    def test_creates_pool_manager(self):
        """
        Make sure that when we pass a PoolManager in, we use it.
        """
        pm = PoolManager()
        manager = SessionManager(pm)
        self.assertTrue(manager.manager is pm)

    def test_with_external_jar(self):
        """
        Make sure that when we pass a CookieJar in, we use it.
        """
        this_policy = cookielib.DefaultCookiePolicy()
        jar = CookieJar(policy=this_policy)
        context = SessionContext(cookie_jar=jar)
        manager = SessionManager(PoolManager(), context=context)
        self.assertTrue(manager.context.cookie_jar is jar)


class TestSessionContext(unittest.TestCase):

    def setUp(self):
        self.context = SessionContext()

    def test_extract_cookie(self):

        """
        Check to be sure that we're properly extracting cookies into the
        SessionManager's jar, and that the cookie has the expected value.
        """

        expected_cookie = cookielib.Cookie(
            version=0, name='cookiename', value='cookieval', port=None,
            port_specified=False, domain='google.com', domain_specified=False,
            domain_initial_dot=False, path='/', path_specified=False,
            secure=False, expires=None, discard=True, comment=None,
            comment_url=None, rest={}, rfc2109=False
        )

        self.assertFalse(self.context.cookie_jar)
        req = Request(method='GET', url='http://google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        self.assertTrue(self.context.cookie_jar)
        for each in self.context.cookie_jar:
            self.assertEqual(repr(each), repr(expected_cookie))

    def test_apply_cookie(self):
        """
        Ensure that we're setting relevant cookies on outgoing requests
        """
        req = Request(method='GET', url='http://google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        req = Request(method='GET', url='http://google.com')
        self.context.apply_to(req)
        self.assertEqual(req.headers.get('Cookie'), 'cookiename=cookieval')

    def test_no_apply_cookie(self):
        """
        Ensure that we don't set cookies on requests to another domain
        """
        req = Request(method='GET', url='http://google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        self.assertTrue(self.context.cookie_jar)
        req = Request(method='GET', url='http://evil.com')
        self.context.apply_to(req)
        self.assertTrue(req.headers.get('Cookie', None) is None)

    def test_unacceptable_cookie(self):
        """
        Ensure that we don't accept cookies for domains other than the one
        the request was sent to
        """
        self.assertFalse(self.context.cookie_jar)
        req = Request(method='GET', url='http://evil.com')
        headers = {'Set-Cookie': 'cookiename=cookieval; domain=.google.com'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        self.assertFalse(self.context.cookie_jar)

    def test_parent_domain(self):
        """
        Ensure that cookies set by child domains are sent to their parent domains
        """
        req = Request(method='GET', url='http://www.google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval; domain=.google.com'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        req = Request(method='GET', url='http://google.com')
        self.context.apply_to(req)
        self.assertEqual(req.headers.get('Cookie'), 'cookiename=cookieval')

    def test_sibling_domain(self):
        """
        Ensure that cookies set by sibling subdomains are not sent to
        other siblings under the same domain automatically.
        """
        req = Request(method='GET', url='http://ww1.google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        req = Request(method='GET', url='http://ww2.google.com')
        self.context.apply_to(req)
        self.assertTrue(req.headers.get('Cookie') is None)

    def test_sibling_domain_with_wildcard(self):
        """
        Ensure that when sibling domains specify a parent domain to send a cookie
        to, that cookie is also sent to other sibling domains under the
        same parent domain.
        """
        req = Request(method='GET', url='http://ww1.google.com')
        headers = {'Set-Cookie': 'cookiename=cookieval; domain=.google.com'}
        resp = HTTPResponse(headers=headers)
        self.context.extract_from(resp, req)
        req = Request(method='GET', url='http://ww2.google.com')
        self.context.apply_to(req)
        self.assertEqual(req.headers.get('Cookie'), 'cookiename=cookieval')

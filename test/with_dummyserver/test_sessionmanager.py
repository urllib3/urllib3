from urllib3.sessionmanager import SessionManager
from urllib3.exceptions import MaxRetryError
from urllib3.poolmanager import PoolManager

from urllib3.packages.six import b, u
from urllib3.packages import six

from dummyserver.testcase import HTTPDummyServerTestCase


class TestSessionManager(HTTPDummyServerTestCase):

    def create_url(self, route):
        return 'http://' + self.host + ':' + str(self.port) + route

    def create_alternate_url(self, route):
        return 'http://' + self.host_alt + ':' + str(self.port) + route

    def setUp(self):
        self.manager = SessionManager(PoolManager())

    def test_cookie_handler(self):
        route = self.create_url('/set_cookie_on_client')
        r = self.manager.request('GET', route)
        self.assertEqual(r.status, 200)
        self.assertTrue(self.manager.context.cookie_jar)
        route = self.create_url('/verify_cookie')
        r = self.manager.request('GET', route)
        self.assertEqual(r.data, b'Received cookie')

    def test_restrict_undomained_cookie_by_host(self):
        route = self.create_url('/set_undomained_cookie_on_client')
        r = self.manager.request('GET', route)
        self.assertEqual(r.status, 200)
        self.assertTrue(self.manager.context.cookie_jar)
        route = self.create_alternate_url('/verify_cookie')
        r = self.manager.request('GET', route)
        self.assertEqual(r.status, 400)

    def test_merge_cookie_header(self):
        self.assertFalse(self.manager.context.cookie_jar)
        headers = {'Cookie': 'testing_cookie=test_cookie_value'}
        route = self.create_url('/verify_cookie')
        r = self.manager.request('GET', route, headers=headers)
        self.assertEqual(r.data, b'Received cookie')

    def test_instance_headers(self):
        headers = {'Cookie': 'testing_cookie=test_cookie_value'}
        manager = SessionManager(PoolManager(), headers=headers)
        route = self.create_url('/verify_cookie')
        r = manager.request('GET', route)
        self.assertEqual(r.data, b'Received cookie')

    def test_collect_cookie_on_redirect(self):
        route = self.create_url('/set_cookie_and_redirect')
        r = self.manager.request('GET', route)
        self.assertEqual(r.data, b'Received cookie')

    def test_no_retry(self):
        def execute_query():
            route = self.create_url('/set_cookie_and_redirect')
            r = self.manager.request('GET', route, retries=0)
        self.assertRaises(MaxRetryError, execute_query)

    def test_no_redirect(self):
        route = self.create_url('/set_cookie_and_redirect')
        r = self.manager.request('GET', route, redirect=False)
        self.assertEqual(r.status, 303)

import json
from test import LONG_TIMEOUT

import pytest

from dummyserver.server import HAS_IPV6
from dummyserver.testcase import HTTPDummyServerTestCase, IPv6HTTPDummyServerTestCase
from urllib3._collections import HTTPHeaderDict
from urllib3.connectionpool import port_by_scheme
from urllib3.exceptions import MaxRetryError, URLSchemeUnknown
from urllib3.poolmanager import PoolManager
from urllib3.util.retry import Retry

# Retry failed tests
pytestmark = pytest.mark.flaky


class TestPoolManager(HTTPDummyServerTestCase):
    @classmethod
    def setup_class(cls):
        super(TestPoolManager, cls).setup_class()
        cls.base_url = "http://%s:%d" % (cls.host, cls.port)
        cls.base_url_alt = "http://%s:%d" % (cls.host_alt, cls.port)

    def test_redirect(self):
        with PoolManager() as http:
            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/" % self.base_url},
                redirect=False,
            )

            assert r.status == 303

            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/" % self.base_url},
            )

            assert r.status == 200
            assert r.data == b"Dummy server!"

    def test_redirect_twice(self):
        with PoolManager() as http:
            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/redirect" % self.base_url},
                redirect=False,
            )

            assert r.status == 303

            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={
                    "target": "%s/redirect?target=%s/" % (self.base_url, self.base_url)
                },
            )

            assert r.status == 200
            assert r.data == b"Dummy server!"

    def test_redirect_to_relative_url(self):
        with PoolManager() as http:
            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "/redirect"},
                redirect=False,
            )

            assert r.status == 303

            r = http.request(
                "GET", "%s/redirect" % self.base_url, fields={"target": "/redirect"}
            )

            assert r.status == 200
            assert r.data == b"Dummy server!"

    @pytest.mark.parametrize(
        "retries",
        (0, Retry(total=0), Retry(redirect=0), Retry(total=0, redirect=0)),
    )
    def test_redirects_disabled_for_pool_manager_with_0(
        self, retries: typing.Literal[0] | Retry
    ) -> None:
        """
        Check handling redirects when retries is set to 0 on the pool
        manager.
        """
        with PoolManager(retries=retries) as http:
            with pytest.raises(MaxRetryError):
                http.request("GET", f"{self.base_url}/redirect")

            # Setting redirect=True should not change the behavior.
            with pytest.raises(MaxRetryError):
                http.request("GET", f"{self.base_url}/redirect", redirect=True)

            # Setting redirect=False should not make it follow the redirect,
            # but MaxRetryError should not be raised.
            response = http.request("GET", f"{self.base_url}/redirect", redirect=False)
            assert response.status == 303

    @pytest.mark.parametrize(
        "retries",
        (
            False,
            Retry(total=False),
            Retry(redirect=False),
            Retry(total=False, redirect=False),
        ),
    )
    def test_redirects_disabled_for_pool_manager_with_false(
        self, retries: typing.Literal[False] | Retry
    ) -> None:
        """
        Check that setting retries set to False on the pool manager disables
        raising MaxRetryError and redirect=True does not change the
        behavior.
        """
        with PoolManager(retries=retries) as http:
            response = http.request("GET", f"{self.base_url}/redirect")
            assert response.status == 303

            response = http.request("GET", f"{self.base_url}/redirect", redirect=True)
            assert response.status == 303

            response = http.request("GET", f"{self.base_url}/redirect", redirect=False)
            assert response.status == 303

    def test_redirects_disabled_for_individual_request(self) -> None:
        """
        Check handling redirects when they are meant to be disabled
        on the request level.
        """
        with PoolManager() as http:
            # Check when redirect is not passed.
            with pytest.raises(MaxRetryError):
                http.request("GET", f"{self.base_url}/redirect", retries=0)
            response = http.request("GET", f"{self.base_url}/redirect", retries=False)
            assert response.status == 303

            # Check when redirect=True.
            with pytest.raises(MaxRetryError):
                http.request(
                    "GET", f"{self.base_url}/redirect", retries=0, redirect=True
                )
            response = http.request(
                "GET", f"{self.base_url}/redirect", retries=False, redirect=True
            )
            assert response.status == 303

            # Check when redirect=False.
            response = http.request(
                "GET", f"{self.base_url}/redirect", retries=0, redirect=False
            )
            assert response.status == 303
            response = http.request(
                "GET", f"{self.base_url}/redirect", retries=False, redirect=False
            )
            assert response.status == 303

    def test_cross_host_redirect(self):
        with PoolManager() as http:
            cross_host_location = "%s/echo?a=b" % self.base_url_alt
            with pytest.raises(MaxRetryError):
                http.request(
                    "GET",
                    "%s/redirect" % self.base_url,
                    fields={"target": cross_host_location},
                    timeout=LONG_TIMEOUT,
                    retries=0,
                )

            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/echo?a=b" % self.base_url_alt},
                timeout=LONG_TIMEOUT,
                retries=1,
            )

            assert r._pool.host == self.host_alt

    def test_too_many_redirects(self):
        with PoolManager() as http:
            with pytest.raises(MaxRetryError):
                http.request(
                    "GET",
                    "%s/redirect" % self.base_url,
                    fields={
                        "target": "%s/redirect?target=%s/"
                        % (self.base_url, self.base_url)
                    },
                    retries=1,
                    preload_content=False,
                )

            with pytest.raises(MaxRetryError):
                http.request(
                    "GET",
                    "%s/redirect" % self.base_url,
                    fields={
                        "target": "%s/redirect?target=%s/"
                        % (self.base_url, self.base_url)
                    },
                    retries=Retry(total=None, redirect=1),
                    preload_content=False,
                )

            # Even with preload_content=False and raise on redirects, we reused the same
            # connection
            assert len(http.pools) == 1
            pool = http.connection_from_host(self.host, self.port)
            assert pool.num_connections == 1

        # Check when retries are configured for the pool manager.
        with PoolManager(retries=1) as http:
            with pytest.raises(MaxRetryError):
                http.request(
                    "GET",
                    f"{self.base_url}/redirect",
                    fields={"target": f"/redirect?target={self.base_url}/"},
                )

            # Here we allow more retries for the request.
            response = http.request(
                "GET",
                f"{self.base_url}/redirect",
                fields={"target": f"/redirect?target={self.base_url}/"},
                retries=2,
            )
            assert response.status == 200

    def test_redirect_cross_host_remove_headers(self):
        with PoolManager() as http:
            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/headers" % self.base_url_alt},
                headers={
                    "Authorization": "foo",
                    "Proxy-Authorization": "bar",
                    "Cookie": "foo=bar",
                },
            )

            assert r.status == 200

            data = json.loads(r.data.decode("utf-8"))

            assert "Authorization" not in data
            assert "Proxy-Authorization" not in data
            assert "Cookie" not in data

            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/headers" % self.base_url_alt},
                headers={
                    "authorization": "foo",
                    "proxy-authorization": "baz",
                    "cookie": "foo=bar",
                },
            )

            assert r.status == 200

            data = json.loads(r.data.decode("utf-8"))

            assert "authorization" not in data
            assert "Authorization" not in data
            assert "proxy-authorization" not in data
            assert "Proxy-Authorization" not in data
            assert "cookie" not in data
            assert "Cookie" not in data

    def test_redirect_cross_host_no_remove_headers(self):
        with PoolManager() as http:
            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/headers" % self.base_url_alt},
                headers={
                    "Authorization": "foo",
                    "Proxy-Authorization": "bar",
                    "Cookie": "foo=bar",
                },
                retries=Retry(remove_headers_on_redirect=[]),
            )

            assert r.status == 200

            data = json.loads(r.data.decode("utf-8"))

            assert data["Authorization"] == "foo"
            assert data["Proxy-Authorization"] == "bar"
            assert data["Cookie"] == "foo=bar"

    def test_redirect_cross_host_set_removed_headers(self):
        with PoolManager() as http:
            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/headers" % self.base_url_alt},
                headers={
                    "X-API-Secret": "foo",
                    "Authorization": "bar",
                    "Proxy-Authorization": "baz",
                    "Cookie": "foo=bar",
                },
                retries=Retry(remove_headers_on_redirect=["X-API-Secret"]),
            )

            assert r.status == 200

            data = json.loads(r.data.decode("utf-8"))

            assert "X-API-Secret" not in data
            assert data["Authorization"] == "bar"
            assert data["Proxy-Authorization"] == "baz"
            assert data["Cookie"] == "foo=bar"

            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": "%s/headers" % self.base_url_alt},
                headers={
                    "x-api-secret": "foo",
                    "proxy-authorization": "baz",
                    "authorization": "bar",
                    "cookie": "foo=bar",
                },
                retries=Retry(remove_headers_on_redirect=["X-API-Secret"]),
            )

            assert r.status == 200

            data = json.loads(r.data.decode("utf-8"))

            assert "x-api-secret" not in data
            assert "X-API-Secret" not in data
            assert data["Authorization"] == "bar"
            assert data["Proxy-Authorization"] == "baz"
            assert data["Cookie"] == "foo=bar"

    def test_redirect_without_preload_releases_connection(self):
        with PoolManager(block=True, maxsize=2) as http:
            r = http.request(
                "GET", "%s/redirect" % self.base_url, preload_content=False
            )
            assert r._pool.num_requests == 2
            assert r._pool.num_connections == 1
            assert len(http.pools) == 1

    def test_303_redirect_makes_request_lose_body(self):
        with PoolManager() as http:
            response = http.request(
                "POST",
                "%s/redirect" % self.base_url,
                fields={
                    "target": "%s/headers_and_params" % self.base_url,
                    "status": "303 See Other",
                },
            )
        data = json.loads(response.data)
        assert data["params"] == {}
        assert "Content-Type" not in HTTPHeaderDict(data["headers"])

    def test_unknown_scheme(self):
        with PoolManager() as http:
            unknown_scheme = "unknown"
            unknown_scheme_url = "%s://host" % unknown_scheme
            with pytest.raises(URLSchemeUnknown) as e:
                r = http.request("GET", unknown_scheme_url)
            assert e.value.scheme == unknown_scheme
            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={"target": unknown_scheme_url},
                redirect=False,
            )
            assert r.status == 303
            assert r.headers.get("Location") == unknown_scheme_url
            with pytest.raises(URLSchemeUnknown) as e:
                r = http.request(
                    "GET",
                    "%s/redirect" % self.base_url,
                    fields={"target": unknown_scheme_url},
                )
            assert e.value.scheme == unknown_scheme

    def test_raise_on_redirect(self):
        with PoolManager() as http:
            r = http.request(
                "GET",
                "%s/redirect" % self.base_url,
                fields={
                    "target": "%s/redirect?target=%s/" % (self.base_url, self.base_url)
                },
                retries=Retry(total=None, redirect=1, raise_on_redirect=False),
            )

            assert r.status == 303

    def test_raise_on_status(self):
        with PoolManager() as http:
            with pytest.raises(MaxRetryError):
                # the default is to raise
                r = http.request(
                    "GET",
                    "%s/status" % self.base_url,
                    fields={"status": "500 Internal Server Error"},
                    retries=Retry(total=1, status_forcelist=range(500, 600)),
                )

            with pytest.raises(MaxRetryError):
                # raise explicitly
                r = http.request(
                    "GET",
                    "%s/status" % self.base_url,
                    fields={"status": "500 Internal Server Error"},
                    retries=Retry(
                        total=1, status_forcelist=range(500, 600), raise_on_status=True
                    ),
                )

            # don't raise
            r = http.request(
                "GET",
                "%s/status" % self.base_url,
                fields={"status": "500 Internal Server Error"},
                retries=Retry(
                    total=1, status_forcelist=range(500, 600), raise_on_status=False
                ),
            )

            assert r.status == 500

    def test_missing_port(self):
        # Can a URL that lacks an explicit port like ':80' succeed, or
        # will all such URLs fail with an error?

        with PoolManager() as http:
            # By globally adjusting `port_by_scheme` we pretend for a moment
            # that HTTP's default port is not 80, but is the port at which
            # our test server happens to be listening.
            port_by_scheme["http"] = self.port
            try:
                r = http.request("GET", "http://%s/" % self.host, retries=0)
            finally:
                port_by_scheme["http"] = 80

            assert r.status == 200
            assert r.data == b"Dummy server!"

    def test_headers(self):
        with PoolManager(headers={"Foo": "bar"}) as http:
            r = http.request("GET", "%s/headers" % self.base_url)
            returned_headers = json.loads(r.data.decode())
            assert returned_headers.get("Foo") == "bar"

            r = http.request("POST", "%s/headers" % self.base_url)
            returned_headers = json.loads(r.data.decode())
            assert returned_headers.get("Foo") == "bar"

            r = http.request_encode_url("GET", "%s/headers" % self.base_url)
            returned_headers = json.loads(r.data.decode())
            assert returned_headers.get("Foo") == "bar"

            r = http.request_encode_body("POST", "%s/headers" % self.base_url)
            returned_headers = json.loads(r.data.decode())
            assert returned_headers.get("Foo") == "bar"

            r = http.request_encode_url(
                "GET", "%s/headers" % self.base_url, headers={"Baz": "quux"}
            )
            returned_headers = json.loads(r.data.decode())
            assert returned_headers.get("Foo") is None
            assert returned_headers.get("Baz") == "quux"

            r = http.request_encode_body(
                "GET", "%s/headers" % self.base_url, headers={"Baz": "quux"}
            )
            returned_headers = json.loads(r.data.decode())
            assert returned_headers.get("Foo") is None
            assert returned_headers.get("Baz") == "quux"

    def test_http_with_ssl_keywords(self):
        with PoolManager(ca_certs="REQUIRED") as http:
            r = http.request("GET", "http://%s:%s/" % (self.host, self.port))
            assert r.status == 200

    def test_http_with_server_hostname(self):
        with PoolManager(server_hostname="example.com") as http:
            r = http.request("GET", "http://%s:%s/" % (self.host, self.port))
            assert r.status == 200

    def test_http_with_ca_cert_dir(self):
        with PoolManager(ca_certs="REQUIRED", ca_cert_dir="/nosuchdir") as http:
            r = http.request("GET", "http://%s:%s/" % (self.host, self.port))
            assert r.status == 200

    @pytest.mark.parametrize(
        ["target", "expected_target"],
        [
            ("/echo_uri?q=1#fragment", b"/echo_uri?q=1"),
            ("/echo_uri?#", b"/echo_uri?"),
            ("/echo_uri#?", b"/echo_uri"),
            ("/echo_uri#?#", b"/echo_uri"),
            ("/echo_uri??#", b"/echo_uri??"),
            ("/echo_uri?%3f#", b"/echo_uri?%3F"),
            ("/echo_uri?%3F#", b"/echo_uri?%3F"),
            ("/echo_uri?[]", b"/echo_uri?%5B%5D"),
        ],
    )
    def test_encode_http_target(self, target, expected_target):
        with PoolManager() as http:
            url = "http://%s:%d%s" % (self.host, self.port, target)
            r = http.request("GET", url)
            assert r.data == expected_target


@pytest.mark.skipif(not HAS_IPV6, reason="IPv6 is not supported on this system")
class TestIPv6PoolManager(IPv6HTTPDummyServerTestCase):
    @classmethod
    def setup_class(cls):
        super(TestIPv6PoolManager, cls).setup_class()
        cls.base_url = "http://[%s]:%d" % (cls.host, cls.port)

    def test_ipv6(self):
        with PoolManager() as http:
            http.request("GET", self.base_url)

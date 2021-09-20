import functools
import logging
import warnings
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    FrozenSet,
    Mapping,
    NamedTuple,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)
from urllib.parse import urljoin

from ._collections import RecentlyUsedContainer
from ._request_methods import RequestMethods
from .connection import ProxyConfig
from .connectionpool import HTTPConnectionPool, HTTPSConnectionPool, port_by_scheme
from .exceptions import (
    LocationValueError,
    MaxRetryError,
    ProxySchemeUnknown,
    URLSchemeUnknown,
)
from .response import BaseHTTPResponse
from .util.connection import _TYPE_SOCKET_OPTIONS
from .util.proxy import connection_requires_http_tunnel
from .util.retry import Retry
from .util.timeout import Timeout
from .util.url import Url, parse_url

if TYPE_CHECKING:
    import ssl

    from typing_extensions import Literal

__all__ = ["PoolManager", "ProxyManager", "proxy_from_url"]


log = logging.getLogger(__name__)

SSL_KEYWORDS = (
    "key_file",
    "cert_file",
    "cert_reqs",
    "ca_certs",
    "ssl_version",
    "ssl_minimum_version",
    "ssl_maximum_version",
    "ca_cert_dir",
    "ssl_context",
    "key_password",
)
# Default value for `blocksize` - a new parameter introduced to
# http.client.HTTPConnection & http.client.HTTPSConnection in Python 3.7
_DEFAULT_BLOCKSIZE = 16384

_SelfT = TypeVar("_SelfT")


class PoolKey(NamedTuple):
    """
    All known keyword arguments that could be provided to the pool manager, its
    pools, or the underlying connections.

    All custom key schemes should include the fields in this key at a minimum.
    """

    key_scheme: str
    key_host: str
    key_port: Optional[int]
    key_timeout: Optional[Union[Timeout, float, int]]
    key_retries: Optional[Union[Retry, int]]
    key_block: Optional[bool]
    key_source_address: Optional[Tuple[str, int]]
    key_key_file: Optional[str]
    key_key_password: Optional[str]
    key_cert_file: Optional[str]
    key_cert_reqs: Optional[str]
    key_ca_certs: Optional[str]
    key_ssl_version: Optional[Union[int, str]]
    key_ssl_minimum_version: Optional["ssl.TLSVersion"]
    key_ssl_maximum_version: Optional["ssl.TLSVersion"]
    key_ca_cert_dir: Optional[str]
    key_ssl_context: Optional["ssl.SSLContext"]
    key_maxsize: Optional[int]
    key_headers: Optional[FrozenSet[Tuple[str, str]]]
    key__proxy: Optional[Url]
    key__proxy_headers: Optional[FrozenSet[Tuple[str, str]]]
    key__proxy_config: Optional[ProxyConfig]
    key_socket_options: Optional[_TYPE_SOCKET_OPTIONS]
    key__socks_options: Optional[FrozenSet[Tuple[str, str]]]
    key_assert_hostname: Optional[Union[bool, str]]
    key_assert_fingerprint: Optional[str]
    key_server_hostname: Optional[str]
    key_blocksize: Optional[int]


def _default_key_normalizer(
    key_class: Type[PoolKey], request_context: Dict[str, Any]
) -> PoolKey:
    """
    Create a pool key out of a request context dictionary.

    According to RFC 3986, both the scheme and host are case-insensitive.
    Therefore, this function normalizes both before constructing the pool
    key for an HTTPS request. If you wish to change this behaviour, provide
    alternate callables to ``key_fn_by_scheme``.

    :param key_class:
        The class to use when constructing the key. This should be a namedtuple
        with the ``scheme`` and ``host`` keys at a minimum.
    :type  key_class: namedtuple
    :param request_context:
        A dictionary-like object that contain the context for a request.
    :type  request_context: dict

    :return: A namedtuple that can be used as a connection pool key.
    :rtype:  PoolKey
    """
    # Since we mutate the dictionary, make a copy first
    context = request_context.copy()
    context["scheme"] = context["scheme"].lower()
    context["host"] = context["host"].lower()

    # These are both dictionaries and need to be transformed into frozensets
    for key in ("headers", "_proxy_headers", "_socks_options"):
        if key in context and context[key] is not None:
            context[key] = frozenset(context[key].items())

    # The socket_options key may be a list and needs to be transformed into a
    # tuple.
    socket_opts = context.get("socket_options")
    if socket_opts is not None:
        context["socket_options"] = tuple(socket_opts)

    # Map the kwargs to the names in the namedtuple - this is necessary since
    # namedtuples can't have fields starting with '_'.
    for key in list(context.keys()):
        context["key_" + key] = context.pop(key)

    # Default to ``None`` for keys missing from the context
    for field in key_class._fields:
        if field not in context:
            context[field] = None

    # Default key_blocksize to _DEFAULT_BLOCKSIZE if missing from the context
    if context.get("key_blocksize") is None:
        context["key_blocksize"] = _DEFAULT_BLOCKSIZE

    return key_class(**context)


#: A dictionary that maps a scheme to a callable that creates a pool key.
#: This can be used to alter the way pool keys are constructed, if desired.
#: Each PoolManager makes a copy of this dictionary so they can be configured
#: globally here, or individually on the instance.
key_fn_by_scheme = {
    "http": functools.partial(_default_key_normalizer, PoolKey),
    "https": functools.partial(_default_key_normalizer, PoolKey),
}

pool_classes_by_scheme = {"http": HTTPConnectionPool, "https": HTTPSConnectionPool}


class PoolManager(RequestMethods):
    """
    Allows for arbitrary requests while transparently keeping track of
    necessary connection pools for you.

    :param num_pools:
        Number of connection pools to cache before discarding the least
        recently used pool.

    :param headers:
        Headers to include with all requests, unless other headers are given
        explicitly.

    :param \\**connection_pool_kw:
        Additional parameters are used to create fresh
        :class:`urllib3.connectionpool.ConnectionPool` instances.

    Example:

    .. code-block:: python

        import urllib3

        http = urllib3.PoolManager(num_pools=2)

        resp1 = http.request("GET", "https://google.com/")
        resp2 = http.request("GET", "https://google.com/mail")
        resp3 = http.request("GET", "https://yahoo.com/")

        print(len(http.pools))
        # 2

    """

    proxy: Optional[Url] = None
    proxy_config: Optional[ProxyConfig] = None

    def __init__(
        self,
        num_pools: int = 10,
        headers: Optional[Mapping[str, str]] = None,
        **connection_pool_kw: Any,
    ) -> None:
        super().__init__(headers)
        self.connection_pool_kw = connection_pool_kw

        def dispose_func(p: Any) -> None:
            p.close()

        self.pools: RecentlyUsedContainer[PoolKey, HTTPConnectionPool]
        self.pools = RecentlyUsedContainer(num_pools, dispose_func=dispose_func)

        # Locally set the pool classes and keys so other PoolManagers can
        # override them.
        self.pool_classes_by_scheme = pool_classes_by_scheme
        self.key_fn_by_scheme = key_fn_by_scheme.copy()

    def __enter__(self: _SelfT) -> _SelfT:
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> "Literal[False]":
        self.clear()
        # Return False to re-raise any potential exceptions
        return False

    def _new_pool(
        self,
        scheme: str,
        host: str,
        port: int,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> HTTPConnectionPool:
        """
        Create a new :class:`urllib3.connectionpool.ConnectionPool` based on host, port, scheme, and
        any additional pool keyword arguments.

        If ``request_context`` is provided, it is provided as keyword arguments
        to the pool class used. This method is used to actually create the
        connection pools handed out by :meth:`connection_from_url` and
        companion methods. It is intended to be overridden for customization.
        """
        pool_cls: Type[HTTPConnectionPool] = self.pool_classes_by_scheme[scheme]
        if request_context is None:
            request_context = self.connection_pool_kw.copy()

        # Default blocksize to _DEFAULT_BLOCKSIZE if missing or explicitly
        # set to 'None' in the request_context.
        if request_context.get("blocksize") is None:
            request_context["blocksize"] = _DEFAULT_BLOCKSIZE

        # Although the context has everything necessary to create the pool,
        # this function has historically only used the scheme, host, and port
        # in the positional args. When an API change is acceptable these can
        # be removed.
        for key in ("scheme", "host", "port"):
            request_context.pop(key, None)

        if scheme == "http":
            for kw in SSL_KEYWORDS:
                request_context.pop(kw, None)

        return pool_cls(host, port, **request_context)

    def clear(self) -> None:
        """
        Empty our store of pools and direct them all to close.

        This will not affect in-flight connections, but they will not be
        re-used after completion.
        """
        self.pools.clear()

    def connection_from_host(
        self,
        host: Optional[str],
        port: Optional[int] = None,
        scheme: Optional[str] = "http",
        pool_kwargs: Optional[Dict[str, Any]] = None,
    ) -> HTTPConnectionPool:
        """
        Get a :class:`urllib3.connectionpool.ConnectionPool` based on the host, port, and scheme.

        If ``port`` isn't given, it will be derived from the ``scheme`` using
        ``urllib3.connectionpool.port_by_scheme``. If ``pool_kwargs`` is
        provided, it is merged with the instance's ``connection_pool_kw``
        variable and used to create the new connection pool, if one is
        needed.
        """

        if not host:
            raise LocationValueError("No host specified.")

        request_context = self._merge_pool_kwargs(pool_kwargs)
        request_context["scheme"] = scheme or "http"
        if not port:
            port = port_by_scheme.get(request_context["scheme"].lower(), 80)
        request_context["port"] = port
        request_context["host"] = host

        return self.connection_from_context(request_context)

    def connection_from_context(
        self, request_context: Dict[str, Any]
    ) -> HTTPConnectionPool:
        """
        Get a :class:`urllib3.connectionpool.ConnectionPool` based on the request context.

        ``request_context`` must at least contain the ``scheme`` key and its
        value must be a key in ``key_fn_by_scheme`` instance variable.
        """
        if "strict" in request_context:
            warnings.warn(
                "The 'strict' parameter is no longer needed on Python 3+. "
                "This will raise an error in urllib3 v3.0.0.",
                DeprecationWarning,
            )
            request_context.pop("strict")

        scheme = request_context["scheme"].lower()
        pool_key_constructor = self.key_fn_by_scheme.get(scheme)
        if not pool_key_constructor:
            raise URLSchemeUnknown(scheme)
        pool_key = pool_key_constructor(request_context)

        return self.connection_from_pool_key(pool_key, request_context=request_context)

    def connection_from_pool_key(
        self, pool_key: PoolKey, request_context: Dict[str, Any]
    ) -> HTTPConnectionPool:
        """
        Get a :class:`urllib3.connectionpool.ConnectionPool` based on the provided pool key.

        ``pool_key`` should be a namedtuple that only contains immutable
        objects. At a minimum it must have the ``scheme``, ``host``, and
        ``port`` fields.
        """
        with self.pools.lock:
            # If the scheme, host, or port doesn't match existing open
            # connections, open a new ConnectionPool.
            pool = self.pools.get(pool_key)
            if pool:
                return pool

            # Make a fresh ConnectionPool of the desired type
            scheme = request_context["scheme"]
            host = request_context["host"]
            port = request_context["port"]
            pool = self._new_pool(scheme, host, port, request_context=request_context)
            self.pools[pool_key] = pool

        return pool

    def connection_from_url(
        self, url: str, pool_kwargs: Optional[Dict[str, Any]] = None
    ) -> HTTPConnectionPool:
        """
        Similar to :func:`urllib3.connectionpool.connection_from_url`.

        If ``pool_kwargs`` is not provided and a new pool needs to be
        constructed, ``self.connection_pool_kw`` is used to initialize
        the :class:`urllib3.connectionpool.ConnectionPool`. If ``pool_kwargs``
        is provided, it is used instead. Note that if a new pool does not
        need to be created for the request, the provided ``pool_kwargs`` are
        not used.
        """
        u = parse_url(url)
        return self.connection_from_host(
            u.host, port=u.port, scheme=u.scheme, pool_kwargs=pool_kwargs
        )

    def _merge_pool_kwargs(self, override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Merge a dictionary of override values for self.connection_pool_kw.

        This does not modify self.connection_pool_kw and returns a new dict.
        Any keys in the override dictionary with a value of ``None`` are
        removed from the merged dictionary.
        """
        base_pool_kwargs = self.connection_pool_kw.copy()
        if override:
            for key, value in override.items():
                if value is None:
                    try:
                        del base_pool_kwargs[key]
                    except KeyError:
                        pass
                else:
                    base_pool_kwargs[key] = value
        return base_pool_kwargs

    def _proxy_requires_url_absolute_form(self, parsed_url: Url) -> bool:
        """
        Indicates if the proxy requires the complete destination URL in the
        request.  Normally this is only needed when not using an HTTP CONNECT
        tunnel.
        """
        if self.proxy is None:
            return False

        return not connection_requires_http_tunnel(
            self.proxy, self.proxy_config, parsed_url.scheme
        )

    def urlopen(  # type: ignore[override]
        self, method: str, url: str, redirect: bool = True, **kw: Any
    ) -> BaseHTTPResponse:
        """
        Same as :meth:`urllib3.HTTPConnectionPool.urlopen`
        with custom cross-host redirect logic and only sends the request-uri
        portion of the ``url``.

        The given ``url`` parameter must be absolute, such that an appropriate
        :class:`urllib3.connectionpool.ConnectionPool` can be chosen for it.
        """
        u = parse_url(url)

        conn = self.connection_from_host(u.host, port=u.port, scheme=u.scheme)

        kw["assert_same_host"] = False
        kw["redirect"] = False

        if "headers" not in kw:
            kw["headers"] = self.headers

        if self._proxy_requires_url_absolute_form(u):
            response = conn.urlopen(method, url, **kw)
        else:
            response = conn.urlopen(method, u.request_uri, **kw)

        redirect_location = redirect and response.get_redirect_location()
        if not redirect_location:
            return response

        # Support relative URLs for redirecting.
        redirect_location = urljoin(url, redirect_location)

        # RFC 7231, Section 6.4.4
        if response.status == 303:
            method = "GET"

        retries = kw.get("retries")
        if not isinstance(retries, Retry):
            retries = Retry.from_int(retries, redirect=redirect)

        # Strip headers marked as unsafe to forward to the redirected location.
        # Check remove_headers_on_redirect to avoid a potential network call within
        # conn.is_same_host() which may use socket.gethostbyname() in the future.
        if retries.remove_headers_on_redirect and not conn.is_same_host(
            redirect_location
        ):
            new_headers = kw["headers"].copy()
            for header in kw["headers"]:
                if header.lower() in retries.remove_headers_on_redirect:
                    new_headers.pop(header, None)
            kw["headers"] = new_headers

        try:
            retries = retries.increment(method, url, response=response, _pool=conn)  # type: ignore[arg-type]
        except MaxRetryError:
            if retries.raise_on_redirect:
                response.drain_conn()
                raise
            return response

        kw["retries"] = retries
        kw["redirect"] = redirect

        log.info("Redirecting %s -> %s", url, redirect_location)

        response.drain_conn()
        return self.urlopen(method, redirect_location, **kw)


class ProxyManager(PoolManager):
    """
    Behaves just like :class:`PoolManager`, but sends all requests through
    the defined proxy, using the CONNECT method for HTTPS URLs.

    :param proxy_url:
        The URL of the proxy to be used.

    :param proxy_headers:
        A dictionary containing headers that will be sent to the proxy. In case
        of HTTP they are being sent with each request, while in the
        HTTPS/CONNECT case they are sent only once. Could be used for proxy
        authentication.

    :param proxy_ssl_context:
        The proxy SSL context is used to establish the TLS connection to the
        proxy when using HTTPS proxies.

    :param use_forwarding_for_https:
        (Defaults to False) If set to True will forward requests to the HTTPS
        proxy to be made on behalf of the client instead of creating a TLS
        tunnel via the CONNECT method. **Enabling this flag means that request
        and response headers and content will be visible from the HTTPS proxy**
        whereas tunneling keeps request and response headers and content
        private.  IP address, target hostname, SNI, and port are always visible
        to an HTTPS proxy even when this flag is disabled.

    Example:

    .. code-block:: python

        import urllib3

        proxy = urllib3.ProxyManager("https://localhost:3128/")

        resp1 = proxy.request("GET", "https://google.com/")
        resp2 = proxy.request("GET", "https://httpbin.org/")

        print(len(proxy.pools))
        # 1

        resp3 = proxy.request("GET", "https://httpbin.org/")
        resp4 = proxy.request("GET", "https://twitter.com/")

        print(len(proxy.pools))
        # 3

    """

    def __init__(
        self,
        proxy_url: str,
        num_pools: int = 10,
        headers: Optional[Mapping[str, str]] = None,
        proxy_headers: Optional[Mapping[str, str]] = None,
        proxy_ssl_context: Optional["ssl.SSLContext"] = None,
        use_forwarding_for_https: bool = False,
        **connection_pool_kw: Any,
    ) -> None:

        if isinstance(proxy_url, HTTPConnectionPool):
            str_proxy_url = f"{proxy_url.scheme}://{proxy_url.host}:{proxy_url.port}"
        else:
            str_proxy_url = proxy_url
        proxy = parse_url(str_proxy_url)

        if proxy.scheme not in ("http", "https"):
            raise ProxySchemeUnknown(proxy.scheme)

        if not proxy.port:
            port = port_by_scheme.get(proxy.scheme, 80)
            proxy = proxy._replace(port=port)

        self.proxy = proxy
        self.proxy_headers = proxy_headers or {}
        self.proxy_ssl_context = proxy_ssl_context
        self.proxy_config = ProxyConfig(proxy_ssl_context, use_forwarding_for_https)

        connection_pool_kw["_proxy"] = self.proxy
        connection_pool_kw["_proxy_headers"] = self.proxy_headers
        connection_pool_kw["_proxy_config"] = self.proxy_config

        super().__init__(num_pools, headers, **connection_pool_kw)

    def connection_from_host(
        self,
        host: Optional[str],
        port: Optional[int] = None,
        scheme: Optional[str] = "http",
        pool_kwargs: Optional[Dict[str, Any]] = None,
    ) -> HTTPConnectionPool:
        if scheme == "https":
            return super().connection_from_host(
                host, port, scheme, pool_kwargs=pool_kwargs
            )

        return super().connection_from_host(
            self.proxy.host, self.proxy.port, self.proxy.scheme, pool_kwargs=pool_kwargs  # type: ignore[union-attr]
        )

    def _set_proxy_headers(
        self, url: str, headers: Optional[Mapping[str, str]] = None
    ) -> Mapping[str, str]:
        """
        Sets headers needed by proxies: specifically, the Accept and Host
        headers. Only sets headers not provided by the user.
        """
        headers_ = {"Accept": "*/*"}

        netloc = parse_url(url).netloc
        if netloc:
            headers_["Host"] = netloc

        if headers:
            headers_.update(headers)
        return headers_

    def urlopen(  # type: ignore[override]
        self, method: str, url: str, redirect: bool = True, **kw: Any
    ) -> BaseHTTPResponse:
        "Same as HTTP(S)ConnectionPool.urlopen, ``url`` must be absolute."
        u = parse_url(url)
        if not connection_requires_http_tunnel(self.proxy, self.proxy_config, u.scheme):
            # For connections using HTTP CONNECT, httplib sets the necessary
            # headers on the CONNECT to the proxy. If we're not using CONNECT,
            # we'll definitely need to set 'Host' at the very least.
            headers = kw.get("headers", self.headers)
            kw["headers"] = self._set_proxy_headers(url, headers)

        return super().urlopen(method, url, redirect=redirect, **kw)


def proxy_from_url(url: str, **kw: Any) -> ProxyManager:
    return ProxyManager(proxy_url=url, **kw)

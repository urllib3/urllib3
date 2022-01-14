import datetime
import logging
import os
import re
import socket
import warnings
from copy import copy
from http.client import HTTPConnection as _HTTPConnection
from http.client import HTTPException as HTTPException  # noqa: F401
from socket import timeout as SocketTimeout
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Mapping,
    NamedTuple,
    Optional,
    Tuple,
    Union,
    cast,
)

if TYPE_CHECKING:
    from typing_extensions import Literal

    from .util.ssl_ import _TYPE_PEER_CERT_RET_DICT

from .util.proxy import create_proxy_ssl_context
from .util.timeout import _DEFAULT_TIMEOUT, _TYPE_TIMEOUT, Timeout
from .util.util import to_bytes, to_str

try:  # Compiled with SSL?
    import ssl

    BaseSSLError = ssl.SSLError
except (ImportError, AttributeError):  # Platform-specific: No SSL.
    ssl = None  # type: ignore[assignment]

    class BaseSSLError(BaseException):  # type: ignore[no-redef]
        pass


from ._version import __version__
from .exceptions import (
    ConnectTimeoutError,
    NameResolutionError,
    NewConnectionError,
    ProxyError,
    SystemTimeWarning,
)
from .util import SKIP_HEADER, SKIPPABLE_HEADERS, connection, ssl_
from .util.ssl_ import (
    assert_fingerprint,
    create_urllib3_context,
    resolve_cert_reqs,
    resolve_ssl_version,
    ssl_wrap_socket,
)
from .util.ssl_match_hostname import CertificateError, match_hostname

# Not a no-op, we're adding this to the namespace so it can be imported.
ConnectionError = ConnectionError
BrokenPipeError = BrokenPipeError


log = logging.getLogger(__name__)

port_by_scheme = {"http": 80, "https": 443}

# When it comes time to update this value as a part of regular maintenance
# (ie test_recent_date is failing) update it to ~6 months before the current date.
RECENT_DATE = datetime.date(2020, 7, 1)

_CONTAINS_CONTROL_CHAR_RE = re.compile(r"[^-!#$%&'*+.^_`|~0-9a-zA-Z]")


_TYPE_BODY = Union[bytes, IO[Any], Iterable[bytes], str]


class ProxyConfig(NamedTuple):
    ssl_context: Optional["ssl.SSLContext"]
    use_forwarding_for_https: bool


class HTTPConnection(_HTTPConnection):
    """
    Based on :class:`http.client.HTTPConnection` but provides an extra constructor
    backwards-compatibility layer between older and newer Pythons.

    Additional keyword parameters are used to configure attributes of the connection.
    Accepted parameters include:

    - ``source_address``: Set the source address for the current connection.
    - ``socket_options``: Set specific options on the underlying socket. If not specified, then
      defaults are loaded from ``HTTPConnection.default_socket_options`` which includes disabling
      Nagle's algorithm (sets TCP_NODELAY to 1) unless the connection is behind a proxy.

      For example, if you wish to enable TCP Keep Alive in addition to the defaults,
      you might pass:

      .. code-block:: python

         HTTPConnection.default_socket_options + [
             (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
         ]

      Or you may want to disable the defaults by passing an empty list (e.g., ``[]``).
    """

    default_port: int = port_by_scheme["http"]

    #: Disable Nagle's algorithm by default.
    #: ``[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]``
    default_socket_options: connection._TYPE_SOCKET_OPTIONS = [
        (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    ]

    #: Whether this connection verifies the host's certificate.
    is_verified: bool = False

    source_address: Optional[Tuple[str, int]]
    socket_options: Optional[connection._TYPE_SOCKET_OPTIONS]
    _tunnel_host: Optional[str]
    _tunnel: Callable[["HTTPConnection"], None]
    _connecting_to_proxy: bool

    def __init__(
        self,
        host: str,
        port: Optional[int] = None,
        timeout: _TYPE_TIMEOUT = _DEFAULT_TIMEOUT,
        source_address: Optional[Tuple[str, int]] = None,
        blocksize: int = 8192,
        socket_options: Optional[
            connection._TYPE_SOCKET_OPTIONS
        ] = default_socket_options,
        proxy: Optional[str] = None,
        proxy_config: Optional[ProxyConfig] = None,
    ) -> None:
        # Pre-set source_address.
        self.source_address = source_address

        self.socket_options = socket_options

        # Proxy options provided by the user.
        self.proxy = proxy
        self.proxy_config = proxy_config

        super().__init__(
            host=host,
            port=port,
            timeout=Timeout.resolve_default_timeout(timeout),
            source_address=source_address,
            blocksize=blocksize,
        )

        self._connecting_to_proxy = False

    # https://github.com/python/mypy/issues/4125
    # Mypy treats this as LSP violation, which is considered a bug.
    # If `host` is made a property it violates LSP, because a writeable attribute is overridden with a read-only one.
    # However, there is also a `host` setter so LSP is not violated.
    # Potentially, a `@host.deleter` might be needed depending on how this issue will be fixed.
    @property  # type: ignore[override]
    def host(self) -> str:  # type: ignore[override]
        """
        Getter method to remove any trailing dots that indicate the hostname is an FQDN.

        In general, SSL certificates don't include the trailing dot indicating a
        fully-qualified domain name, and thus, they don't validate properly when
        checked against a domain name that includes the dot. In addition, some
        servers may not expect to receive the trailing dot when provided.

        However, the hostname with trailing dot is critical to DNS resolution; doing a
        lookup with the trailing dot will properly only resolve the appropriate FQDN,
        whereas a lookup without a trailing dot will search the system's search domain
        list. Thus, it's important to keep the original host around for use only in
        those cases where it's appropriate (i.e., when doing DNS lookup to establish the
        actual TCP connection across which we're going to send HTTP requests).
        """
        return self._dns_host.rstrip(".")

    @host.setter
    def host(self, value: str) -> None:
        """
        Setter for the `host` property.

        We assume that only urllib3 uses the _dns_host attribute; httplib itself
        only uses `host`, and it seems reasonable that other libraries follow suit.
        """
        self._dns_host = value

    def _new_conn(self) -> socket.socket:
        """Establish a socket connection and set nodelay settings on it.

        :return: New socket connection.
        """

        try:
            conn = connection.create_connection(
                (self._dns_host, self.port),
                self.timeout,
                source_address=self.source_address,
                socket_options=self.socket_options,
            )
        except socket.gaierror as e:
            raise NameResolutionError(self.host, self, e) from e
        except SocketTimeout as e:
            raise ConnectTimeoutError(
                self,
                f"Connection to {self.host} timed out. (connect timeout={self.timeout})",
            ) from e

        except OSError as e:
            raise NewConnectionError(
                self, f"Failed to establish a new connection: {e}"
            ) from e

        return conn

    def _is_using_tunnel(self) -> Optional[str]:
        return self._tunnel_host

    def _prepare_conn(self, conn: socket.socket) -> None:
        self.sock = conn
        if self._is_using_tunnel():
            # TODO: Fix tunnel so it doesn't depend on self.sock state.
            self._tunnel()
            self._connecting_to_proxy = False
            # Mark this connection as not reusable
            self.auto_open = 0

    def connect(self) -> None:
        self._connecting_to_proxy = bool(self.proxy)
        conn = self._new_conn()
        self._prepare_conn(conn)
        self._connecting_to_proxy = False

    def close(self) -> None:
        self._connecting_to_proxy = False
        super().close()

    def putrequest(
        self,
        method: str,
        url: str,
        skip_host: bool = False,
        skip_accept_encoding: bool = False,
    ) -> None:
        """"""
        # Empty docstring because the indentation of CPython's implementation
        # is broken but we don't want this method in our documentation.
        match = _CONTAINS_CONTROL_CHAR_RE.search(method)
        if match:
            raise ValueError(
                f"Method cannot contain non-token characters {method!r} (found at least {match.group()!r})"
            )

        return super().putrequest(
            method, url, skip_host=skip_host, skip_accept_encoding=skip_accept_encoding
        )

    def putheader(self, header: str, *values: str) -> None:
        """"""
        if not any(isinstance(v, str) and v == SKIP_HEADER for v in values):
            super().putheader(header, *values)
        elif to_str(header.lower()) not in SKIPPABLE_HEADERS:
            skippable_headers = "', '".join(
                [str.title(header) for header in sorted(SKIPPABLE_HEADERS)]
            )
            raise ValueError(
                f"urllib3.util.SKIP_HEADER only supports '{skippable_headers}'"
            )

    # `request` method's signature intentionally violates LSP.
    # urllib3's API is different from `http.client.HTTPConnection` and the subclassing is only incidental.
    def request(  # type: ignore[override]
        self,
        method: str,
        url: str,
        body: Optional[_TYPE_BODY] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        if headers is None:
            headers = {}
        else:
            # Avoid modifying the headers passed into .request()
            headers = copy(headers)
            # Don't send bytes keys to httplib to avoid bytes/str comparison
            # HTTPHeaderDict is already safe, but other types are not
            for key, value in list(headers.items()):
                if isinstance(key, bytes):
                    headers.pop(key)
                    # httplib would have decoded to latin-1 anyway
                    headers[key.decode("latin-1")] = value

        if "user-agent" not in (to_str(k.lower()) for k in headers):
            updated_headers = {"User-Agent": _get_default_user_agent()}
            updated_headers.update(headers)
            headers = updated_headers
        super().request(method, url, body=body, headers=headers)

    def request_chunked(
        self,
        method: str,
        url: str,
        body: Optional[_TYPE_BODY] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        """
        Alternative to the common request method, which sends the
        body with chunked encoding and not as one block
        """
        if headers is None:
            headers = {}
        header_keys = {to_str(k.lower()) for k in headers}
        skip_accept_encoding = "accept-encoding" in header_keys
        skip_host = "host" in header_keys
        self.putrequest(
            method, url, skip_accept_encoding=skip_accept_encoding, skip_host=skip_host
        )
        if "user-agent" not in header_keys:
            self.putheader("User-Agent", _get_default_user_agent())
        for header, value in headers.items():
            self.putheader(header, value)
        if "transfer-encoding" not in header_keys:
            self.putheader("Transfer-Encoding", "chunked")
        self.endheaders()

        if body is not None:
            if isinstance(body, (str, bytes)):
                body = (to_bytes(body),)
            for chunk in body:
                if not chunk:
                    continue
                if not isinstance(chunk, bytes):
                    chunk = chunk.encode("utf8")
                len_str = hex(len(chunk))[2:]
                to_send = bytearray(len_str.encode())
                to_send += b"\r\n"
                to_send += chunk
                to_send += b"\r\n"
                self.send(to_send)

        # After the if clause, to always have a closed body
        self.send(b"0\r\n\r\n")


class HTTPSConnection(HTTPConnection):
    """
    Many of the parameters to this constructor are passed to the underlying SSL
    socket by means of :py:func:`urllib3.util.ssl_wrap_socket`.
    """

    default_port = port_by_scheme["https"]

    cert_reqs: Optional[Union[int, str]] = None
    ca_certs: Optional[str] = None
    ca_cert_dir: Optional[str] = None
    ca_cert_data: Union[None, str, bytes] = None
    ssl_version: Optional[Union[int, str]] = None
    ssl_minimum_version: Optional[int] = None
    ssl_maximum_version: Optional[int] = None
    assert_fingerprint: Optional[str] = None
    tls_in_tls_required: bool = False

    def __init__(
        self,
        host: str,
        port: Optional[int] = None,
        key_file: Optional[str] = None,
        cert_file: Optional[str] = None,
        key_password: Optional[str] = None,
        timeout: _TYPE_TIMEOUT = _DEFAULT_TIMEOUT,
        ssl_context: Optional["ssl.SSLContext"] = None,
        server_hostname: Optional[str] = None,
        source_address: Optional[Tuple[str, int]] = None,
        blocksize: int = 8192,
        socket_options: Optional[
            connection._TYPE_SOCKET_OPTIONS
        ] = HTTPConnection.default_socket_options,
        proxy: Optional[str] = None,
        proxy_config: Optional[ProxyConfig] = None,
    ) -> None:

        super().__init__(
            host,
            port=port,
            timeout=timeout,
            source_address=source_address,
            blocksize=blocksize,
            socket_options=socket_options,
            proxy=proxy,
            proxy_config=proxy_config,
        )

        self.key_file = key_file
        self.cert_file = cert_file
        self.key_password = key_password
        self.ssl_context = ssl_context
        self.server_hostname = server_hostname
        self.ssl_version = None
        self.ssl_minimum_version = None
        self.ssl_maximum_version = None

    def set_cert(
        self,
        key_file: Optional[str] = None,
        cert_file: Optional[str] = None,
        cert_reqs: Optional[Union[int, str]] = None,
        key_password: Optional[str] = None,
        ca_certs: Optional[str] = None,
        assert_hostname: Union[None, str, "Literal[False]"] = None,
        assert_fingerprint: Optional[str] = None,
        ca_cert_dir: Optional[str] = None,
        ca_cert_data: Union[None, str, bytes] = None,
    ) -> None:
        """
        This method should only be called once, before the connection is used.
        """
        # If cert_reqs is not provided we'll assume CERT_REQUIRED unless we also
        # have an SSLContext object in which case we'll use its verify_mode.
        if cert_reqs is None:
            if self.ssl_context is not None:
                cert_reqs = self.ssl_context.verify_mode
            else:
                cert_reqs = resolve_cert_reqs(None)

        self.key_file = key_file
        self.cert_file = cert_file
        self.cert_reqs = cert_reqs
        self.key_password = key_password
        self.assert_hostname = assert_hostname
        self.assert_fingerprint = assert_fingerprint
        self.ca_certs = ca_certs and os.path.expanduser(ca_certs)
        self.ca_cert_dir = ca_cert_dir and os.path.expanduser(ca_cert_dir)
        self.ca_cert_data = ca_cert_data

    def connect(self) -> None:
        self._connecting_to_proxy = bool(self.proxy)
        # Add certificate verification
        conn = self._new_conn()
        hostname: str = self.host
        tls_in_tls = False

        if self._is_using_tunnel():
            if self.tls_in_tls_required:
                conn = self._connect_tls_proxy(hostname, conn)
                tls_in_tls = True

            self._connecting_to_proxy = False
            self.sock = conn

            # Calls self._set_hostport(), so self.host is
            # self._tunnel_host below.
            self._tunnel()
            # Mark this connection as not reusable
            self.auto_open = 0

            # Override the host with the one we're requesting data from.
            hostname = cast(
                str, self._tunnel_host
            )  # self._tunnel_host is not None, because self._is_using_tunnel() returned a truthy value.

        server_hostname = hostname
        if self.server_hostname is not None:
            server_hostname = self.server_hostname

        is_time_off = datetime.date.today() < RECENT_DATE
        if is_time_off:
            warnings.warn(
                (
                    f"System time is way off (before {RECENT_DATE}). This will probably "
                    "lead to SSL verification errors"
                ),
                SystemTimeWarning,
            )

        # Wrap socket using verification with the root certs in
        # trusted_root_certs
        default_ssl_context = False
        if self.ssl_context is None:
            default_ssl_context = True
            self.ssl_context = create_urllib3_context(
                ssl_version=resolve_ssl_version(self.ssl_version),
                ssl_minimum_version=self.ssl_minimum_version,
                ssl_maximum_version=self.ssl_maximum_version,
                cert_reqs=resolve_cert_reqs(self.cert_reqs),
            )
            # In some cases, we want to verify hostnames ourselves
            if (
                # `ssl` can't verify fingerprints or alternate hostnames
                self.assert_fingerprint
                or self.assert_hostname
                # We still support OpenSSL 1.0.2, which prevents us from verifying
                # hostnames easily: https://github.com/pyca/pyopenssl/pull/933
                or ssl_.IS_PYOPENSSL
                or not ssl_.HAS_NEVER_CHECK_COMMON_NAME
            ):
                self.ssl_context.check_hostname = False

        context = self.ssl_context
        context.verify_mode = resolve_cert_reqs(self.cert_reqs)

        # Try to load OS default certs if none are given.
        # Works well on Windows.
        if (
            not self.ca_certs
            and not self.ca_cert_dir
            and not self.ca_cert_data
            and default_ssl_context
            and hasattr(context, "load_default_certs")
        ):
            context.load_default_certs()

        self.sock = ssl_wrap_socket(
            sock=conn,
            keyfile=self.key_file,
            certfile=self.cert_file,
            key_password=self.key_password,
            ca_certs=self.ca_certs,
            ca_cert_dir=self.ca_cert_dir,
            ca_cert_data=self.ca_cert_data,
            server_hostname=server_hostname,
            ssl_context=context,
            tls_in_tls=tls_in_tls,
        )
        self._connecting_to_proxy = False

        if self.assert_fingerprint:
            assert_fingerprint(
                self.sock.getpeercert(binary_form=True), self.assert_fingerprint
            )
        elif (
            context.verify_mode != ssl.CERT_NONE
            and not context.check_hostname
            and self.assert_hostname is not False
        ):
            cert: "_TYPE_PEER_CERT_RET_DICT" = self.sock.getpeercert()  # type: ignore[assignment]

            # Need to signal to our match_hostname whether to use 'commonName' or not.
            # If we're using our own constructed SSLContext we explicitly set 'False'
            # because PyPy hard-codes 'True' from SSLContext.hostname_checks_common_name.
            if default_ssl_context:
                hostname_checks_common_name = False
            else:
                hostname_checks_common_name = (
                    getattr(context, "hostname_checks_common_name", False) or False
                )

            _match_hostname(
                cert,
                self.assert_hostname or server_hostname,
                hostname_checks_common_name,
            )

        self.is_verified = context.verify_mode == ssl.CERT_REQUIRED or bool(
            self.assert_fingerprint
        )

    def _connect_tls_proxy(self, hostname: str, conn: socket.socket) -> "ssl.SSLSocket":
        """
        Establish a TLS connection to the proxy using the provided SSL context.
        """

        proxy_config = cast(
            ProxyConfig, self.proxy_config
        )  # `_connect_tls_proxy` is called when self._is_using_tunnel() is truthy.
        ssl_context = proxy_config.ssl_context

        if ssl_context:
            # If the user provided a proxy context, we assume CA and client
            # certificates have already been set
            return ssl_wrap_socket(
                sock=conn,
                server_hostname=hostname,
                ssl_context=ssl_context,
            )

        ssl_context = create_proxy_ssl_context(
            self.ssl_version,
            self.cert_reqs,
            self.ca_certs,
            self.ca_cert_dir,
            self.ca_cert_data,
        )

        # If no cert was provided, use only the default options for server
        # certificate validation
        return ssl_wrap_socket(
            sock=conn,
            ca_certs=self.ca_certs,
            ca_cert_dir=self.ca_cert_dir,
            ca_cert_data=self.ca_cert_data,
            server_hostname=hostname,
            ssl_context=ssl_context,
        )


def _match_hostname(
    cert: Optional["_TYPE_PEER_CERT_RET_DICT"],
    asserted_hostname: str,
    hostname_checks_common_name: bool = False,
) -> None:
    try:
        match_hostname(cert, asserted_hostname, hostname_checks_common_name)
    except CertificateError as e:
        log.warning(
            "Certificate did not match expected hostname: %s. Certificate: %s",
            asserted_hostname,
            cert,
        )
        # Add cert to exception and reraise so client code can inspect
        # the cert when catching the exception, if they want to
        e._peer_cert = cert  # type: ignore[attr-defined]
        raise


def _wrap_proxy_error(err: Exception) -> ProxyError:
    # Look for the phrase 'wrong version number', if found
    # then we should warn the user that we're very sure that
    # this proxy is HTTP-only and they have a configuration issue.
    error_normalized = " ".join(re.split("[^a-z]", str(err).lower()))
    is_likely_http_proxy = "wrong version number" in error_normalized
    http_proxy_warning = (
        ". Your proxy appears to only use HTTP and not HTTPS, "
        "did you intend to set a proxy URL using HTTPS instead of HTTP?"
    )
    new_err = ProxyError(
        f"Unable to connect to proxy"
        f"{http_proxy_warning if is_likely_http_proxy else ''}",
        err,
    )
    new_err.__cause__ = err
    return new_err


def _get_default_user_agent() -> str:
    return f"python-urllib3/{__version__}"


class DummyConnection:
    """Used to detect a failed ConnectionCls import."""

    pass


if not ssl:
    HTTPSConnection = DummyConnection  # type: ignore[misc, assignment] # noqa: F811


VerifiedHTTPSConnection = HTTPSConnection

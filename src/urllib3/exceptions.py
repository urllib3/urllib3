import socket
import warnings
from email.errors import MessageDefect
from http.client import IncompleteRead as httplib_IncompleteRead
from typing import TYPE_CHECKING, Callable, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from .connection import HTTPConnection
    from .connectionpool import ConnectionPool
    from .response import HTTPResponse
    from .util.retry import Retry

# Base Exceptions


class HTTPError(Exception):
    """Base exception used by this module."""

    pass


class HTTPWarning(Warning):
    """Base warning used by this module."""

    pass


_TYPE_REDUCE_RESULT = Tuple[Callable[..., object], Tuple[object, ...]]


class PoolError(HTTPError):
    """Base exception for errors caused within a pool."""

    def __init__(self, pool: "ConnectionPool", message: str) -> None:
        self.pool = pool
        super().__init__(f"{pool}: {message}")

    def __reduce__(self) -> _TYPE_REDUCE_RESULT:
        # For pickling purposes.
        return self.__class__, (None, None)


class RequestError(PoolError):
    """Base exception for PoolErrors that have associated URLs."""

    def __init__(self, pool: "ConnectionPool", url: str, message: str) -> None:
        self.url = url
        super().__init__(pool, message)

    def __reduce__(self) -> _TYPE_REDUCE_RESULT:
        # For pickling purposes.
        return self.__class__, (None, self.url, None)


class SSLError(HTTPError):
    """Raised when SSL certificate fails in an HTTPS connection."""

    pass


class ProxyError(HTTPError):
    """Raised when the connection to a proxy fails."""

    # The original error is also available as __cause__.
    original_error: Exception

    def __init__(self, message: str, error: Exception) -> None:
        super().__init__(message, error)
        self.original_error = error


class DecodeError(HTTPError):
    """Raised when automatic decoding based on Content-Type fails."""

    pass


class ProtocolError(HTTPError):
    """Raised when something unexpected happens mid-request/response."""

    pass


#: Renamed to ProtocolError but aliased for backwards compatibility.
ConnectionError = ProtocolError


# Leaf Exceptions


class MaxRetryError(RequestError):
    """Raised when the maximum number of retries is exceeded.

    :param pool: The connection pool
    :type pool: :class:`~urllib3.connectionpool.HTTPConnectionPool`
    :param string url: The requested Url
    :param exceptions.Exception reason: The underlying error

    """

    def __init__(
        self, pool: "ConnectionPool", url: str, reason: Optional[Exception] = None
    ) -> None:
        self.reason = reason

        message = f"Max retries exceeded with url: {url} (Caused by {reason!r})"

        super().__init__(pool, url, message)


class HostChangedError(RequestError):
    """Raised when an existing pool gets a request for a foreign host."""

    def __init__(
        self, pool: "ConnectionPool", url: str, retries: Union["Retry", int] = 3
    ) -> None:
        message = f"Tried to open a foreign host with url: {url}"
        super().__init__(pool, url, message)
        self.retries = retries


class TimeoutStateError(HTTPError):
    """Raised when passing an invalid state to a timeout"""

    pass


class TimeoutError(HTTPError):
    """Raised when a socket timeout error occurs.

    Catching this error will catch both :exc:`ReadTimeoutErrors
    <ReadTimeoutError>` and :exc:`ConnectTimeoutErrors <ConnectTimeoutError>`.
    """

    pass


class ReadTimeoutError(TimeoutError, RequestError):
    """Raised when a socket timeout occurs while receiving data from a server"""

    pass


# This timeout error does not have a URL attached and needs to inherit from the
# base HTTPError
class ConnectTimeoutError(TimeoutError):
    """Raised when a socket timeout occurs while connecting to a server"""

    pass


class NewConnectionError(ConnectTimeoutError, HTTPError):
    """Raised when we fail to establish a new connection. Usually ECONNREFUSED."""

    def __init__(self, conn: "HTTPConnection", message: str) -> None:
        self.conn = conn
        super().__init__(f"{conn}: {message}")

    @property
    def pool(self) -> "HTTPConnection":
        warnings.warn(
            "The 'pool' property is deprecated and will be removed "
            "in a later urllib3 v2.x release. use 'conn' instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        return self.conn


class NameResolutionError(NewConnectionError):
    """Raised when host name resolution fails."""

    def __init__(self, host: str, conn: "HTTPConnection", reason: socket.gaierror):
        message = f"Failed to resolve '{host}' ({reason})"
        super().__init__(conn, message)


class EmptyPoolError(PoolError):
    """Raised when a pool runs out of connections and no more are allowed."""

    pass


class FullPoolError(PoolError):
    """Raised when we try to add a connection to a full pool in blocking mode."""

    pass


class ClosedPoolError(PoolError):
    """Raised when a request enters a pool after the pool has been closed."""

    pass


class LocationValueError(ValueError, HTTPError):
    """Raised when there is something wrong with a given URL input."""

    pass


class LocationParseError(LocationValueError):
    """Raised when get_host or similar fails to parse the URL input."""

    def __init__(self, location: str) -> None:
        message = f"Failed to parse: {location}"
        super().__init__(message)

        self.location = location


class URLSchemeUnknown(LocationValueError):
    """Raised when a URL input has an unsupported scheme."""

    def __init__(self, scheme: str):
        message = f"Not supported URL scheme {scheme}"
        super().__init__(message)

        self.scheme = scheme


class ResponseError(HTTPError):
    """Used as a container for an error reason supplied in a MaxRetryError."""

    GENERIC_ERROR = "too many error responses"
    SPECIFIC_ERROR = "too many {status_code} error responses"


class SecurityWarning(HTTPWarning):
    """Warned when performing security reducing actions"""

    pass


class InsecureRequestWarning(SecurityWarning):
    """Warned when making an unverified HTTPS request."""

    pass


class SystemTimeWarning(SecurityWarning):
    """Warned when system time is suspected to be wrong"""

    pass


class InsecurePlatformWarning(SecurityWarning):
    """Warned when certain TLS/SSL configuration is not available on a platform."""

    pass


class SNIMissingWarning(HTTPWarning):
    """Warned when making a HTTPS request without SNI available."""

    pass


class DependencyWarning(HTTPWarning):
    """
    Warned when an attempt is made to import a module with missing optional
    dependencies.
    """

    pass


class ResponseNotChunked(ProtocolError, ValueError):
    """Response needs to be chunked in order to read it as chunks."""

    pass


class BodyNotHttplibCompatible(HTTPError):
    """
    Body should be :class:`http.client.HTTPResponse` like
    (have an fp attribute which returns raw chunks) for read_chunked().
    """

    pass


class IncompleteRead(HTTPError, httplib_IncompleteRead):
    """
    Response length doesn't match expected Content-Length

    Subclass of :class:`http.client.IncompleteRead` to allow int value
    for ``partial`` to avoid creating large objects on streamed reads.
    """

    def __init__(self, partial: int, expected: int) -> None:
        self.partial = partial  # type: ignore[assignment]
        self.expected = expected

    def __repr__(self) -> str:
        return "IncompleteRead(%i bytes read, %i more expected)" % (
            self.partial,  # type: ignore[str-format]
            self.expected,
        )


class InvalidChunkLength(HTTPError, httplib_IncompleteRead):
    """Invalid chunk length in a chunked response."""

    def __init__(self, response: "HTTPResponse", length: bytes) -> None:
        self.partial: int = response.tell()  # type: ignore[assignment]
        self.expected: Optional[int] = response.length_remaining
        self.response = response
        self.length = length

    def __repr__(self) -> str:
        return "InvalidChunkLength(got length %r, %i bytes read)" % (
            self.length,
            self.partial,
        )


class InvalidHeader(HTTPError):
    """The header provided was somehow invalid."""

    pass


class ProxySchemeUnknown(AssertionError, URLSchemeUnknown):
    """ProxyManager does not support the supplied scheme"""

    # TODO(t-8ch): Stop inheriting from AssertionError in v2.0.

    def __init__(self, scheme: Optional[str]) -> None:
        # 'localhost' is here because our URL parser parses
        # localhost:8080 -> scheme=localhost, remove if we fix this.
        if scheme == "localhost":
            scheme = None
        if scheme is None:
            message = "Proxy URL had no scheme, should start with http:// or https://"
        else:
            message = f"Proxy URL had unsupported scheme {scheme}, should use http:// or https://"
        super().__init__(message)


class ProxySchemeUnsupported(ValueError):
    """Fetching HTTPS resources through HTTPS proxies is unsupported"""

    pass


class HeaderParsingError(HTTPError):
    """Raised by assert_header_parsing, but we convert it to a log.warning statement."""

    def __init__(
        self, defects: List[MessageDefect], unparsed_data: Optional[Union[bytes, str]]
    ) -> None:
        message = f"{defects or 'Unknown'}, unparsed data: {unparsed_data!r}"
        super().__init__(message)


class UnrewindableBodyError(HTTPError):
    """urllib3 encountered an error when trying to rewind a body"""

    pass

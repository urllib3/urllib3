from __future__ import annotations

import enum
import socket
import typing

if typing.TYPE_CHECKING:
    from ssl import SSLSocket, SSLContext

from .._collections import HTTPHeaderDict
from ..util import connection


class HttpVersion(str, enum.Enum):
    """Describe possible SVN protocols that can be supported."""

    h11 = "HTTP/1.1"
    # we know that it is rather "HTTP/2" than "HTTP/2.0"
    # it is this way to remain somewhat compatible with http.client
    # http_svn (int). 9 -> 11 -> 20 -> 30
    h2 = "HTTP/2.0"
    h3 = "HTTP/3.0"


class ProxyHttpLibResponse:
    """Implemented for backward compatibility purposes. It is there to impose http.client like
    basic response object. So that we don't have to change urllib3 tested behaviors."""

    def __init__(
        self,
        status: int,
        version: int,
        reason: str,
        headers: HTTPHeaderDict,
        body: typing.Callable[[int | None], tuple[bytes, bool]] | None,
        *,
        method: str | None = None,
        authority: str | None = None,
        port: int | None = None,
    ):
        self.status = status
        self.version = version
        self.reason = reason
        self.msg = headers
        self._method = method

        self.__internal_read_st = body
        self.closed = True if self.__internal_read_st is None else False
        self._eot = True if self.__internal_read_st is None else False

        # is kept to determine if we can upgrade conn
        self.authority = authority
        self.port = port

        self.__buffer_excess: bytes = b""

    def isclosed(self) -> bool:
        """Here we do not create a fp sock like http.client Response."""
        return self.closed

    def read(self, __size: int | None = None) -> bytes:
        if self.closed is True or self.__internal_read_st is None:
            # overly protective, just in case.
            raise ValueError(
                "I/O operation on closed file."
            )  # Defensive: Should not be reachable in normal condition

        if __size == 0:
            return b""  # Defensive: This is unreachable, this case is already covered higher in the stack.

        if self._eot is False:
            data, self._eot = self.__internal_read_st(__size)

            # that's awkward, but rather no choice. the state machine
            # consume and render event regardless of your amt !
            if self.__buffer_excess:
                data = (  # Defensive: Difficult to put in place a scenario that verify this
                    self.__buffer_excess + data
                )
                self.__buffer_excess = b""  # Defensive:
        else:
            if __size is None:
                data = self.__buffer_excess
            else:
                data = self.__buffer_excess[:__size]
                self.__buffer_excess = self.__buffer_excess[__size:]

        if __size is not None and len(data) > __size:
            self.__buffer_excess = data[__size:]
            data = data[:__size]

        if self._eot and len(self.__buffer_excess) == 0:
            self.closed = True

        return data

    def close(self) -> None:
        self.__internal_read_st = None
        self.closed = True


_HostPortType = typing.Tuple[str, int]
QuicPreemptiveCacheType = typing.MutableMapping[
    _HostPortType, typing.Optional[_HostPortType]
]


class BaseBackend:
    """
    The goal here is to detach ourselves from the http.client package.
    At first, we'll strictly follow the methods in http.client.HTTPConnection. So that
    we would be able to implement other backend without disrupting the actual code base.
    Extend that base class in order to ship another backend with urllib3.
    """

    supported_svn: typing.ClassVar[list[HttpVersion] | None] = None
    scheme: typing.ClassVar[str]

    default_socket_kind: socket.SocketKind = socket.SOCK_STREAM
    #: Disable Nagle's algorithm by default.
    default_socket_options: typing.ClassVar[connection._TYPE_SOCKET_OPTIONS] = [
        (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    ]

    #: Whether this connection verifies the host's certificate.
    is_verified: bool = False

    #: Whether this proxy connection verified the proxy host's certificate.
    # If no proxy is currently connected to the value will be ``None``.
    proxy_is_verified: bool | None = None

    def __init__(
        self,
        host: str,
        port: int | None = None,
        timeout: int = -1,
        source_address: tuple[str, int] | None = None,
        blocksize: int = 8192,
        *,
        socket_options: None
        | (connection._TYPE_SOCKET_OPTIONS) = default_socket_options,
        disabled_svn: set[HttpVersion] | None = None,
        preemptive_quic_cache: QuicPreemptiveCacheType | None = None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.source_address = source_address
        self.blocksize = blocksize
        self.socket_kind = BaseBackend.default_socket_kind
        self.socket_options = socket_options
        self.sock: socket.socket | SSLSocket | None = None

        self._response: ProxyHttpLibResponse | None = None
        # Set it as default
        self._svn: HttpVersion | None = HttpVersion.h11

        self._tunnel_host: str | None = None
        self._tunnel_port: int | None = None
        self._tunnel_scheme: str | None = None
        self._tunnel_headers: typing.Mapping[str, str] = dict()

        self._disabled_svn = disabled_svn or set()
        self._preemptive_quic_cache = preemptive_quic_cache

        if self._disabled_svn:
            if HttpVersion.h11 in self._disabled_svn:
                raise RuntimeError(
                    "HTTP/1.1 cannot be disabled. It will be allowed in a future urllib3 version."
                )

    @property
    def disabled_svn(self) -> set[HttpVersion]:
        return self._disabled_svn

    @property
    def _http_vsn_str(self) -> str:
        """Reimplemented for backward compatibility purposes."""
        assert self._svn is not None
        return self._svn.value

    @property
    def _http_vsn(self) -> int:
        """Reimplemented for backward compatibility purposes."""
        assert self._svn is not None
        return int(self._svn.value.split("/")[-1].replace(".", ""))

    def _upgrade(self) -> None:
        """Upgrade conn from svn ver to max supported."""
        raise NotImplementedError

    def _tunnel(self) -> None:
        """Emit proper CONNECT request to the http (server) intermediary."""
        raise NotImplementedError

    def _new_conn(self) -> socket.socket | None:
        """Run protocol initialization from there. Return None to ensure that the child
        class correctly create the socket / connection."""
        raise NotImplementedError

    def _post_conn(self) -> None:
        """Should be called after _new_conn proceed as expected.
        Expect protocol handshake to be done here."""
        raise NotImplementedError

    def _custom_tls(
        self,
        ssl_context: SSLContext | None = None,
        ca_certs: str | None = None,
        ca_cert_dir: str | None = None,
        ca_cert_data: None | str | bytes = None,
        ssl_minimum_version: int | None = None,
        ssl_maximum_version: int | None = None,
        cert_file: str | None = None,
        key_file: str | None = None,
        key_password: str | None = None,
    ) -> None:
        """This method serve as bypassing any default tls setup.
        It is most useful when the encryption does not lie on the TCP layer. This method
        WILL raise NotImplementedError if the connection is not concerned."""
        raise NotImplementedError

    def set_tunnel(
        self,
        host: str,
        port: int | None = None,
        headers: typing.Mapping[str, str] | None = None,
        scheme: str = "http",
    ) -> None:
        """Prepare the connection to set up a tunnel. Does NOT actually do the socket and http connect.
        Here host:port represent the target (final) server and not the intermediary."""
        raise NotImplementedError

    def putrequest(
        self,
        method: str,
        url: str,
        skip_host: bool = False,
        skip_accept_encoding: bool = False,
    ) -> None:
        """It is the first method called, setting up the request initial context."""
        raise NotImplementedError

    def putheader(self, header: str, *values: str) -> None:
        """For a single header name, assign one or multiple value. This method is called right after putrequest()
        for each entries."""
        raise NotImplementedError

    def endheaders(
        self, message_body: bytes | None = None, *, encode_chunked: bool = False
    ) -> None:
        """This method conclude the request context construction."""
        raise NotImplementedError

    def getresponse(self) -> ProxyHttpLibResponse:
        """Fetch the HTTP response. You SHOULD not retrieve the body in that method, it SHOULD be done
        in the ProxyHttpLibResponse, so it enable stream capabilities and remain efficient.
        """
        raise NotImplementedError

    def close(self) -> None:
        """End the connection, do some reinit, closing of fd, etc..."""
        raise NotImplementedError

    def send(
        self,
        data: (bytes | typing.IO[typing.Any] | typing.Iterable[bytes] | str),
    ) -> None:
        """The send() method SHOULD be invoked after calling endheaders() if and only if the request
        context specify explicitly that a body is going to be sent."""
        raise NotImplementedError

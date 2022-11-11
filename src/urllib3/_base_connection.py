import typing

from .util.connection import _TYPE_SOCKET_OPTIONS
from .util.timeout import _DEFAULT_TIMEOUT, _TYPE_TIMEOUT
from .util.url import Url

_TYPE_BODY = typing.Union[bytes, typing.IO[typing.Any], typing.Iterable[bytes], str]


class ProxyConfig(typing.NamedTuple):
    ssl_context: typing.Optional["ssl.SSLContext"]
    use_forwarding_for_https: bool
    assert_hostname: typing.Union[None, str, "Literal[False]"]
    assert_fingerprint: typing.Optional[str]


class _ResponseOptions(typing.NamedTuple):
    # TODO: Remove this in favor of a better
    # HTTP request/response lifecycle tracking.
    request_method: str
    request_url: str
    preload_content: bool
    decode_content: bool
    enforce_content_length: bool


if typing.TYPE_CHECKING:
    import ssl

    from typing_extensions import Literal, Protocol

    from .response import BaseHTTPResponse

    class BaseHTTPConnection(Protocol):
        default_port: typing.ClassVar[int]
        default_socket_options: typing.ClassVar[_TYPE_SOCKET_OPTIONS]

        host: str
        port: int
        timeout: typing.Optional[
            float
        ]  # Instance doesn't store _DEFAULT_TIMEOUT, must be resolved.
        blocksize: int
        source_address: typing.Optional[typing.Tuple[str, int]]
        socket_options: typing.Optional[_TYPE_SOCKET_OPTIONS]

        proxy: typing.Optional[Url]
        proxy_config: typing.Optional[ProxyConfig]

        is_verified: bool
        proxy_is_verified: typing.Optional[bool]

        def __init__(
            self,
            host: str,
            port: typing.Optional[int] = None,
            *,
            timeout: _TYPE_TIMEOUT = _DEFAULT_TIMEOUT,
            source_address: typing.Optional[typing.Tuple[str, int]] = None,
            blocksize: int = 8192,
            socket_options: typing.Optional[_TYPE_SOCKET_OPTIONS] = ...,
            proxy: typing.Optional[Url] = None,
            proxy_config: typing.Optional[ProxyConfig] = None,
        ) -> None:
            ...

        def set_tunnel(
            self,
            host: str,
            port: typing.Optional[int] = None,
            headers: typing.Optional[typing.Mapping[str, str]] = None,
            scheme: str = "http",
        ) -> None:
            ...

        def connect(self) -> None:
            ...

        def request(
            self,
            method: str,
            url: str,
            body: typing.Optional[_TYPE_BODY] = None,
            headers: typing.Optional[typing.Mapping[str, str]] = None,
            # We know *at least* botocore is depending on the order of the
            # first 3 parameters so to be safe we only mark the later ones
            # as keyword-only to ensure we have space to extend.
            *,
            chunked: bool = False,
            preload_content: bool = True,
            decode_content: bool = True,
            enforce_content_length: bool = True,
        ) -> None:
            ...

        def getresponse(self) -> "BaseHTTPResponse":
            ...

        def close(self) -> None:
            ...

        @property
        def is_closed(self) -> bool:
            """Whether the connection either is brand new or has been previously closed.
            If this property is True then both ``is_connected`` and ``has_connected_to_proxy``
            properties must be False.
            """

        @property
        def is_connected(self) -> bool:
            """Whether the connection is actively connected to any origin (proxy or target)"""

        @property
        def has_connected_to_proxy(self) -> bool:
            """Whether the connection has successfully connected to its proxy.
            This returns False if no proxy is in use. Used to determine whether
            errors are coming from the proxy layer or from tunnelling to the target origin.
            """

    class BaseHTTPSConnection(BaseHTTPConnection, Protocol):
        default_port: typing.ClassVar[int]
        default_socket_options: typing.ClassVar[_TYPE_SOCKET_OPTIONS]

        # Certificate verification methods
        cert_reqs: typing.Optional[typing.Union[int, str]]
        assert_hostname: typing.Union[None, str, "Literal[False]"]
        assert_fingerprint: typing.Optional[str]
        ssl_context: typing.Optional[ssl.SSLContext]

        # Trusted CAs
        ca_certs: typing.Optional[str]
        ca_cert_dir: typing.Optional[str]
        ca_cert_data: typing.Union[None, str, bytes]

        # TLS version
        ssl_minimum_version: typing.Optional[int]
        ssl_maximum_version: typing.Optional[int]
        ssl_version: typing.Optional[typing.Union[int, str]]  # Deprecated

        # Client certificates
        cert_file: typing.Optional[str]
        key_file: typing.Optional[str]
        key_password: typing.Optional[str]

        def __init__(
            self,
            host: str,
            port: typing.Optional[int] = None,
            *,
            timeout: _TYPE_TIMEOUT = _DEFAULT_TIMEOUT,
            source_address: typing.Optional[typing.Tuple[str, int]] = None,
            blocksize: int = 8192,
            socket_options: typing.Optional[_TYPE_SOCKET_OPTIONS] = ...,
            proxy: typing.Optional[Url] = None,
            proxy_config: typing.Optional[ProxyConfig] = None,
            cert_reqs: typing.Optional[typing.Union[int, str]] = None,
            assert_hostname: typing.Union[None, str, "Literal[False]"] = None,
            assert_fingerprint: typing.Optional[str] = None,
            server_hostname: typing.Optional[str] = None,
            ssl_context: typing.Optional["ssl.SSLContext"] = None,
            ca_certs: typing.Optional[str] = None,
            ca_cert_dir: typing.Optional[str] = None,
            ca_cert_data: typing.Union[None, str, bytes] = None,
            ssl_minimum_version: typing.Optional[int] = None,
            ssl_maximum_version: typing.Optional[int] = None,
            ssl_version: typing.Optional[typing.Union[int, str]] = None,  # Deprecated
            cert_file: typing.Optional[str] = None,
            key_file: typing.Optional[str] = None,
            key_password: typing.Optional[str] = None,
        ) -> None:
            ...

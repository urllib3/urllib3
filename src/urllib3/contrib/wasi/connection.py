from __future__ import annotations

import os
import typing
from http.client import ResponseNotReady

from urllib3.util.request import body_to_chunks
from urllib3.util.util import to_str

from ..._base_connection import _TYPE_BODY
from ...connection import (
    HTTPConnection,
    ProxyConfig,
    _get_default_user_agent,
    port_by_scheme,
)
from ...response import BaseHTTPResponse
from ...util.connection import _TYPE_SOCKET_OPTIONS
from ...util.timeout import _DEFAULT_TIMEOUT, _TYPE_TIMEOUT
from ...util.url import Url
from . import errors, wasi
from .request import WasiRequest
from .response import WasiHttpResponseWrapper, WasiResponse

if typing.TYPE_CHECKING:
    from ..._base_connection import BaseHTTPConnection, BaseHTTPSConnection


class WasiHTTPConnection:
    default_port: typing.ClassVar[int] = port_by_scheme["http"]
    default_socket_options: typing.ClassVar[_TYPE_SOCKET_OPTIONS]

    timeout: None | (float)

    host: str
    port: int
    blocksize: int
    source_address: tuple[str, int] | None
    socket_options: _TYPE_SOCKET_OPTIONS | None

    proxy: Url | None
    proxy_config: ProxyConfig | None

    is_verified: bool = False
    proxy_is_verified: bool | None = None

    _response: WasiResponse | None

    def __init__(
        self,
        host: str,
        port: int | None = None,
        *,
        timeout: _TYPE_TIMEOUT = _DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        blocksize: int = 4096,
        socket_options: _TYPE_SOCKET_OPTIONS | None = None,
        proxy: Url | None = None,
        proxy_config: ProxyConfig | None = None,
    ) -> None:
        (self.host, self.port) = self._get_hostport(host, port)
        self.timeout = timeout if isinstance(timeout, float) else None
        self.scheme = "http"
        self._closed = True
        self._response = None
        self.proxy = None
        self.proxy_config = None
        self.blocksize = max(blocksize, 4096)  # wasi-http limits blocksize to 4096
        self.source_address = None
        self.socket_options = None
        self.is_verified = False

    def set_tunnel(
        self,
        host: str,
        port: int | None = 0,
        headers: typing.Mapping[str, str] | None = None,
        scheme: str = "http",
    ) -> None:
        pass

    def connect(self) -> None:
        pass

    def request(
        self,
        method: str,
        url: str,
        body: _TYPE_BODY | None = None,
        headers: typing.Mapping[str, str] | None = None,
        *,
        chunked: bool = False,
        preload_content: bool = True,
        decode_content: bool = True,
        enforce_content_length: bool = True,
    ) -> None:
        if headers is None:
            headers = {}
        header_keys = frozenset(to_str(k.lower()) for k in headers)

        chunks_and_cl = body_to_chunks(body, method=method, blocksize=self.blocksize)
        chunks = chunks_and_cl.chunks
        content_length = chunks_and_cl.content_length

        request = WasiRequest(
            scheme=self.scheme,
            host=self.host,
            port=self.port,
            method=method,
            url=url,
            timeout=self.timeout,
            body=chunks,
            decode_content=decode_content,
            preload_content=preload_content,
        )

        if content_length is not None:
            request.set_header("Content-Length", str(content_length))
        if "user-agent" not in header_keys:
            request.set_header("User-Agent", _get_default_user_agent())
        for header, value in headers.items():
            request.set_header(header, value)

        self._response = wasi.send_request(request)

    def getresponse(self) -> BaseHTTPResponse:
        if self._response is not None:
            return WasiHttpResponseWrapper(
                internal_response=self._response,
                connection=self,
            )
        else:
            raise ResponseNotReady()

    def close(self) -> None:
        self._closed = True
        self._response = None

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def is_connected(self) -> bool:
        return True

    @property
    def has_connected_to_proxy(self) -> bool:
        return False

    def _get_hostport(self, host: str, port: int | None) -> tuple[str, int]:
        if port is None:
            i = host.rfind(":")
            j = host.rfind("]")  # ipv6 addresses have [...]
            if i > j:
                try:
                    port = int(host[i + 1 :])
                except ValueError:
                    if host[i + 1 :] == "":  # http://foo.com:/ == http://foo.com/
                        port = self.default_port
                    else:
                        raise errors.InvalidURL("nonnumeric port: '%s'" % host[i + 1 :])
                host = host[:i]
            else:
                port = self.default_port
        if host and host[0] == "[" and host[-1] == "]":
            host = host[1:-1]

        return (host, port)


class WasiHTTPSConnection(WasiHTTPConnection):
    default_port: typing.ClassVar[int] = port_by_scheme["https"]
    # all this is basically ignored, as host handles https
    cert_reqs: int | str | None = None
    ca_certs: str | None = None
    ca_cert_dir: str | None = None
    ca_cert_data: None | str | bytes = None
    cert_file: str | None
    key_file: str | None
    key_password: str | None
    ssl_context: typing.Any | None
    ssl_version: int | str | None = None
    ssl_minimum_version: int | None = None
    ssl_maximum_version: int | None = None
    assert_hostname: None | str | typing.Literal[False]
    assert_fingerprint: str | None = None

    def __init__(
        self,
        host: str,
        port: int | None = None,
        *,
        timeout: _TYPE_TIMEOUT = _DEFAULT_TIMEOUT,
        source_address: tuple[str, int] | None = None,
        blocksize: int = 16384,
        socket_options: (
            None | _TYPE_SOCKET_OPTIONS
        ) = HTTPConnection.default_socket_options,
        proxy: Url | None = None,
        proxy_config: ProxyConfig | None = None,
        cert_reqs: int | str | None = None,
        assert_hostname: None | str | typing.Literal[False] = None,
        assert_fingerprint: str | None = None,
        server_hostname: str | None = None,
        ssl_context: typing.Any | None = None,
        ca_certs: str | None = None,
        ca_cert_dir: str | None = None,
        ca_cert_data: None | str | bytes = None,
        ssl_minimum_version: int | None = None,
        ssl_maximum_version: int | None = None,
        ssl_version: int | str | None = None,  # Deprecated
        cert_file: str | None = None,
        key_file: str | None = None,
        key_password: str | None = None,
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
        self.scheme = "https"

        self.key_file = key_file
        self.cert_file = cert_file
        self.key_password = key_password
        self.ssl_context = ssl_context
        self.server_hostname = server_hostname
        self.assert_hostname = assert_hostname
        self.assert_fingerprint = assert_fingerprint
        self.ssl_version = ssl_version
        self.ssl_minimum_version = ssl_minimum_version
        self.ssl_maximum_version = ssl_maximum_version
        self.ca_certs = ca_certs and os.path.expanduser(ca_certs)
        self.ca_cert_dir = ca_cert_dir and os.path.expanduser(ca_cert_dir)
        self.ca_cert_data = ca_cert_data

        self.cert_reqs = None

        # The host will automatically verify all requests.
        # We have no control over that setting.
        self.is_verified = True

    def set_cert(
        self,
        key_file: str | None = None,
        cert_file: str | None = None,
        cert_reqs: int | str | None = None,
        key_password: str | None = None,
        ca_certs: str | None = None,
        assert_hostname: None | str | typing.Literal[False] = None,
        assert_fingerprint: str | None = None,
        ca_cert_dir: str | None = None,
        ca_cert_data: None | str | bytes = None,
    ) -> None:
        pass


# verify that this class implements BaseHTTP(s) connection correctly
if typing.TYPE_CHECKING:
    _supports_http_protocol: BaseHTTPConnection = WasiHTTPConnection("", 0)
    _supports_https_protocol: BaseHTTPSConnection = WasiHTTPSConnection("", 0)

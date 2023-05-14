from __future__ import annotations

import typing
from http.client import HTTPConnection

from ..util import connection
from ._base import BaseBackend, HttpVersion, QuicPreemptiveCacheType


class _PatchedHTTPConnection(HTTPConnection):
    """Internal use only. Use to bypass limits from Python inheritance mechanism."""

    def __init__(
        self,
        host: str,
        port: int | None = None,
        timeout: int = -1,
        source_address: tuple[str, int] | None = None,
        blocksize: int = 8192,
        *,
        socket_options: None
        | (connection._TYPE_SOCKET_OPTIONS) = BaseBackend.default_socket_options,
        disabled_svn: set[HttpVersion] | None = None,
        preemptive_quic_cache: QuicPreemptiveCacheType | None = None,
    ):
        super().__init__(
            host=host,
            port=port,
            timeout=timeout,
            source_address=source_address,
            blocksize=blocksize,
        )

        self.socket_kind = BaseBackend.default_socket_kind
        self.socket_options = socket_options

        self._tunnel_host: str | None = None
        self._tunnel_port: int | None = None
        self._tunnel_scheme: str | None = None
        self._tunnel_headers: typing.Mapping[str, str] = dict()

        # has no effect for httplib.
        self._disabled_svn = disabled_svn or set()
        self._preemptive_quic_cache = preemptive_quic_cache


class LegacyBackend(_PatchedHTTPConnection, BaseBackend):  # type: ignore[misc]
    """httplib (http.client) legacy backend. will remain the default until a future version."""

    supported_svn = [HttpVersion.h11]

    def _upgrade(self) -> None:
        raise NotImplementedError

    def _new_conn(self) -> None:
        ...

    def _post_conn(self) -> None:
        ...

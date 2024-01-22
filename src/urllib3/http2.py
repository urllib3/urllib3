from __future__ import annotations

import contextlib
import threading
import typing

import h2.config  # type: ignore[import]
import h2.connection  # type: ignore[import]
import h2.events  # type: ignore[import]

import urllib3.connection
import urllib3.util.ssl_

from ._collections import HTTPHeaderDict
from .connection import HTTPSConnection
from .connectionpool import HTTPSConnectionPool

orig_HTTPSConnection = HTTPSConnection


class HTTP2Connection(HTTPSConnection):
    def __init__(
        self, host: str, port: int | None = None, **kwargs: typing.Any
    ) -> None:
        self._h2_lock = threading.RLock()
        self._h2_conn = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=True)
        )
        self._h2_stream: int | None = None
        self._h2_headers: list[tuple[bytes, bytes]] = []

        if "proxy" in kwargs or "proxy_config" in kwargs:  # Defensive:
            raise NotImplementedError("Proxies aren't supported with HTTP/2")

        super().__init__(host, port, **kwargs)

    @contextlib.contextmanager
    def _lock_h2_conn(self) -> typing.Generator[h2.connection.H2Connection, None, None]:
        with self._h2_lock:
            yield self._h2_conn

    def connect(self) -> None:
        super().connect()

        with self._lock_h2_conn() as h2_conn:
            h2_conn.initiate_connection()
            self.sock.sendall(h2_conn.data_to_send())

    def putrequest(
        self,
        method: str,
        url: str,
        skip_host: bool = False,
        skip_accept_encoding: bool = False,
    ) -> None:
        with self._lock_h2_conn() as h2_conn:
            self._h2_stream = h2_conn.get_next_available_stream_id()

            if ":" in self.host:
                authority = f"[{self.host}]:{self.port or 443}"
            else:
                authority = f"{self.host}:{self.port or 443}"

            self._h2_headers.extend(
                (
                    (b":scheme", b"https"),
                    (b":method", method.encode()),
                    (b":authority", authority.encode()),
                    (b":path", url.encode()),
                )
            )

    def putheader(self, header: str, *values: str) -> None:
        for value in values:
            self._h2_headers.append(
                (header.encode("utf-8").lower(), value.encode("utf-8"))
            )

    def endheaders(self) -> None:  # type: ignore[override]
        with self._lock_h2_conn() as h2_conn:
            h2_conn.send_headers(
                stream_id=self._h2_stream,
                headers=self._h2_headers,
                end_stream=True,
            )
            if data_to_send := h2_conn.data_to_send():
                self.sock.sendall(data_to_send)

    def send(self, data: bytes) -> None:  # type: ignore[override]  # Defensive:
        if not data:
            return
        raise NotImplementedError("Sending data isn't supported yet")

    def getresponse(  # type: ignore[override]
        self,
    ) -> HTTP2Response:
        status = None
        data = bytearray()
        with self._lock_h2_conn() as h2_conn:
            end_stream = False
            while not end_stream:
                # TODO: Arbitrary read value.
                if received_data := self.sock.recv(65535):
                    events = h2_conn.receive_data(received_data)
                    for event in events:
                        if isinstance(
                            event, h2.events.InformationalResponseReceived
                        ):  # Defensive:
                            continue  # TODO: Does the stdlib do anything with these responses?

                        elif isinstance(event, h2.events.ResponseReceived):
                            headers = HTTPHeaderDict()
                            for header, value in event.headers:
                                if header == b":status":
                                    status = int(value.decode())
                                else:
                                    headers.add(
                                        header.decode("ascii"), value.decode("ascii")
                                    )

                        elif isinstance(event, h2.events.DataReceived):
                            data += event.data
                            h2_conn.acknowledge_received_data(
                                event.flow_controlled_length, event.stream_id
                            )

                        elif isinstance(event, h2.events.StreamEnded):
                            end_stream = True

                if data_to_send := h2_conn.data_to_send():
                    self.sock.sendall(data_to_send)

        # We always close to not have to handle connection management.
        self.close()

        assert status is not None
        return HTTP2Response(status=status, headers=headers, data=bytes(data))

    def close(self) -> None:
        with self._lock_h2_conn() as h2_conn:
            try:
                self._h2_conn.close_connection()
                if data := h2_conn.data_to_send():
                    self.sock.sendall(data)
            except Exception:
                pass

        # Reset all our HTTP/2 connection state.
        self._h2_conn = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=True)
        )
        self._h2_stream = None
        self._h2_headers = []

        super().close()


class HTTP2Response:
    # TODO: This is a woefully incomplete response object, but works for non-streaming.
    def __init__(self, status: int, headers: HTTPHeaderDict, data: bytes) -> None:
        self.status = status
        self.headers = headers
        self.data = data
        self.length_remaining = 0

    def get_redirect_location(self) -> None:
        return None


def inject_into_urllib3() -> None:
    HTTPSConnectionPool.ConnectionCls = HTTP2Connection  # type: ignore[assignment]
    urllib3.connection.HTTPSConnection = HTTP2Connection  # type: ignore[misc]

    # TODO: Offer 'http/1.1' as well, but for testing purposes this is handy.
    urllib3.util.ssl_.ALPN_PROTOCOLS = ["h2"]


def extract_from_urllib3() -> None:
    HTTPSConnectionPool.ConnectionCls = orig_HTTPSConnection
    urllib3.connection.HTTPSConnection = orig_HTTPSConnection  # type: ignore[misc]

    urllib3.util.ssl_.ALPN_PROTOCOLS = ["http/1.1"]

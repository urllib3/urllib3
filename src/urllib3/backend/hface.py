from __future__ import annotations

import typing

_BACKEND_AVAILABLE: bool

try:
    # purposely disable this backend if python not built with ssl
    from ssl import CERT_NONE, SSLContext, SSLSocket

    from urllib3_ext_hface import (
        HTTP1Protocol,
        HTTP2Protocol,
        HTTP3Protocol,
        HTTPOverQUICProtocol,
        HTTPOverTCPProtocol,
        HTTPProtocolFactory,
        QuicTLSConfig,
    )
    from urllib3_ext_hface.events import (
        ConnectionTerminated,
        DataReceived,
        Event,
        HandshakeCompleted,
        HeadersReceived,
    )

    _BACKEND_AVAILABLE = True
except ImportError:
    _BACKEND_AVAILABLE = False


# Don't bother interpreting HfaceBackend if it is not available.
if not _BACKEND_AVAILABLE:
    HfaceBackend = NotImplemented
else:
    import sys
    from http.client import ResponseNotReady, responses
    from socket import SOCK_DGRAM, SOCK_STREAM

    from .._collections import HTTPHeaderDict
    from ..exceptions import InvalidHeader, ProtocolError, SSLError
    from ..util import connection, parse_alt_svc
    from ..util.ssltransport import SSLTransport
    from ._base import (
        BaseBackend,
        HttpVersion,
        ProxyHttpLibResponse,
        QuicPreemptiveCacheType,
    )

    _HAS_SYS_AUDIT = hasattr(sys, "audit")

    class HfaceBackend(BaseBackend):  # type: ignore[no-redef]
        supported_svn = [HttpVersion.h11, HttpVersion.h2, HttpVersion.h3]

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
                host,
                port,
                timeout,
                source_address,
                blocksize,
                socket_options=socket_options,
                disabled_svn=disabled_svn,
                preemptive_quic_cache=preemptive_quic_cache,
            )

            self._protocol: HTTPOverQUICProtocol | HTTPOverTCPProtocol | None = None
            self._svn = None

            self._stream_id: int | None = None

            # prep buffer, internal usage only.
            # not suited for HTTPHeaderDict
            self.__headers: list[tuple[bytes, bytes]] = []
            self.__expected_body_length: int | None = None
            self.__remaining_body_length: int | None = None

            # h3 specifics
            self.__custom_tls_settings: QuicTLSConfig | None = None
            self.__alt_authority: tuple[str, int] | None = None
            self.__session_ticket: typing.Any | None = None
            # we may switch from STREAM (TCP) to DGRAM (UDP)
            # options may not work as intended, we keep tcp options in there
            self.__backup_socket_options: None | (
                connection._TYPE_SOCKET_OPTIONS
            ) = None

        def _new_conn(self) -> None:
            # handle if set up, quic cache capability. thus avoiding first TCP request prior to upgrade.
            if (
                self._svn is None
                and HttpVersion.h3 not in self._disabled_svn
                and self.scheme == "https"
            ):
                if (
                    self._preemptive_quic_cache
                    and (self.host, self.port) in self._preemptive_quic_cache
                ):
                    self.__alt_authority = self._preemptive_quic_cache[
                        (self.host, self.port or 443)
                    ]
                    if self.__alt_authority:
                        self._svn = HttpVersion.h3
                        # we ignore alt-host as we do not trust cache security
                        self.port = self.__alt_authority[1]

            if self._svn == HttpVersion.h3:
                if self.__backup_socket_options is None:
                    self.__backup_socket_options = self.socket_options

                # ensure no opt are set for QUIC/UDP socket
                self.socket_options = []
                self.socket_kind = SOCK_DGRAM

                # undo local memory on whether conn supposedly support quic/h3
                # if conn target another host.
                if self._response and self._response.authority != self.host:
                    self._svn = None
                    self._new_conn()  # restore socket defaults
            else:
                if self.__backup_socket_options is not None:
                    self.socket_options = self.__backup_socket_options
                    self.__backup_socket_options = None
                self.socket_kind = SOCK_STREAM

        def _upgrade(self) -> None:
            assert (
                self._response is not None
            ), "attempt to call _upgrade() prior to successful getresponse()"

            if self._svn == HttpVersion.h3:
                return
            if HttpVersion.h3 in self._disabled_svn:
                return

            self.__alt_authority = self.__h3_probe()

            if self.__alt_authority:
                if self._preemptive_quic_cache is not None:
                    self._preemptive_quic_cache[
                        (self.host, self.port or 443)
                    ] = self.__alt_authority
                self._svn = HttpVersion.h3
                # We purposely ignore setting the Hostname. Avoid MITM attack from local cache attack.
                self.port = self.__alt_authority[1]
                self.close()

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
            """Meant to support TLS over QUIC meanwhile cpython does not ship with its native implementation."""
            if self._svn != HttpVersion.h3:
                raise NotImplementedError

            self.__custom_tls_settings = QuicTLSConfig(
                insecure=ssl_context.verify_mode == CERT_NONE if ssl_context else False,
                cafile=ca_certs,
                capath=ca_cert_dir,
                cadata=ca_cert_data.encode()
                if isinstance(ca_cert_data, str)
                else ca_cert_data,
                session_ticket=self.__session_ticket,  # going to be set after first successful quic handshake
                certfile=cert_file,
                keyfile=key_file,
                keypassword=key_password,
            )

            self.is_verified = not self.__custom_tls_settings.insecure

        def __h3_probe(self) -> tuple[str, int] | None:
            """Determine if remote is capable of operating through the http/3 protocol over QUIC."""
            # need at least first request being made
            assert self._svn is not None
            assert self._response is not None

            # do not upgrade if not coming from TLS already.
            # we exclude SSLTransport, HTTP/3 is not supported in that condition anyway.
            if not isinstance(self.sock, SSLSocket):
                return None

            for alt_svc in self._response.msg.getlist("alt-svc"):
                for protocol, alt_authority in parse_alt_svc(alt_svc):
                    # Looking for final specification of HTTP/3 over QUIC.
                    if protocol != "h3":
                        continue

                    server, port = alt_authority.split(":")

                    # Security: We don't accept Alt-Svc with switching Host
                    # It's up to consideration, can be a security risk.
                    if server and server != self.host:
                        continue

                    return server, int(port)

            return None

        def _post_conn(self) -> None:
            if self._tunnel_host is None:
                assert (
                    self._protocol is None
                ), "_post_conn() must be called when socket is closed or unset"
            assert (
                self.sock is not None
            ), "probable attempt to call _post_conn() prior to successful _new_conn()"

            # first request was not made yet
            if self._svn is None:
                if isinstance(self.sock, (SSLSocket, SSLTransport)):
                    alpn: str | None = (
                        self.sock.selected_alpn_protocol()
                        if isinstance(self.sock, SSLSocket)
                        else self.sock.sslobj.selected_alpn_protocol()  # type: ignore[attr-defined]
                    )

                    if alpn is not None:
                        if alpn == "h2":
                            self._protocol = HTTPProtocolFactory.new(HTTP2Protocol)  # type: ignore[type-abstract]
                            self._svn = HttpVersion.h2
                        elif alpn != "http/1.1":
                            raise ProtocolError(  # Defensive: This should be unreachable as ALPN is explicit higher in the stack.
                                f"Unsupported ALPN '{alpn}' during handshake"
                            )
            else:
                if self._svn == HttpVersion.h2:
                    self._protocol = HTTPProtocolFactory.new(HTTP2Protocol)  # type: ignore[type-abstract]
                elif self._svn == HttpVersion.h3:
                    assert self.__custom_tls_settings is not None
                    assert self.__alt_authority is not None

                    server, port = self.__alt_authority

                    self._protocol = HTTPProtocolFactory.new(
                        HTTP3Protocol,  # type: ignore[type-abstract]
                        remote_address=(self.host, int(port)),
                        server_name=self.host,
                        tls_config=self.__custom_tls_settings,
                    )

            # fallback to http/1.1
            if self._protocol is None or self._svn == HttpVersion.h11:
                self._protocol = HTTPProtocolFactory.new(HTTP1Protocol)  # type: ignore[type-abstract]
                self._svn = HttpVersion.h11

                return

            # it may be required to send some initial data, aka. magic header (PRI * HTTP/2..)
            self.__exchange_until(
                HandshakeCompleted,
                receive_first=False,
            )

        def set_tunnel(
            self,
            host: str,
            port: int | None = None,
            headers: typing.Mapping[str, str] | None = None,
            scheme: str = "http",
        ) -> None:
            if self.sock:
                # overly protective, checks are made higher, this is unreachable.
                raise RuntimeError(  # Defensive: mimic HttpConnection from http.client
                    "Can't set up tunnel for established connection"
                )

            # We either support tunneling or http/3. Need complex developments.
            if HttpVersion.h3 not in self._disabled_svn:
                self._disabled_svn.add(HttpVersion.h3)

            self._tunnel_host = host
            self._tunnel_port = port

            if headers:
                self._tunnel_headers = headers
            else:
                self._tunnel_headers = {}

        def _tunnel(self) -> None:
            assert self._protocol is not None
            assert self.sock is not None
            assert self._tunnel_host is not None
            assert self._tunnel_port is not None

            if self._svn != HttpVersion.h11:
                raise NotImplementedError(
                    """Unable to establish a tunnel using other than HTTP/1.1."""
                )

            self._stream_id = self._protocol.get_available_stream_id()

            req_context = [
                (
                    b":authority",
                    f"{self._tunnel_host}:{self._tunnel_port}".encode("ascii"),
                ),
                (b":method", b"CONNECT"),
            ]

            for header, value in self._tunnel_headers.items():
                req_context.append(
                    (header.lower().encode(), value.encode("iso-8859-1"))
                )

            self._protocol.submit_headers(
                self._stream_id,
                req_context,
                True,
            )

            events = self.__exchange_until(
                HeadersReceived,
                receive_first=False,
                event_type_collectable=(HeadersReceived,),
                # special case for CONNECT
                respect_end_stream_signal=False,
            )

            status: int | None = None

            for event in events:
                if isinstance(event, HeadersReceived):
                    for raw_header, raw_value in event.headers:
                        if raw_header == b":status":
                            status = int(raw_value.decode())
                            break

            tunnel_accepted: bool = status is not None and (200 <= status < 300)

            if not tunnel_accepted:
                self.close()
                message: str = responses[status] if status in responses else "UNKNOWN"
                raise OSError(f"Tunnel connection failed: {status} {message}")

            # We will re-initialize those afterward
            # to be in phase with Us --> NotIntermediary
            self._svn = None
            self._protocol = None
            self._protocol_factory = None

        def __exchange_until(
            self,
            event_type: type[Event] | tuple[type[Event], ...],
            *,
            receive_first: bool = False,
            event_type_collectable: type[Event] | tuple[type[Event], ...] | None = None,
            respect_end_stream_signal: bool = True,
            maximal_data_in_read: int | None = None,
            data_in_len_from: typing.Callable[[Event], int] | None = None,
        ) -> list[Event]:
            """This method simplify socket exchange in/out based on what the protocol state machine orders.
            Can be used for the initial handshake for instance."""
            assert self._protocol is not None
            assert self.sock is not None
            assert (maximal_data_in_read is not None and maximal_data_in_read >= 0) or (
                maximal_data_in_read is None
            )

            data_out: bytes
            data_in: bytes

            data_in_len: int = 0

            events: list[Event] = []

            if maximal_data_in_read == 0:
                # The '0' case amt is handled higher in the stack.
                return events  # Defensive: This should be unreachable in the current project state.

            while True:
                if not self._protocol.has_pending_event():
                    if receive_first is False:
                        data_out = self._protocol.bytes_to_send()

                        if data_out:
                            self.sock.sendall(data_out)
                        else:  # nothing to send out...? immediately exit.
                            return events  # Defensive: This should be unreachable in the current project state.

                    data_in = self.sock.recv(maximal_data_in_read or self.blocksize)

                    if not data_in:
                        # in some cases (merely http/1 legacy)
                        # server can signify "end-of-transmission" by simply closing the socket.
                        # pretty much dirty.

                        # must have at least one event received, otherwise we can't declare a proper eof.
                        if (events or self._response is not None) and hasattr(
                            self._protocol, "eof_received"
                        ):
                            try:
                                self._protocol.eof_received()
                            except self._protocol.exceptions() as e:  # Defensive:
                                # overly protective, we hide exception that are behind urllib3.
                                # should not happen, but one truly never known.
                                raise ProtocolError(e) from e  # Defensive:
                        else:
                            raise ProtocolError(
                                "server unexpectedly closed the connection in-flight (prior-to-response)"
                            )
                    else:
                        if data_in_len_from is None:
                            data_in_len += len(data_in)

                        try:
                            self._protocol.bytes_received(data_in)
                        except self._protocol.exceptions() as e:
                            raise ProtocolError(e) from e  # Defensive:

                    if receive_first is True:
                        data_out = self._protocol.bytes_to_send()

                        if data_out:
                            self.sock.sendall(data_out)

                for event in iter(self._protocol.next_event, None):  # type: Event
                    if isinstance(event, ConnectionTerminated):
                        if (
                            event.error_code == 400
                            and event.message
                            and "header" in event.message
                        ):
                            raise InvalidHeader(event.message)
                        # QUIC operate TLS verification outside native capabilities
                        # We have to forward the error so that users aren't caught off guard when the connection
                        # unexpectedly close.
                        elif event.error_code == 298 and self._svn == HttpVersion.h3:
                            raise SSLError(
                                "TLS over QUIC did not succeed (Error 298). Chain certificate verification failed."
                            )

                        raise ProtocolError(event.message)

                    if data_in_len_from:
                        data_in_len += data_in_len_from(event)

                    if not event_type_collectable:
                        events.append(event)
                    else:
                        if isinstance(event, event_type_collectable):
                            events.append(event)

                    if (event_type and isinstance(event, event_type)) or (
                        maximal_data_in_read and data_in_len >= maximal_data_in_read
                    ):
                        # if event type match, make sure it is the latest one
                        # simply put, end_stream should be True.
                        if respect_end_stream_signal and hasattr(event, "end_stream"):
                            if event.end_stream is True:
                                return events
                            continue

                        return events

        def putrequest(
            self,
            method: str,
            url: str,
            skip_host: bool = False,
            skip_accept_encoding: bool = False,
        ) -> None:
            """Internally fhace translate this into what putrequest does. e.g. initial trame."""
            self.__headers = []
            self.__expected_body_length = None
            self.__remaining_body_length = None

            if self._tunnel_host is not None:
                host, port = self._tunnel_host, self._tunnel_port
            else:
                host, port = self.host, self.port

            authority: bytes = host.encode("idna")

            self.__headers = [
                (b":method", method.encode("ascii")),
                (
                    b":scheme",
                    self.scheme.encode("ascii"),
                ),
                (b":path", url.encode("ascii")),
            ]

            if not skip_host:
                self.__headers.append(
                    (
                        b":authority",
                        authority
                        if port == self.default_port  # type: ignore[attr-defined]
                        else authority + f":{port}".encode(),
                    ),
                )

            if not skip_accept_encoding:
                self.putheader("Accept-Encoding", "identity")

        def putheader(self, header: str, *values: str) -> None:
            # note: requests allow passing headers as bytes (seen in requests/tests)
            # warn: always lowercase header names, quic transport crash if not lowercase.
            header = header.lower()

            encoded_header = (
                header.encode("ascii") if isinstance(header, str) else header
            )

            for value in values:
                self.__headers.append(
                    (
                        encoded_header,
                        value.encode("iso-8859-1") if isinstance(value, str) else value,
                    )
                )

        def endheaders(
            self, message_body: bytes | None = None, *, encode_chunked: bool = False
        ) -> None:
            # only the case when it is plain http
            if self.sock is None:
                self.connect()  # type: ignore[attr-defined]

            assert self.sock is not None
            assert self._protocol is not None

            # only h2 and h3 support streams, it is faked/simulated for h1.
            self._stream_id = self._protocol.get_available_stream_id()

            # unless anything hint the opposite, the request head frame is the end stream
            should_end_stream: bool = True
            # only h11 support chunked transfer encoding, we internally translate
            # it to the right method for h2 and h3.
            support_te_chunked: bool = self._svn == HttpVersion.h11

            # determine if stream should end there (absent body case)
            for raw_header, raw_value in self.__headers:
                header: str = raw_header.decode("ascii").lower().replace("_", "-")
                value: str = raw_value.decode("iso-8859-1")
                if header.startswith(":"):
                    continue
                if header == "content-length":
                    if value.isdigit():
                        self.__expected_body_length = int(value)
                    should_end_stream = not (
                        self.__expected_body_length is not None and int(value) > 0
                    )
                    break
                if header == "transfer-encoding" and value.lower() == "chunked":
                    should_end_stream = False
                    break

            # handle cases where 'Host' header is set manually
            if any(k == b":authority" for k, v in self.__headers) is False:
                for raw_header, raw_value in self.__headers:
                    header = raw_header.decode("ascii").lower().replace("_", "-")

                    if header == "host":
                        self.__headers.append((b":authority", raw_value))
                        break
            if any(k == b":authority" for k, v in self.__headers) is False:
                raise ProtocolError(
                    (
                        "HfaceBackend do not support emitting HTTP requests without the `Host` header",
                        "It was only permitted in HTTP/1.0 and prior. This implementation ship with HTTP/1.1+.",
                    )
                )

            if not support_te_chunked:
                # We MUST never use that header in h2 and h3 over quic.
                # It may(should) break the connection.
                intent_te_chunked: bool = False
                try:
                    self.__headers.remove((b"transfer-encoding", b"chunked"))
                    intent_te_chunked = True
                except ValueError:
                    pass

                # some quic/h3 implementation like quic-go skip reading the body
                # if this indicator isn't present, equivalent to te: chunked but looking for stream FIN marker.
                # officially, it should not be there. kept for compatibility.
                if (
                    intent_te_chunked
                    and self._svn == HttpVersion.h3
                    and self.__expected_body_length is None
                ):
                    self.__headers.append((b"content-length", b"-1"))

            try:
                self._protocol.submit_headers(
                    self._stream_id,
                    self.__headers,
                    end_stream=should_end_stream,
                )
            except self._protocol.exceptions() as e:  # Defensive:
                # overly protective, designed to avoid exception leak bellow urllib3.
                raise ProtocolError(e) from e  # Defensive:

            self.sock.sendall(self._protocol.bytes_to_send())

        def __read_st(self, __amt: int | None = None) -> tuple[bytes, bool]:
            """Allows us to defer the body loading after constructing the response object."""
            eot = False

            events: list[DataReceived] = self.__exchange_until(  # type: ignore[assignment]
                DataReceived,
                receive_first=True,
                # we ignore Trailers even if provided in response.
                event_type_collectable=(DataReceived, HeadersReceived),
                maximal_data_in_read=__amt,
                data_in_len_from=lambda x: len(x.data)
                if isinstance(x, DataReceived)
                else 0,
            )

            if events and events[-1].end_stream:
                eot = True
                # probe for h3/quic if available, and remember it.
                self._upgrade()

                # remote can refuse future inquiries, so no need to go further with this conn.
                if self._protocol and self._protocol.has_expired():
                    self.close()

            return (
                b"".join(
                    e.data if isinstance(e, DataReceived) else b"" for e in events
                ),
                eot,
            )

        def getresponse(self) -> ProxyHttpLibResponse:
            if self.sock is None or self._protocol is None or self._svn is None:
                raise ResponseNotReady()  # Defensive: Comply with http.client, actually tested but not reported?

            headers = HTTPHeaderDict()
            status: int | None = None

            events: list[HeadersReceived] = self.__exchange_until(  # type: ignore[assignment]
                HeadersReceived,
                receive_first=True,
                event_type_collectable=(HeadersReceived,),
                respect_end_stream_signal=False,
            )

            for event in events:
                if isinstance(event, HeadersReceived):
                    for raw_header, raw_value in event.headers:
                        header: str = raw_header.decode("ascii")
                        value: str = raw_value.decode("iso-8859-1")

                        # special headers that represent (usually) the HTTP response status, version and reason.
                        if header.startswith(":"):
                            if header == ":status" and value.isdigit():
                                status = int(value)
                                continue
                            # this should be unreachable.
                            # it is designed to detect eventual changes lower in the stack.
                            raise ProtocolError(
                                f"Unhandled special header '{header}'"
                            )  # Defensive:

                        headers.add(header, value)

            # this should be unreachable
            if status is None:
                raise ProtocolError(  # Defensive: This is unreachable, all three implementations crash before.
                    "Got an HTTP response without a status code. This is a violation."
                )

            eot = events[-1].end_stream is True

            response = ProxyHttpLibResponse(
                status,
                self._http_vsn,
                responses[status] if status in responses else "UNKNOWN",
                headers,
                self.__read_st if not eot else None,
                method=dict(self.__headers)[b":method"].decode("ascii"),
                authority=self.host,
                port=self.port,
            )

            # keep last response
            self._response = response

            # save the quic ticket for session resumption
            if self._svn == HttpVersion.h3 and hasattr(
                self._protocol, "session_ticket"
            ):
                self.__session_ticket = self._protocol.session_ticket

            if eot:
                self._upgrade()

                # remote can refuse future inquiries, so no need to go further with this conn.
                if self._protocol and self._protocol.has_expired():
                    self.close()

            return response

        def send(
            self,
            data: (bytes | typing.IO[typing.Any] | typing.Iterable[bytes] | str),
        ) -> None:
            """We might be receiving a chunk constructed downstream"""
            if self.sock is None or self._stream_id is None or self._protocol is None:
                # this is unreachable in normal condition as urllib3
                # is strict on his workflow.
                raise RuntimeError(  # Defensive:
                    "Trying to send data from a closed connection"
                )

            if (
                self.__remaining_body_length is None
                and self.__expected_body_length is not None
            ):
                self.__remaining_body_length = self.__expected_body_length

            def unpack_chunk(possible_chunk: bytes) -> bytes:
                """This hacky function is there because we won't alter the send() method signature.
                Therefor cannot know intention prior to this. b"%x\r\n%b\r\n" % (len(chunk), chunk)
                """
                if (
                    possible_chunk.endswith(b"\r\n")
                    and possible_chunk.startswith(b"--") is False
                ):
                    _: list[bytes] = possible_chunk.split(b"\r\n", maxsplit=1)
                    if len(_) != 2 or any(uc == b"" for uc in _):
                        return possible_chunk
                    return _[-1][:-2]
                return possible_chunk

            try:
                if isinstance(
                    data,
                    (
                        bytes,
                        bytearray,
                    ),
                ):
                    data_ = unpack_chunk(data)
                    is_chunked = len(data_) != len(data)

                    if self.__remaining_body_length:
                        self.__remaining_body_length -= len(data_)

                    self._protocol.submit_data(
                        self._stream_id,
                        data_,
                        end_stream=(is_chunked and data_ == b"")
                        or self.__remaining_body_length == 0,
                    )
                else:
                    # urllib3 is supposed to handle every case
                    # and pass down bytes only. This should be unreachable.
                    raise OSError(  # Defensive:
                        f"unhandled type '{type(data)}' in send method"
                    )

                if _HAS_SYS_AUDIT:
                    sys.audit("http.client.send", self, data)

                self.sock.sendall(self._protocol.bytes_to_send())
            except self._protocol.exceptions() as e:
                raise ProtocolError(  # Defensive: In the unlikely event that exception may leak from below
                    e
                ) from e

        def close(self) -> None:
            if self.sock:
                if self._protocol is not None:
                    try:
                        self._protocol.submit_close()
                    except self._protocol.exceptions() as e:  # Defensive:
                        # overly protective, made in case of possible exception leak.
                        raise ProtocolError(e) from e  # Defensive:

                    goodbye_trame: bytes = self._protocol.bytes_to_send()

                    if goodbye_trame:
                        self.sock.sendall(goodbye_trame)

                self.sock.close()

            self._protocol = None
            self._stream_id = None

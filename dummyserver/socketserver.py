#!/usr/bin/env python

"""
Dummy server used for unit testing.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import select
import socket
import ssl
import sys
import threading
import time
import typing
import warnings

import trustme
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from urllib3.exceptions import HTTPWarning
from urllib3.util import resolve_cert_reqs, resolve_ssl_version

if typing.TYPE_CHECKING:
    from typing_extensions import ParamSpec

    P = ParamSpec("P")

log = logging.getLogger(__name__)

CERTS_PATH = os.path.join(os.path.dirname(__file__), "certs")
DEFAULT_CERTS: dict[str, typing.Any] = {
    "certfile": os.path.join(CERTS_PATH, "server.crt"),
    "keyfile": os.path.join(CERTS_PATH, "server.key"),
    "cert_reqs": ssl.CERT_OPTIONAL,
    "ca_certs": os.path.join(CERTS_PATH, "cacert.pem"),
    "alpn_protocols": ["h2", "http/1.1"],
}
DEFAULT_CA = os.path.join(CERTS_PATH, "cacert.pem")
DEFAULT_CA_KEY = os.path.join(CERTS_PATH, "cacert.key")


def _resolves_to_ipv6(host: str) -> bool:
    """Returns True if the system resolves host to an IPv6 address by default."""
    resolves_to_ipv6 = False
    try:
        for res in socket.getaddrinfo(host, None, socket.AF_UNSPEC):
            af, _, _, _, _ = res
            if af == socket.AF_INET6:
                resolves_to_ipv6 = True
    except socket.gaierror:
        pass

    return resolves_to_ipv6


def _has_ipv6(host: str) -> bool:
    """Returns True if the system can bind an IPv6 address."""
    sock = None
    has_ipv6 = False

    if socket.has_ipv6:
        # has_ipv6 returns true if cPython was compiled with IPv6 support.
        # It does not tell us if the system has IPv6 support enabled. To
        # determine that we must bind to an IPv6 address.
        # https://github.com/urllib3/urllib3/pull/611
        # https://bugs.python.org/issue658327
        try:
            sock = socket.socket(socket.AF_INET6)
            sock.bind((host, 0))
            has_ipv6 = _resolves_to_ipv6("localhost")
        except Exception:
            pass

    if sock:
        sock.close()
    return has_ipv6


# Some systems may have IPv6 support but DNS may not be configured
# properly. We can not count that localhost will resolve to ::1 on all
# systems. See https://github.com/urllib3/urllib3/pull/611 and
# https://bugs.python.org/issue18792
HAS_IPV6_AND_DNS = _has_ipv6("localhost")
HAS_IPV6 = _has_ipv6("::1")


# Different types of servers we have:


class NoIPv6Warning(HTTPWarning):
    "IPv6 is not available"


class _MultiSocketListener:
    """Presents multiple listening sockets behind a single accept() API."""

    def __init__(self, sockets: list[socket.socket]) -> None:
        self._sockets = sockets
        self._timeout: float | None = None
        self._closed = False

    def settimeout(self, value: float | None) -> None:
        if value is not None and value < 0:
            raise ValueError("Timeout value out of range")
        self._timeout = value

    def gettimeout(self) -> float | None:
        return self._timeout

    def getsockname(self) -> typing.Any:
        return self._sockets[0].getsockname()

    def accept(self) -> tuple[socket.socket, typing.Any]:
        if self._closed:
            raise OSError(errno.EBADF, "Bad file descriptor")
        deadline = None if self._timeout is None else time.monotonic() + self._timeout
        while True:
            remaining = (
                None if deadline is None else max(0.0, deadline - time.monotonic())
            )
            readable, _, _ = select.select(self._sockets, [], [], remaining)
            if not readable:
                raise TimeoutError("timed out")
            for sock in readable:
                sock.setblocking(False)
                try:
                    conn, addr = sock.accept()
                except BlockingIOError:
                    continue
                finally:
                    with contextlib.suppress(OSError):
                        sock.setblocking(True)
                conn.setblocking(True)
                return conn, addr
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("timed out")

    def close(self) -> None:
        self._closed = True
        for sock in self._sockets:
            sock.close()

    def __enter__(self) -> _MultiSocketListener:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class SocketServerThread(threading.Thread):
    """
    :param socket_handler: Callable which receives a socket argument for one
        request.
    :param ready_event: Event which gets set when the socket handler is
        ready to receive requests.
    """

    USE_IPV6 = HAS_IPV6_AND_DNS

    def __init__(
        self,
        socket_handler: typing.Callable[[socket.socket], None],
        host: str = "localhost",
        ready_event: threading.Event | None = None,
        quit_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self.daemon = True

        self.socket_handler = socket_handler
        self.host = host
        self.ready_event = ready_event
        self.quit_event = quit_event

    def _resolve_bind_targets(self) -> list[tuple[int, int, int, typing.Any]]:
        if not self.USE_IPV6:
            warnings.warn("No IPv6 support. Falling back to IPv4.", NoIPv6Warning)
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, (self.host, 0))]

        addrinfo = socket.getaddrinfo(
            self.host, 0, socket.AF_UNSPEC, socket.SOCK_STREAM, 0, socket.AI_PASSIVE
        )
        targets_by_family: dict[int, tuple[int, int, int, typing.Any]] = {}
        for af, socktype, proto, _, sockaddr in addrinfo:
            if af in (socket.AF_INET, socket.AF_INET6) and af not in targets_by_family:
                targets_by_family[af] = (af, socktype, proto, sockaddr)
        if self.host == "localhost":
            targets_by_family.setdefault(
                socket.AF_INET6, (socket.AF_INET6, socket.SOCK_STREAM, 0, ("::1", 0))
            )

        # Bind IPv4 first to select a free port, then bind IPv6 on the same port.
        targets = [
            targets_by_family[af]
            for af in (socket.AF_INET, socket.AF_INET6)
            if af in targets_by_family
        ]
        return targets or [(socket.AF_INET6, socket.SOCK_STREAM, 0, (self.host, 0))]

    def _create_bound_sockets(self) -> list[socket.socket]:
        targets = self._resolve_bind_targets()
        max_attempts = 10 if len(targets) > 1 else 1
        for attempt in range(max_attempts):
            sockets: list[socket.socket] = []
            port = 0
            try:
                for af, socktype, proto, sockaddr in targets:
                    sock = socket.socket(af, socktype, proto)
                    sockets.append(sock)
                    if sys.platform != "win32":
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    if af == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
                        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    bind_addr = (
                        sockaddr if port == 0 else (sockaddr[0], port, *sockaddr[2:])
                    )
                    sock.bind(bind_addr)
                    if port == 0:
                        port = sock.getsockname()[1]
                for sock in sockets:
                    # Once listen() returns, the server socket is ready
                    sock.listen(5)
                self.port = port
                return sockets
            except OSError as e:
                for sock in sockets:
                    sock.close()
                if attempt == max_attempts - 1 or e.errno not in (
                    errno.EADDRINUSE,
                    errno.EACCES,
                ):
                    raise
            except BaseException:
                for sock in sockets:
                    sock.close()
                raise

        raise OSError("failed to bind socket")

    def _start_server(self) -> None:
        sockets = self._create_bound_sockets()
        with contextlib.ExitStack() as stack:
            for sock in sockets:
                stack.enter_context(sock)

            if self.ready_event:
                self.ready_event.set()

            listener = (
                sockets[0]
                if len(sockets) == 1
                else typing.cast(socket.socket, _MultiSocketListener(sockets))
            )
            self.socket_handler(listener)

    def run(self) -> None:
        self._start_server()


def ssl_options_to_context(  # type: ignore[no-untyped-def]
    keyfile=None,
    certfile=None,
    server_side=None,
    cert_reqs=None,
    ssl_version: str | int | None = None,
    ca_certs=None,
    do_handshake_on_connect=None,
    suppress_ragged_eofs=None,
    ciphers=None,
    alpn_protocols=None,
) -> ssl.SSLContext:
    """Return an equivalent SSLContext based on ssl.wrap_socket args."""
    ssl_version = resolve_ssl_version(ssl_version)
    cert_none = resolve_cert_reqs("CERT_NONE")
    if cert_reqs is None:
        cert_reqs = cert_none
    else:
        cert_reqs = resolve_cert_reqs(cert_reqs)

    ctx = ssl.SSLContext(ssl_version)
    ctx.load_cert_chain(certfile, keyfile)
    ctx.verify_mode = cert_reqs
    if ctx.verify_mode != cert_none:
        ctx.load_verify_locations(cafile=ca_certs)
    if alpn_protocols:
        ctx.set_alpn_protocols(alpn_protocols)
    return ctx


def get_unreachable_address() -> tuple[str, int]:
    # reserved as per rfc2606
    return ("something.invalid", 54321)


def encrypt_key_pem(private_key_pem: trustme.Blob, password: bytes) -> trustme.Blob:
    private_key = serialization.load_pem_private_key(
        private_key_pem.bytes(), password=None, backend=default_backend()
    )
    encrypted_key = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.BestAvailableEncryption(password),
    )
    return trustme.Blob(encrypted_key)

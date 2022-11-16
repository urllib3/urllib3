#!/usr/bin/env python

"""
Dummy server used for unit testing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import logging
import os
import socket
import ssl
import sys
import threading
import typing
import warnings
from collections.abc import Coroutine, Generator
from datetime import datetime

import tornado.httpserver
import tornado.ioloop
import tornado.netutil
import tornado.web
import trustme
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from urllib3.exceptions import HTTPWarning
from urllib3.util import ALPN_PROTOCOLS, resolve_cert_reqs, resolve_ssl_version

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
    "alpn_protocols": ALPN_PROTOCOLS,
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
    ) -> None:
        super().__init__()
        self.daemon = True

        self.socket_handler = socket_handler
        self.host = host
        self.ready_event = ready_event

    def _start_server(self) -> None:
        if self.USE_IPV6:
            sock = socket.socket(socket.AF_INET6)
        else:
            warnings.warn("No IPv6 support. Falling back to IPv4.", NoIPv6Warning)
            sock = socket.socket(socket.AF_INET)
        if sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, 0))
        self.port = sock.getsockname()[1]

        # Once listen() returns, the server socket is ready
        sock.listen(1)

        if self.ready_event:
            self.ready_event.set()

        self.socket_handler(sock)
        sock.close()

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
    if alpn_protocols and hasattr(ctx, "set_alpn_protocols"):
        try:
            ctx.set_alpn_protocols(alpn_protocols)
        except NotImplementedError:
            pass
    return ctx


def run_tornado_app(
    app: tornado.web.Application,
    certs: dict[str, typing.Any] | None,
    scheme: str,
    host: str,
) -> tuple[tornado.httpserver.HTTPServer, int]:
    # We can't use fromtimestamp(0) because of CPython issue 29097, so we'll
    # just construct the datetime object directly.
    app.last_req = datetime(1970, 1, 1)  # type: ignore[attr-defined]

    if scheme == "https":
        assert certs is not None
        ssl_opts = ssl_options_to_context(**certs)
        http_server = tornado.httpserver.HTTPServer(app, ssl_options=ssl_opts)
    else:
        http_server = tornado.httpserver.HTTPServer(app)

    sockets = tornado.netutil.bind_sockets(None, address=host)  # type: ignore[arg-type]
    port = sockets[0].getsockname()[1]
    http_server.add_sockets(sockets)
    return http_server, port


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


R = typing.TypeVar("R")


def _run_and_close_tornado(
    async_fn: typing.Callable[P, Coroutine[typing.Any, typing.Any, R]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    tornado_loop = None

    async def inner_fn() -> R:
        nonlocal tornado_loop
        tornado_loop = tornado.ioloop.IOLoop.current()
        return await async_fn(*args, **kwargs)

    try:
        return asyncio.run(inner_fn())
    finally:
        tornado_loop.close(all_fds=True)  # type: ignore[union-attr]


@contextlib.contextmanager
def run_loop_in_thread() -> Generator[tornado.ioloop.IOLoop, None, None]:
    loop_started: concurrent.futures.Future[
        tuple[tornado.ioloop.IOLoop, asyncio.Event]
    ] = concurrent.futures.Future()
    with concurrent.futures.ThreadPoolExecutor(
        1, thread_name_prefix="test IOLoop"
    ) as tpe:

        async def run() -> None:
            io_loop = tornado.ioloop.IOLoop.current()
            stop_event = asyncio.Event()
            loop_started.set_result((io_loop, stop_event))
            await stop_event.wait()

        # run asyncio.run in a thread and collect exceptions from *either*
        # the loop failing to start, or failing to close
        ran = tpe.submit(_run_and_close_tornado, run)  # type: ignore[arg-type]
        for f in concurrent.futures.as_completed((loop_started, ran)):  # type: ignore[misc]
            if f is loop_started:
                io_loop, stop_event = loop_started.result()
                try:
                    yield io_loop
                finally:
                    io_loop.add_callback(stop_event.set)

            elif f is ran:
                # if this is the first iteration the loop failed to start
                # if it's the second iteration the loop has finished or
                # the loop failed to close and we need to raise the exception
                ran.result()
                return


def main() -> int:
    # For debugging dummyserver itself - python -m dummyserver.server
    from .handlers import TestingApp

    host = "127.0.0.1"

    async def amain() -> int:
        app = tornado.web.Application([(r".*", TestingApp)])
        server, port = run_tornado_app(app, None, "http", host)

        print(f"Listening on http://{host}:{port}")
        await asyncio.Event().wait()
        return 0

    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())

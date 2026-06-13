from __future__ import annotations

import errno
import socket

import pytest

import dummyserver.hypercornserver as hypercornserver


class SocketStub:
    def __init__(self, *, fail_on_bind: bool) -> None:
        self.closed = False
        self.fail_on_bind = fail_on_bind

    def setsockopt(self, *args: object) -> None:
        pass

    def setblocking(self, flag: bool) -> None:
        pass

    def bind(self, address: tuple[str, int]) -> None:
        if self.fail_on_bind:
            raise OSError(errno.EADDRINUSE, "Address already in use")

    def getsockname(self) -> tuple[str, int]:
        return ("127.0.0.1", 54321)

    def set_inheritable(self, inheritable: bool) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_hypercorn_config_closes_sockets_after_bind_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sockets: list[SocketStub] = []
    getaddrinfo_results: list[object] = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("0.0.0.0", 0)),
    ]

    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[object]:
        return getaddrinfo_results

    def fake_socket(*args: object) -> SocketStub:
        sock = SocketStub(fail_on_bind=len(sockets) == 1)
        sockets.append(sock)
        return sock

    monkeypatch.setattr(
        "dummyserver.hypercornserver.socket.getaddrinfo", fake_getaddrinfo
    )
    monkeypatch.setattr("dummyserver.hypercornserver.socket.socket", fake_socket)

    with pytest.raises(OSError) as exc_info:
        hypercornserver.Config()._create_urllib3_sockets("localhost:0")

    assert exc_info.value.errno == errno.EADDRINUSE
    assert len(sockets) == 2
    assert all(sock.closed for sock in sockets)

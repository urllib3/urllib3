from __future__ import annotations

import errno
import socket
import typing

import pytest

from dummyserver.hypercornserver import Config


class FakeSocket:
    created: typing.ClassVar[list[FakeSocket]] = []

    def __init__(
        self, family: socket.AddressFamily, kind: socket.SocketKind, proto: int
    ) -> None:
        self.family = family
        self.kind = kind
        self.proto = proto
        self.closed = False
        self.index = len(self.created)
        self.created.append(self)

    def setsockopt(self, level: int, optname: int, value: int) -> None:
        pass

    def setblocking(self, flag: bool) -> None:
        pass

    def bind(self, address: tuple[str, int]) -> None:
        if self.index % 2:
            raise OSError(errno.EADDRINUSE, "address already in use")

    def getsockname(self) -> tuple[str, int]:
        return "127.0.0.1", 54321

    def set_inheritable(self, inheritable: bool) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_hypercorn_socket_retry_closes_partial_sockets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(
        host: str,
        port: int,
        family: int,
        kind: int,
        proto: int,
        flags: int,
    ) -> list[tuple[typing.Any, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "socket", FakeSocket)

    with pytest.raises(OSError, match="failed to bind socket"):
        Config()._retry_create_urllib3_sockets("localhost:0")

    assert len(FakeSocket.created) == 20
    assert all(sock.closed for sock in FakeSocket.created)

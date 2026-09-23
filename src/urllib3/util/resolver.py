from __future__ import annotations

import socket
import typing


class Resolver(typing.Protocol):
    """Type stub for the network address resolver.

    This allows to override CPython's default `getaddrinfo()`_ function
    which can be used to customize the resolution of domain names, hostnames,
    and IP addresses.

    .. _getaddrinfo(): https://docs.python.org/3/library/socket.html#socket.getaddrinfo
    """

    def __call__(
        self,
        host: bytes | str | None,
        port: bytes | str | int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[
        tuple[
            socket.AddressFamily,
            socket.SocketKind,
            int,
            str,
            tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes],
        ]
    ]: ...

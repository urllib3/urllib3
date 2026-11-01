from __future__ import annotations

import signal
import threading
import time
import typing
from socket import socket, socketpair
from types import FrameType

import pytest

from urllib3.util.wait import (
    _have_working_poll,
    poll_wait_for_socket,
    select_wait_for_socket,
    wait_for_read,
    wait_for_socket,
    wait_for_write,
)

TYPE_SOCKET_PAIR = tuple[socket, socket]
TYPE_WAIT_FOR = typing.Callable[..., bool]


@pytest.fixture(scope="module", autouse=True)
def ignore_sigalrm() -> typing.Generator[None]:
    """Keep a stray SIGALRM from killing the whole run.

    The tests below install their own SIGALRM handler and restore the previous
    one when they are done; with this fixture "the previous one" ignores the
    signal instead of terminating the process. The previous action is put back
    when this module is finished, so nothing leaks into other tests.
    """
    if not hasattr(signal, "setitimer"):
        yield
        return
    old_handler = signal.signal(signal.SIGALRM, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGALRM, old_handler)


@pytest.fixture
def spair() -> typing.Generator[TYPE_SOCKET_PAIR]:
    a, b = socketpair()
    yield a, b
    a.close()
    b.close()


variants: list[TYPE_WAIT_FOR] = [wait_for_socket, select_wait_for_socket]
if _have_working_poll():
    variants.append(poll_wait_for_socket)


@pytest.mark.parametrize("wfs", variants)
def test_wait_for_socket(wfs: TYPE_WAIT_FOR, spair: TYPE_SOCKET_PAIR) -> None:
    a, b = spair

    with pytest.raises(RuntimeError):
        wfs(a, read=False, write=False)

    assert not wfs(a, read=True, timeout=0)
    assert wfs(a, write=True, timeout=0)

    b.send(b"x")
    assert wfs(a, read=True, timeout=0)
    assert wfs(a, read=True, timeout=10)
    assert wfs(a, read=True, timeout=None)

    # Fill up the socket with data
    a.setblocking(False)
    try:
        while True:
            a.send(b"x" * 999999)
    except OSError:
        pass

    # Now it's not writable anymore
    assert not wfs(a, write=True, timeout=0)

    # But if we ask for read-or-write, that succeeds
    assert wfs(a, read=True, write=True, timeout=0)

    # Unless we read from it
    assert a.recv(1) == b"x"
    assert not wfs(a, read=True, write=True, timeout=0)

    # But if the remote peer closes the socket, then it becomes readable
    b.close()
    assert wfs(a, read=True, timeout=0)

    # Waiting for a socket that's actually been closed is just a bug, and
    # raises some kind of helpful exception (exact details depend on the
    # platform).
    with pytest.raises(Exception):
        wfs(b, read=True)


@pytest.mark.parametrize("wfs", variants)
def test_wait_for_socket_accepts_timeouts_the_platform_cannot_represent(
    wfs: TYPE_WAIT_FOR, spair: TYPE_SOCKET_PAIR
) -> None:
    a, b = spair
    b.send(b"x")

    # select.poll() takes its timeout in milliseconds as a C int and
    # select.select() as a time_t. A timeout of a few weeks, or infinity, is a
    # legal value for Timeout and for socket.settimeout(), but neither API can
    # represent it: they used to raise instead of waiting.
    assert wfs(a, read=True, timeout=1e9)
    assert wfs(a, read=True, timeout=float("inf"))


@pytest.mark.parametrize("wfs", variants)
def test_wait_for_socket_caps_the_timeout_at_what_the_platform_accepts(
    monkeypatch: pytest.MonkeyPatch, wfs: TYPE_WAIT_FOR, spair: TYPE_SOCKET_PAIR
) -> None:
    monkeypatch.setattr("urllib3.util.wait._MAX_TIMEOUT", 0.05)
    a, b = spair

    start = time.monotonic()
    assert not wfs(a, read=True, timeout=60)
    assert time.monotonic() - start < 5


def test_wait_for_read_does_not_overflow_on_a_long_socket_timeout(
    spair: TYPE_SOCKET_PAIR,
) -> None:
    a, b = spair
    a.settimeout(1e9)
    b.send(b"x")

    assert wait_for_read(a, a.gettimeout())


def test_wait_for_read_write(spair: TYPE_SOCKET_PAIR) -> None:
    a, b = spair

    assert not wait_for_read(a, 0)
    assert wait_for_write(a, 0)

    b.send(b"x")

    assert wait_for_read(a, 0)
    assert wait_for_write(a, 0)

    # Fill up the socket with data
    a.setblocking(False)
    try:
        while True:
            a.send(b"x" * 999999)
    except OSError:
        pass

    # Now it's not writable anymore
    assert not wait_for_write(a, 0)


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="need setitimer() support")
@pytest.mark.parametrize("wfs", variants)
def test_eintr(wfs: TYPE_WAIT_FOR, spair: TYPE_SOCKET_PAIR) -> None:
    a, b = spair
    interrupt_count = [0]

    def handler(sig: int, frame: FrameType | None) -> typing.Any:
        assert sig == signal.SIGALRM
        interrupt_count[0] += 1

    old_handler = signal.signal(signal.SIGALRM, handler)
    try:
        assert not wfs(a, read=True, timeout=0)
        start = time.monotonic()
        try:
            # Start delivering SIGALRM 10 times per second
            signal.setitimer(signal.ITIMER_REAL, 0.1, 0.1)
            # Sleep for 1 second (we hope!)
            wfs(a, read=True, timeout=1)
        finally:
            # Stop delivering SIGALRM
            signal.setitimer(signal.ITIMER_REAL, 0)
        end = time.monotonic()
        dur = end - start
        assert 0.9 < dur < 3
    finally:
        signal.signal(signal.SIGALRM, old_handler)

    assert interrupt_count[0] > 0


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="need setitimer() support")
@pytest.mark.parametrize("wfs", variants)
def test_eintr_zero_timeout(wfs: TYPE_WAIT_FOR, spair: TYPE_SOCKET_PAIR) -> None:
    a, b = spair
    interrupt_count = [0]

    def handler(sig: int, frame: FrameType | None) -> typing.Any:
        assert sig == signal.SIGALRM
        interrupt_count[0] += 1

    old_handler = signal.signal(signal.SIGALRM, handler)
    try:
        assert not wfs(a, read=True, timeout=0)
        try:
            # Start delivering SIGALRM 1000 times per second,
            # to trigger race conditions such as
            # https://github.com/urllib3/urllib3/issues/1396.
            signal.setitimer(signal.ITIMER_REAL, 0.001, 0.001)
            # Hammer the system call for a while to trigger the
            # race.
            end = time.monotonic() + 5
            for i in range(100000):
                wfs(a, read=True, timeout=0)
                if time.monotonic() >= end:
                    break
        finally:
            # Stop delivering SIGALRM
            signal.setitimer(signal.ITIMER_REAL, 0)
    finally:
        signal.signal(signal.SIGALRM, old_handler)

    assert interrupt_count[0] > 0


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="need setitimer() support")
@pytest.mark.parametrize("wfs", variants)
def test_eintr_infinite_timeout(wfs: TYPE_WAIT_FOR, spair: TYPE_SOCKET_PAIR) -> None:
    a, b = spair
    interrupt_count = [0]

    def handler(sig: int, frame: FrameType | None) -> typing.Any:
        assert sig == signal.SIGALRM
        interrupt_count[0] += 1

    def make_a_readable_after_one_second() -> None:
        time.sleep(1)
        b.send(b"x")

    old_handler = signal.signal(signal.SIGALRM, handler)
    try:
        assert not wfs(a, read=True, timeout=0)
        start = time.monotonic()
        try:
            # Start delivering SIGALRM 10 times per second
            signal.setitimer(signal.ITIMER_REAL, 0.1, 0.1)
            # Sleep for 1 second (we hope!)
            thread = threading.Thread(target=make_a_readable_after_one_second)
            thread.start()
            wfs(a, read=True)
        finally:
            # Stop delivering SIGALRM
            signal.setitimer(signal.ITIMER_REAL, 0)
            thread.join()
        end = time.monotonic()
        dur = end - start
        assert 0.9 < dur < 3
    finally:
        signal.signal(signal.SIGALRM, old_handler)

    assert interrupt_count[0] > 0

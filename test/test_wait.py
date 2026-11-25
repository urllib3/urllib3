from __future__ import annotations

import platform
import signal
import threading
import time
import typing
from socket import socket, socketpair
from types import FrameType

import pytest

from urllib3.util.wait import (
    _POLL_MAX_MILLISECONDS,
    _have_working_poll,
    _poll_timeout,
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


# ``select.poll()`` takes its timeout as a C ``int`` of milliseconds, and
# ``select.select()`` rejects timeouts that don't fit in a ``time_t``. Both
# overflow well below the timeouts that ``Timeout`` accepts, so a value past
# these thresholds is clamped rather than raised on.
FOREVER_SECONDS = 1e9


@pytest.mark.parametrize("wfs", variants)
def test_wait_for_socket_timeout_too_large(
    wfs: TYPE_WAIT_FOR, spair: TYPE_SOCKET_PAIR
) -> None:
    a, b = spair
    b.send(b"x")

    assert wfs(a, read=True, timeout=FOREVER_SECONDS)
    assert wfs(a, read=True, timeout=float("inf"))


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Windows rejects socket timeouts that don't fit in a 32-bit timeval, "
    "so settimeout() raises before wait_for_read() is called",
)
def test_wait_for_read_timeout_too_large(spair: TYPE_SOCKET_PAIR) -> None:
    # The pyOpenSSL contrib calls ``wait_for_read(sock, sock.gettimeout())``,
    # so a socket configured with a long timeout has to be waitable.
    # ``HTTPConnection.is_connected()`` passes ``timeout=0.0`` and is not
    # affected by this clamp.
    a, b = spair
    a.settimeout(FOREVER_SECONDS)
    b.send(b"x")

    assert wait_for_read(a, a.gettimeout())


def test_poll_submillisecond_timeout_is_not_truncated(
    spair: TYPE_SOCKET_PAIR,
) -> None:
    # ``int(timeout * 1000)`` truncated 0.0004 s to 0 ms, so ``poll()`` returned
    # immediately. Rounding up waits at least 1 ms. ``0`` stays immediate and
    # ``None`` stays indefinite, and the result still cannot exceed poll's max.
    assert _poll_timeout(None) is None
    assert _poll_timeout(0) == 0
    assert _poll_timeout(0.0004) == 1
    assert _poll_timeout(1e9) == _POLL_MAX_MILLISECONDS
    assert _poll_timeout(float("inf")) == _POLL_MAX_MILLISECONDS

    if not _have_working_poll():
        return

    sock = spair[0]
    # Nothing is readable, so timeout=0 comes back without waiting.
    assert not poll_wait_for_socket(sock, read=True, timeout=0)

    durations: list[float] = []
    for _ in range(5):
        start = time.monotonic()
        assert not poll_wait_for_socket(sock, read=True, timeout=0.0004)
        durations.append(time.monotonic() - start)

    # Distinguish a real ~1 ms wait from the truncated 0 ms return (~0.002 ms).
    assert min(durations) >= 0.0005


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

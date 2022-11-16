from __future__ import annotations

import errno
import logging
import os
import platform
import socket
import sys
import typing
import warnings
from importlib.abc import Loader, MetaPathFinder
from types import ModuleType, TracebackType

import pytest

try:
    try:
        import brotlicffi as brotli  # type: ignore[import]
    except ImportError:
        import brotli  # type: ignore[import]
except ImportError:
    brotli = None

try:
    import zstandard as zstd  # type: ignore[import]
except ImportError:
    zstd = None

import functools

from urllib3 import util
from urllib3.connectionpool import ConnectionPool
from urllib3.exceptions import HTTPWarning
from urllib3.util import ssl_

try:
    import urllib3.contrib.pyopenssl as pyopenssl
except ImportError:
    pyopenssl = None  # type: ignore[assignment]

if typing.TYPE_CHECKING:
    import ssl

    from typing_extensions import Literal


_RT = typing.TypeVar("_RT")  # return type
_TestFuncT = typing.TypeVar("_TestFuncT", bound=typing.Callable[..., typing.Any])


# We need a host that will not immediately close the connection with a TCP
# Reset.
if platform.system() == "Windows":
    # Reserved loopback subnet address
    TARPIT_HOST = "127.0.0.0"
else:
    # Reserved internet scoped address
    # https://www.iana.org/assignments/iana-ipv4-special-registry/iana-ipv4-special-registry.xhtml
    TARPIT_HOST = "240.0.0.0"

# (Arguments for socket, is it IPv6 address?)
VALID_SOURCE_ADDRESSES = [(("::1", 0), True), (("127.0.0.1", 0), False)]
# RFC 5737: 192.0.2.0/24 is for testing only.
# RFC 3849: 2001:db8::/32 is for documentation only.
INVALID_SOURCE_ADDRESSES = [(("192.0.2.255", 0), False), (("2001:db8::1", 0), True)]

# We use timeouts in three different ways in our tests
#
# 1. To make sure that the operation timeouts, we can use a short timeout.
# 2. To make sure that the test does not hang even if the operation should succeed, we
#    want to use a long timeout, even more so on CI where tests can be really slow
# 3. To test our timeout logic by using two different values, eg. by using different
#    values at the pool level and at the request level.
SHORT_TIMEOUT = 0.001
LONG_TIMEOUT = 0.01
if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") == "true":
    LONG_TIMEOUT = 0.5

DUMMY_POOL = ConnectionPool("dummy")


def _can_resolve(host: str) -> bool:
    """Returns True if the system can resolve host to an address."""
    try:
        socket.getaddrinfo(host, None, socket.AF_UNSPEC)
        return True
    except socket.gaierror:
        return False


def has_alpn(ctx_cls: type[ssl.SSLContext] | None = None) -> bool:
    """Detect if ALPN support is enabled."""
    ctx_cls = ctx_cls or util.SSLContext
    ctx = ctx_cls(protocol=ssl_.PROTOCOL_TLS)  # type: ignore[misc]
    try:
        if hasattr(ctx, "set_alpn_protocols"):
            ctx.set_alpn_protocols(ssl_.ALPN_PROTOCOLS)
            return True
    except NotImplementedError:
        pass
    return False


# Some systems might not resolve "localhost." correctly.
# See https://github.com/urllib3/urllib3/issues/1809 and
# https://github.com/urllib3/urllib3/pull/1475#issuecomment-440788064.
RESOLVES_LOCALHOST_FQDN = _can_resolve("localhost.")


def clear_warnings(cls: type[Warning] = HTTPWarning) -> None:
    new_filters = []
    for f in warnings.filters:
        if issubclass(f[2], cls):
            continue
        new_filters.append(f)
    warnings.filters[:] = new_filters  # type: ignore[index]


def setUp() -> None:
    clear_warnings()
    warnings.simplefilter("ignore", HTTPWarning)


def notWindows() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    """Skips this test on Windows"""
    return pytest.mark.skipif(
        platform.system() == "Windows",
        reason="Test does not run on Windows",
    )


def onlyBrotli() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    return pytest.mark.skipif(
        brotli is None, reason="only run if brotli library is present"
    )


def notBrotli() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    return pytest.mark.skipif(
        brotli is not None, reason="only run if a brotli library is absent"
    )


def onlyZstd() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    return pytest.mark.skipif(
        zstd is None, reason="only run if a python-zstandard library is installed"
    )


def notZstd() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    return pytest.mark.skipif(
        zstd is not None,
        reason="only run if a python-zstandard library is not installed",
    )


# Hack to make pytest evaluate a condition at test runtime instead of collection time.
def lazy_condition(condition: typing.Callable[[], bool]) -> bool:
    class LazyCondition:
        def __bool__(self) -> bool:
            return condition()

    return typing.cast(bool, LazyCondition())


def onlySecureTransport() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    """Runs this test when SecureTransport is in use."""
    return pytest.mark.skipif(
        lazy_condition(lambda: not ssl_.IS_SECURETRANSPORT),
        reason="Test only runs with SecureTransport",
    )


def notSecureTransport() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    """Skips this test when SecureTransport is in use."""
    return pytest.mark.skipif(
        lazy_condition(lambda: ssl_.IS_SECURETRANSPORT),
        reason="Test does not run with SecureTransport",
    )


_requires_network_has_route = None


def requires_network() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    """Helps you skip tests that require the network"""

    def _is_unreachable_err(err: Exception) -> bool:
        return getattr(err, "errno", None) in (
            errno.ENETUNREACH,
            errno.EHOSTUNREACH,  # For OSX
        )

    def _has_route() -> bool:
        try:
            sock = socket.create_connection((TARPIT_HOST, 80), 0.0001)
            sock.close()
            return True
        except socket.timeout:
            return True
        except OSError as e:
            if _is_unreachable_err(e):
                return False
            else:
                raise

    global _requires_network_has_route

    if _requires_network_has_route is None:
        _requires_network_has_route = _has_route()

    return pytest.mark.skipif(
        not _requires_network_has_route,
        reason="Can't run the test because the network is unreachable",
    )


def requires_ssl_context_keyfile_password() -> typing.Callable[
    [_TestFuncT], _TestFuncT
]:
    return pytest.mark.skipif(
        lazy_condition(lambda: ssl_.IS_SECURETRANSPORT),
        reason="Test requires password parameter for SSLContext.load_cert_chain()",
    )


def resolvesLocalhostFQDN() -> typing.Callable[[_TestFuncT], _TestFuncT]:
    """Test requires successful resolving of 'localhost.'"""
    return pytest.mark.skipif(
        not RESOLVES_LOCALHOST_FQDN,
        reason="Can't resolve localhost.",
    )


def withPyOpenSSL(test: typing.Callable[..., _RT]) -> typing.Callable[..., _RT]:
    @functools.wraps(test)
    def wrapper(*args: typing.Any, **kwargs: typing.Any) -> _RT:
        if not pyopenssl:
            pytest.skip("pyopenssl not available, skipping test.")
            return test(*args, **kwargs)

        pyopenssl.inject_into_urllib3()
        result = test(*args, **kwargs)
        pyopenssl.extract_from_urllib3()
        return result

    return wrapper


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class LogRecorder:
    def __init__(self, target: logging.Logger = logging.root) -> None:
        super().__init__()
        self._target = target
        self._handler = _ListHandler()

    @property
    def records(self) -> list[logging.LogRecord]:
        return self._handler.records

    def install(self) -> None:
        self._target.addHandler(self._handler)

    def uninstall(self) -> None:
        self._target.removeHandler(self._handler)

    def __enter__(self) -> list[logging.LogRecord]:
        self.install()
        return self.records

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        self.uninstall()
        return False


class ImportBlockerLoader(Loader):
    def load_module(self, fullname: str) -> ModuleType:
        raise ImportError(f"import of {fullname} is blocked")


class ImportBlocker(MetaPathFinder):
    """
    Block Imports

    To be placed on ``sys.meta_path``. This ensures that the modules
    specified cannot be imported, even if they are a builtin.
    """

    def __init__(self, *namestoblock: str) -> None:
        self.namestoblock = namestoblock

    def find_module(
        self, fullname: str, path: typing.Sequence[bytes | str] | None = None
    ) -> Loader | None:
        if fullname in self.namestoblock:
            return ImportBlockerLoader()
        return None


class ModuleStash(MetaPathFinder):
    """
    Stashes away previously imported modules

    If we reimport a module the data from coverage is lost, so we reuse the old
    modules
    """

    def __init__(
        self, namespace: str, modules: dict[str, ModuleType] = sys.modules
    ) -> None:
        self.namespace = namespace
        self.modules = modules
        self._data: dict[str, ModuleType] = {}

    def stash(self) -> None:
        if self.namespace in self.modules:
            self._data[self.namespace] = self.modules.pop(self.namespace)

        for module in list(self.modules.keys()):
            if module.startswith(self.namespace + "."):
                self._data[module] = self.modules.pop(module)

    def pop(self) -> None:
        self.modules.pop(self.namespace, None)

        for module in list(self.modules.keys()):
            if module.startswith(self.namespace + "."):
                self.modules.pop(module)

        self.modules.update(self._data)

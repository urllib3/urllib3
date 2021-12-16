"""
Python HTTP library with thread-safe connection pooling, file post support, user friendly, and more
"""

# Set default logging handler to avoid "No handler found" warnings.
import logging
import warnings
from logging import NullHandler
from typing import Any, Mapping, Optional, TextIO, Type, Union

from . import exceptions
from ._collections import HTTPHeaderDict
from ._version import __version__
from .connection import _TYPE_BODY
from .connectionpool import HTTPConnectionPool, HTTPSConnectionPool, connection_from_url
from .filepost import _TYPE_FIELDS, encode_multipart_formdata
from .poolmanager import PoolManager, ProxyManager, proxy_from_url
from .response import BaseHTTPResponse, HTTPResponse
from .util.request import make_headers
from .util.retry import Retry
from .util.timeout import Timeout

__author__ = "Andrey Petrov (andrey.petrov@shazow.net)"
__license__ = "MIT"
__version__ = __version__

__all__ = (
    "HTTPConnectionPool",
    "HTTPHeaderDict",
    "HTTPSConnectionPool",
    "PoolManager",
    "ProxyManager",
    "HTTPResponse",
    "Retry",
    "Timeout",
    "add_stderr_logger",
    "connection_from_url",
    "disable_warnings",
    "encode_multipart_formdata",
    "make_headers",
    "proxy_from_url",
    "request",
)

logging.getLogger(__name__).addHandler(NullHandler())


def add_stderr_logger(level: int = logging.DEBUG) -> "logging.StreamHandler[TextIO]":
    """
    Helper for quickly adding a StreamHandler to the logger. Useful for
    debugging.

    Returns the handler after adding it.
    """
    # This method needs to be in this __init__.py to get the __name__ correct
    # even if urllib3 is vendored within another package.
    logger = logging.getLogger(__name__)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.debug("Added a stderr logging handler to logger: %s", __name__)
    return handler


# ... Clean up.
del NullHandler


# All warning filters *must* be appended unless you're really certain that they
# shouldn't be: otherwise, it's very hard for users to use most Python
# mechanisms to silence them.
# SecurityWarning's always go off by default.
warnings.simplefilter("always", exceptions.SecurityWarning, append=True)
# InsecurePlatformWarning's don't vary between requests, so we keep it default.
warnings.simplefilter("default", exceptions.InsecurePlatformWarning, append=True)
# SNIMissingWarnings should go off only once.
warnings.simplefilter("default", exceptions.SNIMissingWarning, append=True)


def disable_warnings(category: Type[Warning] = exceptions.HTTPWarning) -> None:
    """
    Helper for quickly disabling all urllib3 warnings.
    """
    warnings.simplefilter("ignore", category)


_DEFAULT_POOL = PoolManager()


def request(
    method: str,
    url: str,
    *,
    body: Optional[_TYPE_BODY] = None,
    fields: Optional[_TYPE_FIELDS] = None,
    headers: Optional[Mapping[str, str]] = None,
    preload_content: Optional[bool] = True,
    decode_content: Optional[bool] = True,
    redirect: Optional[bool] = True,
    retries: Optional[Union[Retry, bool, int]] = None,
    timeout: Optional[Union[Timeout, float, int]] = 3,
    json: Optional[Any] = None,
) -> BaseHTTPResponse:
    """
    A convenience, top-level request method. It uses a module-global ``PoolManager`` instance.
    Therefore, its side effects could be shared across dependencies relying on it.
    To avoid side effects create a new ``PoolManager`` instance and use it instead.
    The method does not accept low-level ``**urlopen_kw`` keyword arguments.
    """

    return _DEFAULT_POOL.request(
        method,
        url,
        body=body,
        fields=fields,
        headers=headers,
        preload_content=preload_content,
        decode_content=decode_content,
        redirect=redirect,
        retries=retries,
        timeout=timeout,
        json=json,
    )

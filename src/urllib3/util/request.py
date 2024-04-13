from __future__ import annotations

import io
import typing
from base64 import b64encode
from enum import Enum

from ..exceptions import UnrewindableBodyError
from .util import to_bytes

if typing.TYPE_CHECKING:
    from typing import Final

# Pass as a value within ``headers`` to skip
# emitting some HTTP headers that are added automatically.
# The only headers that are supported are ``Accept-Encoding``,
# ``Host``, and ``User-Agent``.
SKIP_HEADER = "@@@SKIP_HEADER@@@"
SKIPPABLE_HEADERS = frozenset(["accept-encoding", "host", "user-agent"])

ACCEPT_ENCODING = "gzip,deflate"
try:
    try:
        import brotlicffi as _unused_module_brotli  # type: ignore[import-not-found] # noqa: F401
    except ImportError:
        import brotli as _unused_module_brotli  # type: ignore[import-not-found] # noqa: F401
except ImportError:
    pass
else:
    ACCEPT_ENCODING += ",br"
try:
    import zstandard as _unused_module_zstd  # noqa: F401
except ImportError:
    pass
else:
    ACCEPT_ENCODING += ",zstd"


class _TYPE_FAILEDTELL(Enum):
    token = 0


_FAILEDTELL: Final[_TYPE_FAILEDTELL] = _TYPE_FAILEDTELL.token

_TYPE_BODY_POSITION = typing.Union[int, _TYPE_FAILEDTELL]

# When sending a request with these methods we aren't expecting
# a body so don't need to set an explicit 'Content-Length: 0'
# The reason we do this in the negative instead of tracking methods
# which 'should' have a body is because unknown methods should be
# treated as if they were 'POST' which *does* expect a body.
_METHODS_NOT_EXPECTING_BODY = {"GET", "HEAD", "DELETE", "TRACE", "OPTIONS", "CONNECT"}


def make_headers(
    keep_alive: bool | None = None,
    accept_encoding: bool | list[str] | str | None = None,
    user_agent: str | None = None,
    basic_auth: str | None = None,
    proxy_basic_auth: str | None = None,
    disable_cache: bool | None = None,
) -> dict[str, str]:
    """
    Shortcuts for generating request headers.

    :param keep_alive:
        If ``True``, adds 'connection: keep-alive' header.

    :param accept_encoding:
        Can be a boolean, list, or string.
        ``True`` translates to 'gzip,deflate'.  If either the ``brotli`` or
        ``brotlicffi`` package is installed 'gzip,deflate,br' is used instead.
        List will get joined by comma.
        String will be used as provided.

    :param user_agent:
        String representing the user-agent you want, such as
        "python-urllib3/0.6"

    :param basic_auth:
        Colon-separated username:password string for 'authorization: basic ...'
        auth header.

    :param proxy_basic_auth:
        Colon-separated username:password string for 'proxy-authorization: basic ...'
        auth header.

    :param disable_cache:
        If ``True``, adds 'cache-control: no-cache' header.

    Example:

    .. code-block:: python

        import urllib3

        print(urllib3.util.make_headers(keep_alive=True, user_agent="Batman/1.0"))
        # {'connection': 'keep-alive', 'user-agent': 'Batman/1.0'}
        print(urllib3.util.make_headers(accept_encoding=True))
        # {'accept-encoding': 'gzip,deflate'}
    """
    headers: dict[str, str] = {}
    if accept_encoding:
        if isinstance(accept_encoding, str):
            pass
        elif isinstance(accept_encoding, list):
            accept_encoding = ",".join(accept_encoding)
        else:
            accept_encoding = ACCEPT_ENCODING
        headers["accept-encoding"] = accept_encoding

    if user_agent:
        headers["user-agent"] = user_agent

    if keep_alive:
        headers["connection"] = "keep-alive"

    if basic_auth:
        headers["authorization"] = (
            f"Basic {b64encode(basic_auth.encode('latin-1')).decode()}"
        )

    if proxy_basic_auth:
        headers["proxy-authorization"] = (
            f"Basic {b64encode(proxy_basic_auth.encode('latin-1')).decode()}"
        )

    if disable_cache:
        headers["cache-control"] = "no-cache"

    return headers


def set_file_position(
    body: typing.Any, pos: _TYPE_BODY_POSITION | None
) -> _TYPE_BODY_POSITION | None:
    """
    If a position is provided, move file to that point.
    Otherwise, we'll attempt to record a position for future use.
    """
    if pos is not None:
        rewind_body(body, pos)
    elif getattr(body, "tell", None) is not None:
        try:
            pos = body.tell()
        except OSError:
            # This differentiates from None, allowing us to catch
            # a failed `tell()` later when trying to rewind the body.
            pos = _FAILEDTELL

    return pos


def rewind_body(body: typing.IO[typing.AnyStr], body_pos: _TYPE_BODY_POSITION) -> None:
    """
    Attempt to rewind body to a certain position.
    Primarily used for request redirects and retries.

    :param body:
        File-like object that supports seek.

    :param int pos:
        Position to seek to in file.
    """
    body_seek = getattr(body, "seek", None)
    if body_seek is not None and isinstance(body_pos, int):
        try:
            body_seek(body_pos)
        except OSError as e:
            raise UnrewindableBodyError(
                "An error occurred when rewinding request body for redirect/retry."
            ) from e
    elif body_pos is _FAILEDTELL:
        raise UnrewindableBodyError(
            "Unable to record file position for rewinding "
            "request body during a redirect/retry."
        )
    else:
        raise ValueError(
            f"body_pos must be of type integer, instead it was {type(body_pos)}."
        )


class ChunksAndContentLength(typing.NamedTuple):
    chunks: typing.Iterable[bytes]
    content_length: int | None


def chunk_readable(body: typing.Any, blocksize: int) -> typing.Iterable[bytes]:
    encode = isinstance(body, io.TextIOBase)
    while True:
        datablock = body.read(blocksize)
        if not datablock:
            break
        if encode:
            datablock = datablock.encode("iso-8859-1")
        yield datablock


def body_to_bytes(body: typing.Any, blocksize: int) -> ChunksAndContentLength:
    """Convert body data to sendable bytes and measures the length of it.
    If body is iterable data then iter whole data and buffer it.
    """

    if isinstance(body, (str, bytes)):
        chunks = (to_bytes(body),)
        content_length = len(chunks[0])

    elif hasattr(body, "read"):
        chunks = bytearray()
        for chunk in chunk_readable(body, blocksize):
            chunks += chunk

        chunks = (chunks,)
        content_length = len(chunks[0])

    elif hasattr(body, "__next__"):  # check iterator type
        chunks = bytearray()
        for chunk in body:
            try:
                chunks += chunk
            except TypeError:
                # if chunk is not byte
                raise TypeError(
                    f"'body' must be a bytes-like object, file-like "
                    f"object, or iterable. Instead was {body!r}"
                ) from None

        chunks = (chunks,)
        content_length = len(chunks[0])

    else:
        # Otherwise we need to start checking via duck-typing.
        try:
            mv = memoryview(body)
            chunks = (body,)
            content_length = mv.nbytes
        except TypeError:
            raise TypeError(
                f"'body' must be a bytes-like object, file-like "
                f"object, or iterable. Instead was {body!r}"
            ) from None

    return ChunksAndContentLength(chunks=chunks, content_length=content_length)


def body_to_chunks(body: typing.Any, blocksize: int) -> ChunksAndContentLength:
    """Takes HTTP body and blocksize and transforms
    them into an iterable chunks to pass to socket.sendall().
    This function is only used when header has Transfer-Encoding.
    """

    chunks: typing.Iterable[bytes]
    content_length: int | None

    content_length = None

    # File-like object, TODO: use seek() and tell() for length?
    if hasattr(body, "read"):
        chunks = chunk_readable(body, blocksize)

    elif isinstance(body, (str, bytes)):
        chunks = (to_bytes(body),)

    # Otherwise we need to start checking via duck-typing.
    else:
        try:
            # Check if the body is an iterable
            chunks = iter(body)
        except TypeError:
            raise TypeError(
                f"'body' must be a bytes-like object, file-like "
                f"object, or iterable. Instead was {body!r}"
            ) from None

    return ChunksAndContentLength(chunks=chunks, content_length=content_length)

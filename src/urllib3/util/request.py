from base64 import b64encode
from enum import Enum
from typing import IO, TYPE_CHECKING, Any, AnyStr, Dict, List, Optional, Union

from ..exceptions import UnrewindableBodyError

if TYPE_CHECKING:
    from typing_extensions import Final

# Pass as a value within ``headers`` to skip
# emitting some HTTP headers that are added automatically.
# The only headers that are supported are ``Accept-Encoding``,
# ``Host``, and ``User-Agent``.
SKIP_HEADER = "@@@SKIP_HEADER@@@"
SKIPPABLE_HEADERS = frozenset(["accept-encoding", "host", "user-agent"])

ACCEPT_ENCODING = "gzip,deflate"
try:
    try:
        import brotlicffi as _unused_module_brotli  # type: ignore[import] # noqa: F401
    except ImportError:
        import brotli as _unused_module_brotli  # type: ignore[import] # noqa: F401
except ImportError:
    pass
else:
    ACCEPT_ENCODING += ",br"


class _TYPE_FAILEDTELL(Enum):
    token = 0


_FAILEDTELL: "Final[_TYPE_FAILEDTELL]" = _TYPE_FAILEDTELL.token

_TYPE_BODY_POSITION = Union[int, _TYPE_FAILEDTELL]


def make_headers(
    keep_alive: Optional[bool] = None,
    accept_encoding: Optional[Union[bool, List[str], str]] = None,
    user_agent: Optional[str] = None,
    basic_auth: Optional[str] = None,
    proxy_basic_auth: Optional[str] = None,
    disable_cache: Optional[bool] = None,
) -> Dict[str, str]:
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
    headers: Dict[str, str] = {}
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
        headers[
            "authorization"
        ] = f"Basic {b64encode(basic_auth.encode('latin-1')).decode()}"

    if proxy_basic_auth:
        headers[
            "proxy-authorization"
        ] = f"Basic {b64encode(proxy_basic_auth.encode('latin-1')).decode()}"

    if disable_cache:
        headers["cache-control"] = "no-cache"

    return headers


def set_file_position(
    body: Any, pos: Optional[_TYPE_BODY_POSITION]
) -> Optional[_TYPE_BODY_POSITION]:
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


def rewind_body(body: IO[AnyStr], body_pos: _TYPE_BODY_POSITION) -> None:
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

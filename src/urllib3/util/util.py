from __future__ import annotations

import typing
from types import TracebackType


def to_bytes(
    x: str | bytes, encoding: str | None = None, errors: str | None = None
) -> bytes:
    """
    Encode a string to bytes, passing through bytes unchanged.

    :param x:
        The value to encode. Must be ``str`` or ``bytes``.
    :param encoding:
        The codec to use when encoding. Defaults to ``'utf-8'`` when
        *encoding* or *errors* is provided.
    :param errors:
        The error handling scheme. Defaults to ``'strict'`` when
        *encoding* or *errors* is provided.
    :return:
        The encoded bytes.
    :raises TypeError:
        If *x* is neither ``str`` nor ``bytes``.
    """
    if isinstance(x, bytes):
        return x
    elif not isinstance(x, str):
        raise TypeError(f"not expecting type {type(x).__name__}")
    if encoding or errors:
        return x.encode(encoding or "utf-8", errors=errors or "strict")
    return x.encode()


def to_str(
    x: str | bytes, encoding: str | None = None, errors: str | None = None
) -> str:
    """
    Decode bytes to a string, passing through strings unchanged.

    :param x:
        The value to decode. Must be ``str`` or ``bytes``.
    :param encoding:
        The codec to use when decoding. Defaults to ``'utf-8'`` when
        *encoding* or *errors* is provided.
    :param errors:
        The error handling scheme. Defaults to ``'strict'`` when
        *encoding* or *errors* is provided.
    :return:
        The decoded string.
    :raises TypeError:
        If *x* is neither ``str`` nor ``bytes``.
    """
    if isinstance(x, str):
        return x
    elif not isinstance(x, bytes):
        raise TypeError(f"not expecting type {type(x).__name__}")
    if encoding or errors:
        return x.decode(encoding or "utf-8", errors=errors or "strict")
    return x.decode()


def reraise(
    tp: type[BaseException] | None,
    value: BaseException,
    tb: TracebackType | None = None,
) -> typing.NoReturn:
    """
    Re-raise an exception, optionally with a different traceback.

    This is used internally to preserve the original traceback when
    re-raising errors during retries and redirects.

    :param tp:
        The exception type (unused, kept for backwards compatibility).
    :param value:
        The exception instance to re-raise.
    :param tb:
        The traceback to attach to the exception. If ``None``, the
        existing traceback on *value* is used.
    """
    try:
        if value.__traceback__ is not tb:
            raise value.with_traceback(tb)
        raise value
    finally:
        value = None  # type: ignore[assignment]
        tb = None

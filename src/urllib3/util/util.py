from types import TracebackType
from typing import NoReturn, Optional, Type, Union


def to_bytes(
    x: Union[str, bytes], encoding: Optional[str] = None, errors: Optional[str] = None
) -> bytes:
    if isinstance(x, bytes):
        return x
    elif not isinstance(x, str):
        raise TypeError(f"not expecting type {type(x).__name__}")
    if encoding or errors:
        return x.encode(encoding or "utf-8", errors=errors or "strict")
    return x.encode()


def to_str(
    x: Union[str, bytes], encoding: Optional[str] = None, errors: Optional[str] = None
) -> str:
    if isinstance(x, str):
        return x
    elif not isinstance(x, bytes):
        raise TypeError(f"not expecting type {type(x).__name__}")
    if encoding or errors:
        return x.decode(encoding or "utf-8", errors=errors or "strict")
    return x.decode()


def reraise(
    tp: Optional[Type[BaseException]],
    value: BaseException,
    tb: Optional[TracebackType] = None,
) -> NoReturn:
    try:
        if value.__traceback__ is not tb:
            raise value.with_traceback(tb)
        raise value
    finally:
        value = None  # type: ignore[assignment]
        tb = None

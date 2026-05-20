from __future__ import annotations

import http.client as httplib
import re
from email.errors import MultipartInvariantViolationDefect, StartBoundaryNotFoundDefect

from ..exceptions import InvalidHeader
from ..exceptions import HeaderParsingError


def is_fp_closed(obj: object) -> bool:
    """
    Checks whether a given file-like object is closed.

    :param obj:
        The file-like object to check.
    """

    try:
        # Check `isclosed()` first, in case Python3 doesn't set `closed`.
        # GH Issue #928
        return obj.isclosed()  # type: ignore[no-any-return, attr-defined]
    except AttributeError:
        pass

    try:
        # Check via the official file-like-object way.
        return obj.closed  # type: ignore[no-any-return, attr-defined]
    except AttributeError:
        pass

    try:
        # Check if the object is a container for another file-like object that
        # gets released on exhaustion (e.g. HTTPResponse).
        return obj.fp is None  # type: ignore[attr-defined]
    except AttributeError:
        pass

    raise ValueError("Unable to determine whether fp is closed.")


def assert_header_parsing(headers: httplib.HTTPMessage) -> None:
    """
    Asserts whether all headers have been successfully parsed.
    Extracts encountered errors from the result of parsing headers.

    Only works on Python 3.

    :param http.client.HTTPMessage headers: Headers to verify.

    :raises urllib3.exceptions.HeaderParsingError:
        If parsing errors are found.
    """

    # This will fail silently if we pass in the wrong kind of parameter.
    # To make debugging easier add an explicit check.
    if not isinstance(headers, httplib.HTTPMessage):
        raise TypeError(f"expected httplib.Message, got {type(headers)}.")

    unparsed_data = None

    # get_payload is actually email.message.Message.get_payload;
    # we're only interested in the result if it's not a multipart message
    if not headers.is_multipart():
        payload = headers.get_payload()

        if isinstance(payload, (bytes, str)):
            unparsed_data = payload

    # httplib is assuming a response body is available
    # when parsing headers even when httplib only sends
    # header data to parse_headers() This results in
    # defects on multipart responses in particular.
    # See: https://github.com/urllib3/urllib3/issues/800

    # So we ignore the following defects:
    # - StartBoundaryNotFoundDefect:
    #     The claimed start boundary was never found.
    # - MultipartInvariantViolationDefect:
    #     A message claimed to be a multipart but no subparts were found.
    defects = [
        defect
        for defect in headers.defects
        if not isinstance(
            defect, (StartBoundaryNotFoundDefect, MultipartInvariantViolationDefect)
        )
    ]

    if defects or unparsed_data:
        raise HeaderParsingError(defects=defects, unparsed_data=unparsed_data)


_HEADER_VALUE_OBS_FOLD_RE = re.compile(r"(?:\r\n|\n)[ \t]+")


def sanitize_header_items(
    header_items: list[tuple[str, str]] | list[tuple[bytes, bytes]],
) -> list[tuple[str, str]] | list[tuple[bytes, bytes]]:
    """
    Sanitize header items from ``http.client``.

    Historically, ``http.client`` may return values containing obsolete line folding
    (CRLF + leading whitespace). This is deprecated and can lead to header injection
    when upstream libraries consume values verbatim.

    This function unfolds obs-fold sequences into a single space and rejects any
    remaining CR/LF characters in header names or values.
    """

    sanitized: list[tuple[object, object]] = []

    for name, value in header_items:
        if isinstance(name, str) and ("\r" in name or "\n" in name):
            raise InvalidHeader(f"Invalid header name {name!r}")
        if isinstance(name, (bytes, bytearray, memoryview)):
            name_bytes = bytes(name)
            if b"\r" in name_bytes or b"\n" in name_bytes:
                raise InvalidHeader(f"Invalid header name {name_bytes!r}")

        if isinstance(value, str):
            unfolded = _HEADER_VALUE_OBS_FOLD_RE.sub(" ", value)
            if "\r" in unfolded or "\n" in unfolded:
                raise InvalidHeader(f"Invalid header value for {name!r}")
            sanitized.append((name, unfolded))
        elif isinstance(value, (bytes, bytearray, memoryview)):
            value_bytes = bytes(value)
            unfolded_bytes = re.sub(rb"(?:\r\n|\n)[ \t]+", b" ", value_bytes)
            if b"\r" in unfolded_bytes or b"\n" in unfolded_bytes:
                raise InvalidHeader(f"Invalid header value for {name!r}")
            sanitized.append((name, unfolded_bytes))
        else:
            sanitized.append((name, value))

    return sanitized  # type: ignore[return-value]


def is_response_to_head(response: httplib.HTTPResponse) -> bool:
    """
    Checks whether the request of a response has been a HEAD-request.

    :param http.client.HTTPResponse response:
        Response to check if the originating request
        used 'HEAD' as a method.
    """
    # FIXME: Can we do this somehow without accessing private httplib _method?
    method_str = response._method  # type: str  # type: ignore[attr-defined]
    return method_str.upper() == "HEAD"

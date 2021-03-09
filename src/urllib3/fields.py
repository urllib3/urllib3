import email.utils
import mimetypes
import re
from typing import (
    Callable,
    Dict,
    Iterable,
    Mapping,
    Match,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)

_TYPE_FIELD_VALUE = Union[str, bytes]
_TYPE_FIELD_VALUE_TUPLE = Union[
    _TYPE_FIELD_VALUE, Tuple[str, _TYPE_FIELD_VALUE], Tuple[str, _TYPE_FIELD_VALUE, str]
]


def guess_content_type(filename: str, default: str = "application/octet-stream") -> str:
    """
    Guess the "Content-Type" of a file.

    :param filename:
        The filename to guess the "Content-Type" of using :mod:`mimetypes`.
    :param default:
        If no "Content-Type" can be guessed, default to `default`.
    """
    if filename:
        return mimetypes.guess_type(filename)[0] or default
    return default


def format_header_param_rfc2231(name: str, value: Union[str, bytes]) -> str:
    """
    Helper function to format and quote a single header parameter using the
    strategy defined in RFC 2231.

    Particularly useful for header parameters which might contain
    non-ASCII values, like file names. This follows
    `RFC 2388 Section 4.4 <https://tools.ietf.org/html/rfc2388#section-4.4>`_.

    :param name:
        The name of the parameter, a string expected to be ASCII only.
    :param value:
        The value of the parameter, provided as ``bytes`` or `str``.
    :ret:
        An RFC-2231-formatted unicode string.
    """
    if isinstance(value, bytes):
        value = value.decode("utf-8")

    if not any(ch in value for ch in '"\\\r\n'):
        result = f'{name}="{value}"'
        try:
            result.encode("ascii")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        else:
            return result

    value = email.utils.encode_rfc2231(value, "utf-8")
    value = f"{name}*={value}"

    return value


_HTML5_REPLACEMENTS = {
    "\u0022": "%22",
    # Replace "\" with "\\".
    "\u005C": "\u005C\u005C",
}

# All control characters from 0x00 to 0x1F *except* 0x1B.
_HTML5_REPLACEMENTS.update(
    {chr(cc): f"%{cc:02X}" for cc in range(0x00, 0x1F + 1) if cc not in (0x1B,)}
)


def _replace_multiple(value: str, needles_and_replacements: Mapping[str, str]) -> str:
    def replacer(match: Match[str]) -> str:
        return needles_and_replacements[match.group(0)]

    pattern = re.compile(
        r"|".join([re.escape(needle) for needle in needles_and_replacements.keys()])
    )

    result = pattern.sub(replacer, value)

    return result


def format_header_param_html5(name: str, value: _TYPE_FIELD_VALUE) -> str:
    """
    Helper function to format and quote a single header parameter using the
    HTML5 strategy.

    Particularly useful for header parameters which might contain
    non-ASCII values, like file names. This follows the `HTML5 Working Draft
    Section 4.10.22.7`_ and matches the behavior of curl and modern browsers.

    .. _HTML5 Working Draft Section 4.10.22.7:
        https://w3c.github.io/html/sec-forms.html#multipart-form-data

    :param name:
        The name of the parameter, a string expected to be ASCII only.
    :param value:
        The value of the parameter, provided as ``bytes`` or `str``.
    :ret:
        A unicode string, stripped of troublesome characters.
    """
    if isinstance(value, bytes):
        value = value.decode("utf-8")

    value = _replace_multiple(value, _HTML5_REPLACEMENTS)

    return f'{name}="{value}"'


# For backwards-compatibility.
format_header_param = format_header_param_html5


class RequestField:
    """
    A data container for request body parameters.

    :param name:
        The name of this request field. Must be unicode.
    :param data:
        The data/value body.
    :param filename:
        An optional filename of the request field. Must be unicode.
    :param headers:
        An optional dict-like object of headers to initially use for the field.
    :param header_formatter:
        An optional callable that is used to encode and format the headers. By
        default, this is :func:`format_header_param_html5`.
    """

    def __init__(
        self,
        name: str,
        data: _TYPE_FIELD_VALUE,
        filename: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        header_formatter: Callable[
            [str, _TYPE_FIELD_VALUE], str
        ] = format_header_param_html5,
    ):
        self._name = name
        self._filename = filename
        self.data = data
        self.headers: Dict[str, Optional[str]] = {}
        if headers:
            self.headers = dict(headers)
        self.header_formatter = header_formatter

    @classmethod
    def from_tuples(
        cls,
        fieldname: str,
        value: _TYPE_FIELD_VALUE_TUPLE,
        header_formatter: Callable[
            [str, _TYPE_FIELD_VALUE], str
        ] = format_header_param_html5,
    ) -> "RequestField":
        """
        A :class:`~urllib3.fields.RequestField` factory from old-style tuple parameters.

        Supports constructing :class:`~urllib3.fields.RequestField` from
        parameter of key/value strings AND key/filetuple. A filetuple is a
        (filename, data, MIME type) tuple where the MIME type is optional.
        For example::

            'foo': 'bar',
            'fakefile': ('foofile.txt', 'contents of foofile'),
            'realfile': ('barfile.txt', open('realfile').read()),
            'typedfile': ('bazfile.bin', open('bazfile').read(), 'image/jpeg'),
            'nonamefile': 'contents of nonamefile field',

        Field names and filenames must be unicode.
        """
        filename: Optional[str]
        content_type: Optional[str]
        data: _TYPE_FIELD_VALUE

        if isinstance(value, tuple):
            if len(value) == 3:
                filename, data, content_type = cast(
                    Tuple[str, _TYPE_FIELD_VALUE, str], value
                )
            else:
                filename, data = cast(Tuple[str, _TYPE_FIELD_VALUE], value)
                content_type = guess_content_type(filename)
        else:
            filename = None
            content_type = None
            data = value

        request_param = cls(
            fieldname, data, filename=filename, header_formatter=header_formatter
        )
        request_param.make_multipart(content_type=content_type)

        return request_param

    def _render_part(self, name: str, value: _TYPE_FIELD_VALUE) -> str:
        """
        Overridable helper function to format a single header parameter. By
        default, this calls ``self.header_formatter``.

        :param name:
            The name of the parameter, a string expected to be ASCII only.
        :param value:
            The value of the parameter, provided as a unicode string.
        """

        return self.header_formatter(name, value)

    def _render_parts(
        self,
        header_parts: Union[
            Dict[str, Optional[_TYPE_FIELD_VALUE]],
            Sequence[Tuple[str, Optional[_TYPE_FIELD_VALUE]]],
        ],
    ) -> str:
        """
        Helper function to format and quote a single header.

        Useful for single headers that are composed of multiple items. E.g.,
        'Content-Disposition' fields.

        :param header_parts:
            A sequence of (k, v) tuples or a :class:`dict` of (k, v) to format
            as `k1="v1"; k2="v2"; ...`.
        """
        iterable: Iterable[Tuple[str, Optional[_TYPE_FIELD_VALUE]]]

        parts = []
        if isinstance(header_parts, dict):
            iterable = header_parts.items()
        else:
            iterable = header_parts

        for name, value in iterable:
            if value is not None:
                parts.append(self._render_part(name, value))

        return "; ".join(parts)

    def render_headers(self) -> str:
        """
        Renders the headers for this request field.
        """
        lines = []

        sort_keys = ["Content-Disposition", "Content-Type", "Content-Location"]
        for sort_key in sort_keys:
            if self.headers.get(sort_key, False):
                lines.append(f"{sort_key}: {self.headers[sort_key]}")

        for header_name, header_value in self.headers.items():
            if header_name not in sort_keys:
                if header_value:
                    lines.append(f"{header_name}: {header_value}")

        lines.append("\r\n")
        return "\r\n".join(lines)

    def make_multipart(
        self,
        content_disposition: Optional[str] = None,
        content_type: Optional[str] = None,
        content_location: Optional[str] = None,
    ) -> None:
        """
        Makes this request field into a multipart request field.

        This method overrides "Content-Disposition", "Content-Type" and
        "Content-Location" headers to the request parameter.

        :param content_disposition:
            The 'Content-Disposition' of the request body. Defaults to 'form-data'
        :param content_type:
            The 'Content-Type' of the request body.
        :param content_location:
            The 'Content-Location' of the request body.

        """
        content_disposition = (content_disposition or "form-data") + "; ".join(
            [
                "",
                self._render_parts(
                    (("name", self._name), ("filename", self._filename))
                ),
            ]
        )

        self.headers["Content-Disposition"] = content_disposition
        self.headers["Content-Type"] = content_type
        self.headers["Content-Location"] = content_location

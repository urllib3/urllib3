from __future__ import annotations

import binascii
import os
import typing

from .fields import _TYPE_FIELD_VALUE_TUPLE, RequestField

_TYPE_FIELDS_SEQUENCE = typing.Sequence[
    typing.Union[tuple[str, _TYPE_FIELD_VALUE_TUPLE], RequestField]
]
_TYPE_FIELDS = typing.Union[
    _TYPE_FIELDS_SEQUENCE,
    typing.Mapping[str, _TYPE_FIELD_VALUE_TUPLE],
]


def choose_boundary() -> str:
    """
    Our embarrassingly-simple replacement for mimetools.choose_boundary.
    """
    return binascii.hexlify(os.urandom(16)).decode()


def iter_field_objects(fields: _TYPE_FIELDS) -> typing.Iterable[RequestField]:
    """
    Iterate over fields.

    Supports list of (k, v) tuples and dicts, and lists of
    :class:`~urllib3.fields.RequestField`.

    """
    iterable: typing.Iterable[RequestField | tuple[str, _TYPE_FIELD_VALUE_TUPLE]]

    if isinstance(fields, typing.Mapping):
        iterable = fields.items()
    else:
        iterable = fields

    for field in iterable:
        if isinstance(field, RequestField):
            yield field
        else:
            yield RequestField.from_tuples(*field)


def encode_multipart_formdata(
    fields: _TYPE_FIELDS, boundary: str | None = None
) -> tuple[bytes, str]:
    """
    Encode a dictionary of ``fields`` using the multipart/form-data MIME format.

    :param fields:
        Dictionary of fields or list of (key, :class:`~urllib3.fields.RequestField`).
        Values are processed by :func:`urllib3.fields.RequestField.from_tuples`.

    :param boundary:
        If not specified, then a random boundary will be generated using
        :func:`urllib3.filepost.choose_boundary`.
    """
    # Lazy import to avoid a circular dependency with urllib3.multipart.encoder.
    from .multipart import MultipartEncoder

    encoder = MultipartEncoder(typing.cast(typing.Any, fields), boundary=boundary)
    return encoder.read(), encoder.content_type

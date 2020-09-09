from typing import Any, Generator, List, Mapping, Optional, Tuple, Union

from . import fields

Fields = Union[Mapping[str, str], List[Tuple[str]]]
Iterator = Generator[Tuple[str], None, None]

RequestField = fields.RequestField

writer: Any

def choose_boundary() -> str: ...
def iter_field_objects(fields: Fields) -> Iterator: ...
def iter_fields(fields: Fields) -> Iterator: ...
def encode_multipart_formdata(
    fields: Fields, boundary: Optional[str]
) -> Tuple[str]: ...

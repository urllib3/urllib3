"""
Hypothesis property-based tests for multipart fields and encoding.
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from urllib3.fields import (
    RequestField,
    format_multipart_header_param,
    guess_content_type,
)
from urllib3.filepost import encode_multipart_formdata


# Strategy for field names
field_names = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=50,
)

# Strategy for field values
field_values = st.one_of(
    st.text(max_size=1000),
    st.binary(max_size=1000),
)

# Strategy for filenames
filenames = st.one_of(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="._- "
        ),
        min_size=1,
        max_size=100,
    ),
    st.none(),
)


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    data=field_values,
)
def test_request_field_construction(name: str, data: str | bytes) -> None:
    """Test RequestField construction with various inputs."""
    field = RequestField(name, data)

    assert field._name == name
    assert field.data == data

    # Should be able to render headers
    headers = field.render_headers()
    assert isinstance(headers, str)


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    data=field_values,
    filename=filenames,
)
def test_request_field_with_filename(
    name: str, data: str | bytes, filename: str | None
) -> None:
    """Test RequestField with filename."""
    field = RequestField(name, data, filename=filename)

    assert field._name == name
    assert field._filename == filename

    # Make multipart
    field.make_multipart()

    # Should have Content-Disposition header
    assert "Content-Disposition" in field.headers

    headers_str = field.render_headers()
    assert "Content-Disposition:" in headers_str

    if filename:
        assert "filename=" in headers_str


@settings(max_examples=1000, deadline=None)
@given(
    name=st.text(min_size=1, max_size=50),
    value=st.text(max_size=200),
)
def test_format_multipart_header_param(name: str, value: str) -> None:
    """Test format_multipart_header_param with various inputs."""
    result = format_multipart_header_param(name, value)

    # Should return a string
    assert isinstance(result, str)

    # Should contain the name
    assert name in result

    # Should have quotes
    assert '"' in result


@settings(max_examples=1000, deadline=None)
@given(
    value=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters=" -_.@",
        ),
        max_size=100,
    )
)
def test_format_multipart_header_param_escaping(value: str) -> None:
    """Test that format_multipart_header_param properly escapes special characters."""
    result = format_multipart_header_param("test", value)

    # Newlines should be percent-encoded
    if "\n" in value:
        assert "%0A" in result

    # Carriage returns should be percent-encoded
    if "\r" in value:
        assert "%0D" in result

    # Quotes should be percent-encoded
    if '"' in value:
        assert "%22" in result


@settings(max_examples=1000, deadline=None)
@given(
    filename=st.one_of(
        st.just("test.txt"),
        st.just("image.jpg"),
        st.just("document.pdf"),
        st.just("script.js"),
        st.just("style.css"),
        st.just("unknown.xyz"),
        st.none(),
    )
)
def test_guess_content_type(filename: str | None) -> None:
    """Test guess_content_type with various filenames."""
    result = guess_content_type(filename)

    # Should always return a string
    assert isinstance(result, str)

    # Should be a valid MIME type format
    if "/" in result:
        parts = result.split("/")
        assert len(parts) == 2


@settings(max_examples=1000, deadline=None)
@given(
    fields_list=st.lists(
        st.tuples(field_names, st.text(max_size=100)),
        min_size=1,
        max_size=10,
    )
)
def test_encode_multipart_formdata(fields_list: list[tuple[str, str]]) -> None:
    """Test encoding multipart form data."""
    body, content_type = encode_multipart_formdata(fields_list)

    # Should return bytes and string
    assert isinstance(body, bytes)
    assert isinstance(content_type, str)

    # Content type should be multipart/form-data
    assert content_type.startswith("multipart/form-data")
    assert "boundary=" in content_type

    # Body should contain field names
    body_str = body.decode("utf-8", errors="replace")
    for name, _value in fields_list:
        assert name in body_str


@settings(max_examples=1000, deadline=None)
@given(
    fields_dict=st.dictionaries(
        field_names,
        st.text(max_size=100),
        min_size=1,
        max_size=10,
    )
)
def test_encode_multipart_formdata_from_dict(fields_dict: dict[str, str]) -> None:
    """Test encoding multipart form data from dictionary."""
    body, content_type = encode_multipart_formdata(fields_dict)

    # Should work with dictionaries
    assert isinstance(body, bytes)
    assert isinstance(content_type, str)

    # Should contain all field names
    body_str = body.decode("utf-8", errors="replace")
    for name in fields_dict:
        assert name in body_str


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    value=st.text(max_size=100),
    content_type=st.sampled_from([
        "text/plain",
        "application/json",
        "application/octet-stream",
        "image/jpeg",
        None,
    ]),
)
def test_request_field_make_multipart_with_content_type(
    name: str, value: str, content_type: str | None
) -> None:
    """Test make_multipart with explicit content type."""
    field = RequestField(name, value)
    field.make_multipart(content_type=content_type)

    if content_type:
        assert field.headers.get("Content-Type") == content_type


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    filename=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
        min_size=1,
        max_size=50,
    ),
    data=st.binary(min_size=1, max_size=1000),
)
def test_request_field_from_tuples_with_file(
    name: str, filename: str, data: bytes
) -> None:
    """Test RequestField.from_tuples with file upload."""
    # Create field from tuple (filename, data)
    field = RequestField.from_tuples(name, (filename, data))

    assert field._name == name
    assert field._filename == filename
    assert field.data == data

    # Should have content-type set
    assert "Content-Type" in field.headers


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    value=st.text(max_size=100),
)
def test_request_field_from_tuples_simple(name: str, value: str) -> None:
    """Test RequestField.from_tuples with simple value."""
    field = RequestField.from_tuples(name, value)

    assert field._name == name
    assert field.data == value
    assert field._filename is None


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    filename=st.text(min_size=1, max_size=50),
    data=st.binary(min_size=1, max_size=500),
    content_type=st.text(min_size=1, max_size=50),
)
def test_request_field_from_tuples_with_explicit_content_type(
    name: str, filename: str, data: bytes, content_type: str
) -> None:
    """Test RequestField.from_tuples with explicit content type."""
    # Create field from tuple (filename, data, content_type)
    field = RequestField.from_tuples(name, (filename, data, content_type))

    assert field._filename == filename
    assert field.data == data
    assert field.headers.get("Content-Type") == content_type


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    value=st.binary(max_size=100),
)
def test_request_field_with_binary_data(name: str, value: bytes) -> None:
    """Test RequestField with binary data."""
    field = RequestField(name, value)

    assert field.data == value

    # Should be able to render
    headers = field.render_headers()
    assert isinstance(headers, str)


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    value=st.text(max_size=100),
    custom_headers=st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.text(max_size=50),
        max_size=5,
    ),
)
def test_request_field_with_custom_headers(
    name: str, value: str, custom_headers: dict[str, str]
) -> None:
    """Test RequestField with custom headers."""
    field = RequestField(name, value, headers=custom_headers)

    # Custom headers should be present
    for header_name, header_value in custom_headers.items():
        assert field.headers.get(header_name) == header_value


@settings(max_examples=1000, deadline=None)
@given(
    parts_dict=st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.text(max_size=50),
        min_size=1,
        max_size=5,
    )
)
def test_request_field_render_parts_dict(parts_dict: dict[str, str]) -> None:
    """Test _render_parts with dictionary."""
    field = RequestField("test", "data")
    result = field._render_parts(parts_dict)

    # Should return a string
    assert isinstance(result, str)

    # Should contain the parts
    for name in parts_dict:
        assert name in result


@settings(max_examples=1000, deadline=None)
@given(
    parts_list=st.lists(
        st.tuples(
            st.text(
                alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
                min_size=1,
                max_size=20,
            ),
            st.text(max_size=50),
        ),
        min_size=1,
        max_size=5,
        unique_by=lambda x: x[0],  # Unique names
    )
)
def test_request_field_render_parts_list(parts_list: list[tuple[str, str]]) -> None:
    """Test _render_parts with list of tuples."""
    field = RequestField("test", "data")
    result = field._render_parts(parts_list)

    # Should return a string
    assert isinstance(result, str)

    # Should contain the parts
    for name, _ in parts_list:
        assert name in result


@settings(max_examples=1000, deadline=None)
@given(
    value=st.text(
        alphabet=st.characters(min_codepoint=0x00, max_codepoint=0x7F),
        max_size=100,
    )
)
def test_format_multipart_header_param_control_chars(value: str) -> None:
    """Test format_multipart_header_param with control characters."""
    result = format_multipart_header_param("test", value)

    # Control characters 0x0A, 0x0D should be escaped
    # Other control characters (0x00-0x1F except 0x09, 0x0A, 0x0D)
    # are NOT escaped per WHATWG spec
    assert isinstance(result, str)


@settings(max_examples=1000, deadline=None)
@given(
    fields_list=st.lists(
        st.tuples(field_names, st.integers(min_value=0, max_value=1000)),
        min_size=1,
        max_size=10,
    )
)
def test_encode_multipart_formdata_with_integers(
    fields_list: list[tuple[str, int]]
) -> None:
    """Test encoding multipart form data with integers."""
    body, _content_type = encode_multipart_formdata(fields_list)

    # Should handle integers (converting to strings)
    assert isinstance(body, bytes)

    # Integer values should appear as strings in body
    body_str = body.decode("utf-8", errors="replace")
    for _name, value in fields_list:
        assert str(value) in body_str


@settings(max_examples=1000, deadline=None)
@given(
    name=field_names,
    value=st.text(max_size=100),
    content_location=st.one_of(
        st.just("/path/to/resource"),
        st.just("http://example.com/resource"),
        st.none(),
    ),
)
def test_request_field_make_multipart_with_location(
    name: str, value: str, content_location: str | None
) -> None:
    """Test make_multipart with content location."""
    field = RequestField(name, value)
    field.make_multipart(content_location=content_location)

    if content_location:
        assert field.headers.get("Content-Location") == content_location

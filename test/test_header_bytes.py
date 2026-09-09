from __future__ import annotations

import gzip
import io

import pytest

from urllib3 import HTTPResponse
from urllib3._collections import HTTPHeaderDict
from urllib3.util.retry import Retry


class TestHTTPHeaderBytes:
    def test_single_value_preserves_octets(self) -> None:
        headers = HTTPHeaderDict()
        value = b"Sch\xf6nefeld/1.18.0"
        headers["User-Agent"] = value
        assert headers["user-agent"] == value
        assert headers.getlist("USER-AGENT") == [value]
        assert list(headers.items()) == [("User-Agent", value)]
        assert ("User-Agent", value) in headers.items()
        assert ("User-Agent", value.decode("latin-1")) not in headers.items()
        assert dict(headers) == {"User-Agent": value}
        assert headers != HTTPHeaderDict({"User-Agent": value.decode("latin-1")})

    @pytest.mark.parametrize("combine", [False, True])
    def test_multiple_values_and_copy(self, combine: bool) -> None:
        headers = HTTPHeaderDict({"Cookie": b"a=\xff"})
        headers.add("cookie", b"b=\x80", combine=combine)
        assert headers["COOKIE"] == b"a=\xff, b=\x80"
        expected = [b"a=\xff, b=\x80"] if combine else [b"a=\xff", b"b=\x80"]
        assert headers.getlist("cookie") == expected
        assert list(headers.itermerged()) == [("Cookie", b"a=\xff, b=\x80")]
        for copied in (headers.copy(), HTTPHeaderDict(headers)):
            assert copied == headers
            assert copied.getlist("cookie") == expected
            copied.add("Cookie", b"c=1")
            assert headers.getlist("cookie") == expected

    @pytest.mark.parametrize("first,second", [("text", b"bytes"), (b"bytes", "text")])
    @pytest.mark.parametrize("combine", [False, True])
    def test_mixed_values_fail_without_mutating_existing_header(
        self, first: str | bytes, second: str | bytes, combine: bool
    ) -> None:
        headers = HTTPHeaderDict({"X-Test": first})
        with pytest.raises(TypeError, match="str and bytes"):
            headers.add("x-test", second, combine=combine)
        assert headers["X-Test"] == first
        assert headers.getlist("X-Test") == [first]

    def test_mapping_operations_preserve_binary_and_text_fields(self) -> None:
        values: dict[str, str | bytes] = {"X-Binary": b"\xff", "X-Text": "text"}
        headers = HTTPHeaderDict(values)
        headers.extend([("X-Binary", b"\x80")], Extra=b"\xfe")
        assert headers.setdefault("Default", b"\xfd") == b"\xfd"
        assert headers.setdefault("Default", "ignored") == b"\xfd"
        headers.update({"X-Binary": b"replacement"})
        assert headers.pop("X-Binary") == b"replacement"
        assert headers["X-Text"] == "text"
        assert headers["Extra"] == b"\xfe"
        assert "b'\\xfe'" in repr(headers)
        headers |= {"Extra": b"next"}
        assert headers["Extra"] == b"\xfe, next"
        assert (headers | {"Another": b"value"})["Another"] == b"value"
        assert ({"Another": b"value"} | headers)["Extra"] == b"\xfe, next"

    def test_empty_binary_value_and_replacement(self) -> None:
        headers = HTTPHeaderDict({"X-Test": b""})
        assert headers["X-Test"] == b""
        headers.add("X-Test", b"next")
        assert headers["X-Test"] == b", next"
        headers["X-Test"] = "replacement"
        assert headers.get("X-Test") == "replacement"

    def test_response_decodes_binary_metadata_without_changing_header_values(
        self,
    ) -> None:
        body = gzip.compress(b"decoded body")
        headers = HTTPHeaderDict(
            {
                "Content-Encoding": b"gzip",
                "Content-Length": str(len(body)).encode("ascii"),
            }
        )
        response = HTTPResponse(body=io.BytesIO(body), headers=headers)
        assert response.data == b"decoded body"
        assert response.getheader("Content-Encoding") == "gzip"
        assert response.headers["Content-Encoding"] == b"gzip"
        assert response.getheader("Missing") is None
        assert response.getheader("Missing", "fallback") == "fallback"

    def test_binary_redirect_and_retry_metadata(self) -> None:
        response = HTTPResponse(
            status=302,
            headers=HTTPHeaderDict({"Location": b"/next", "Retry-After": b"10"}),
        )
        assert response.get_redirect_location() == "/next"
        assert Retry().get_retry_after(response) == 10

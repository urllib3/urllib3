# Stubs for requests.packages.urllib3.fields (Python 3.4)

from typing import Any, Callable, Mapping, Optional

def guess_content_type(filename: str, default: str) -> str: ...
def format_header_param_rfc2231(name: str, value: str) -> str: ...
def format_header_param_html5(name: str, value: str) -> str: ...
def format_header_param(name: str, value: str) -> str: ...

class RequestField:
    data: Any
    headers: Optional[Mapping[str, str]]
    def __init__(
        self,
        name: str,
        data: Any,
        filename: Optional[str],
        headers: Optional[Mapping[str, str]],
        header_formatter: Callable[[str, str], str],
    ) -> None: ...
    @classmethod
    def from_tuples(
        cls, fieldname: str, value: str, header_formatter: Callable[[str, str], str]
    ) -> RequestField: ...
    def render_headers(self) -> str: ...
    def make_multipart(
        self, content_disposition: str, content_type: str, content_location: str
    ) -> None: ...

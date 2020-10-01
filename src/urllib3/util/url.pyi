from typing import Any, List, Optional, Tuple, Union

from .. import exceptions

LocationParseError = exceptions.LocationParseError

url_attrs: List[str]

class Url:
    slots: Any
    def __new__(
        cls,
        scheme: Optional[str],
        auth: Optional[str],
        host: Optional[str],
        port: Optional[str],
        path: Optional[str],
        query: Optional[str],
        fragment: Optional[str],
    ) -> Url: ...
    @property
    def hostname(self) -> str: ...
    @property
    def request_uri(self) -> str: ...
    @property
    def netloc(self) -> str: ...
    @property
    def url(self) -> str: ...

def split_first(s: str, delims: str) -> Tuple[str, str, Optional[str]]: ...
def parse_url(url: str) -> Url: ...
def get_host(url: str) -> Union[str, Tuple[str]]: ...

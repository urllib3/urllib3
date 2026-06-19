from __future__ import annotations

from http.client import HTTPException

from urllib3.contrib.wasi.request import WasiRequest


class ResponseAlreadyTaken(HTTPException):
    def __init__(self, request: WasiRequest):
        self.request = request
        self.message = "WASI http response was already taken"
        super().__init__(self.message)


class ResponseStreamReadingError(HTTPException):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class ResourceClosedError(HTTPException):
    def __init__(self, resource_name: str):
        self.message = f"Resource {resource_name} is already closed"
        super().__init__(self.message)


class WasiErrorCode(HTTPException):
    def __init__(self, error: str):
        self.message = f"Request failed with wasi http error {error}"
        super().__init__(self.message)


class InvalidURL(HTTPException):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class UnknownWasiError(HTTPException):
    def __init__(self) -> None:
        super().__init__("Unknown WASI error occurred")

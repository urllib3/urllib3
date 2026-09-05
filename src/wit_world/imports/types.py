"""
This interface defines all of the types and methods for implementing
HTTP Requests and Responses, both incoming and outgoing, as well as
their headers, trailers, and bodies.
"""

from __future__ import annotations

import weakref
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum, Flag, auto
from types import TracebackType
from typing import Any, Generic, List, Optional, Protocol, Self, Tuple, TypeVar, Union

from ..imports import error, poll, streams
from ..types import Err, Ok, Result, Some


@dataclass
class Method_Get:
    pass


@dataclass
class Method_Head:
    pass


@dataclass
class Method_Post:
    pass


@dataclass
class Method_Put:
    pass


@dataclass
class Method_Delete:
    pass


@dataclass
class Method_Connect:
    pass


@dataclass
class Method_Options:
    pass


@dataclass
class Method_Trace:
    pass


@dataclass
class Method_Patch:
    pass


@dataclass
class Method_Other:
    value: str


Method = Union[
    Method_Get,
    Method_Head,
    Method_Post,
    Method_Put,
    Method_Delete,
    Method_Connect,
    Method_Options,
    Method_Trace,
    Method_Patch,
    Method_Other,
]
"""
This type corresponds to HTTP standard Methods.
"""


@dataclass
class Scheme_Http:
    pass


@dataclass
class Scheme_Https:
    pass


@dataclass
class Scheme_Other:
    value: str


Scheme = Union[Scheme_Http, Scheme_Https, Scheme_Other]
"""
This type corresponds to HTTP standard Related Schemes.
"""


@dataclass
class DnsErrorPayload:
    """
    Defines the case payload type for `DNS-error` above:
    """

    rcode: str | None
    info_code: int | None


@dataclass
class TlsAlertReceivedPayload:
    """
    Defines the case payload type for `TLS-alert-received` above:
    """

    alert_id: int | None
    alert_message: str | None


@dataclass
class FieldSizePayload:
    """
    Defines the case payload type for `HTTP-response-{header,trailer}-size` above:
    """

    field_name: str | None
    field_size: int | None


@dataclass
class ErrorCode_DnsTimeout:
    pass


@dataclass
class ErrorCode_DnsError:
    value: DnsErrorPayload


@dataclass
class ErrorCode_DestinationNotFound:
    pass


@dataclass
class ErrorCode_DestinationUnavailable:
    pass


@dataclass
class ErrorCode_DestinationIpProhibited:
    pass


@dataclass
class ErrorCode_DestinationIpUnroutable:
    pass


@dataclass
class ErrorCode_ConnectionRefused:
    pass


@dataclass
class ErrorCode_ConnectionTerminated:
    pass


@dataclass
class ErrorCode_ConnectionTimeout:
    pass


@dataclass
class ErrorCode_ConnectionReadTimeout:
    pass


@dataclass
class ErrorCode_ConnectionWriteTimeout:
    pass


@dataclass
class ErrorCode_ConnectionLimitReached:
    pass


@dataclass
class ErrorCode_TlsProtocolError:
    pass


@dataclass
class ErrorCode_TlsCertificateError:
    pass


@dataclass
class ErrorCode_TlsAlertReceived:
    value: TlsAlertReceivedPayload


@dataclass
class ErrorCode_HttpRequestDenied:
    pass


@dataclass
class ErrorCode_HttpRequestLengthRequired:
    pass


@dataclass
class ErrorCode_HttpRequestBodySize:
    value: int | None


@dataclass
class ErrorCode_HttpRequestMethodInvalid:
    pass


@dataclass
class ErrorCode_HttpRequestUriInvalid:
    pass


@dataclass
class ErrorCode_HttpRequestUriTooLong:
    pass


@dataclass
class ErrorCode_HttpRequestHeaderSectionSize:
    value: int | None


@dataclass
class ErrorCode_HttpRequestHeaderSize:
    value: FieldSizePayload | None


@dataclass
class ErrorCode_HttpRequestTrailerSectionSize:
    value: int | None


@dataclass
class ErrorCode_HttpRequestTrailerSize:
    value: FieldSizePayload


@dataclass
class ErrorCode_HttpResponseIncomplete:
    pass


@dataclass
class ErrorCode_HttpResponseHeaderSectionSize:
    value: int | None


@dataclass
class ErrorCode_HttpResponseHeaderSize:
    value: FieldSizePayload


@dataclass
class ErrorCode_HttpResponseBodySize:
    value: int | None


@dataclass
class ErrorCode_HttpResponseTrailerSectionSize:
    value: int | None


@dataclass
class ErrorCode_HttpResponseTrailerSize:
    value: FieldSizePayload


@dataclass
class ErrorCode_HttpResponseTransferCoding:
    value: str | None


@dataclass
class ErrorCode_HttpResponseContentCoding:
    value: str | None


@dataclass
class ErrorCode_HttpResponseTimeout:
    pass


@dataclass
class ErrorCode_HttpUpgradeFailed:
    pass


@dataclass
class ErrorCode_HttpProtocolError:
    pass


@dataclass
class ErrorCode_LoopDetected:
    pass


@dataclass
class ErrorCode_ConfigurationError:
    pass


@dataclass
class ErrorCode_InternalError:
    value: str | None


ErrorCode = Union[
    ErrorCode_DnsTimeout,
    ErrorCode_DnsError,
    ErrorCode_DestinationNotFound,
    ErrorCode_DestinationUnavailable,
    ErrorCode_DestinationIpProhibited,
    ErrorCode_DestinationIpUnroutable,
    ErrorCode_ConnectionRefused,
    ErrorCode_ConnectionTerminated,
    ErrorCode_ConnectionTimeout,
    ErrorCode_ConnectionReadTimeout,
    ErrorCode_ConnectionWriteTimeout,
    ErrorCode_ConnectionLimitReached,
    ErrorCode_TlsProtocolError,
    ErrorCode_TlsCertificateError,
    ErrorCode_TlsAlertReceived,
    ErrorCode_HttpRequestDenied,
    ErrorCode_HttpRequestLengthRequired,
    ErrorCode_HttpRequestBodySize,
    ErrorCode_HttpRequestMethodInvalid,
    ErrorCode_HttpRequestUriInvalid,
    ErrorCode_HttpRequestUriTooLong,
    ErrorCode_HttpRequestHeaderSectionSize,
    ErrorCode_HttpRequestHeaderSize,
    ErrorCode_HttpRequestTrailerSectionSize,
    ErrorCode_HttpRequestTrailerSize,
    ErrorCode_HttpResponseIncomplete,
    ErrorCode_HttpResponseHeaderSectionSize,
    ErrorCode_HttpResponseHeaderSize,
    ErrorCode_HttpResponseBodySize,
    ErrorCode_HttpResponseTrailerSectionSize,
    ErrorCode_HttpResponseTrailerSize,
    ErrorCode_HttpResponseTransferCoding,
    ErrorCode_HttpResponseContentCoding,
    ErrorCode_HttpResponseTimeout,
    ErrorCode_HttpUpgradeFailed,
    ErrorCode_HttpProtocolError,
    ErrorCode_LoopDetected,
    ErrorCode_ConfigurationError,
    ErrorCode_InternalError,
]
"""
These cases are inspired by the IANA HTTP Proxy Error Types:
  https://www.iana.org/assignments/http-proxy-status/http-proxy-status.xhtml#table-http-proxy-error-types
"""


@dataclass
class HeaderError_InvalidSyntax:
    pass


@dataclass
class HeaderError_Forbidden:
    pass


@dataclass
class HeaderError_Immutable:
    pass


HeaderError = Union[
    HeaderError_InvalidSyntax, HeaderError_Forbidden, HeaderError_Immutable
]
"""
This type enumerates the different kinds of errors that may occur when
setting or appending to a `fields` resource.
"""


class Fields:
    """
    This following block defines the `fields` resource which corresponds to
    HTTP standard Fields. Fields are a common representation used for both
    Headers and Trailers.

    A `fields` may be mutable or immutable. A `fields` created using the
    constructor, `from-list`, or `clone` will be mutable, but a `fields`
    resource given by other means (including, but not limited to,
    `incoming-request.headers`, `outgoing-request.headers`) might be be
    immutable. In an immutable fields, the `set`, `append`, and `delete`
    operations will fail with `header-error.immutable`.
    """

    def __init__(self) -> None:
        """
        Construct an empty HTTP Fields.

        The resulting `fields` is mutable.
        """
        raise NotImplementedError

    @classmethod
    def from_list(cls, entries: list[tuple[str, bytes]]) -> Self:
        """
        Construct an HTTP Fields.

        The resulting `fields` is mutable.

        The list represents each key-value pair in the Fields. Keys
        which have multiple values are represented by multiple entries in this
        list with the same key.

        The tuple is a pair of the field key, represented as a string, and
        Value, represented as a list of bytes. In a valid Fields, all keys
        and values are valid UTF-8 strings. However, values are not always
        well-formed, so they are represented as a raw list of bytes.

        An error result will be returned if any header or value was
        syntactically invalid, or if a header was forbidden.

        Raises: `wit_world.types.Err(wit_world.imports.types.HeaderError)`
        """
        raise NotImplementedError

    def get(self, name: str) -> list[bytes]:
        """
        Get all of the values corresponding to a key. If the key is not present
        in this `fields`, an empty list is returned. However, if the key is
        present but empty, this is represented by a list with one or more
        empty field-values present.
        """
        raise NotImplementedError

    def has(self, name: str) -> bool:
        """
        Returns `true` when the key is present in this `fields`. If the key is
        syntactically invalid, `false` is returned.
        """
        raise NotImplementedError

    def set(self, name: str, value: list[bytes]) -> None:
        """
        Set all of the values for a key. Clears any existing values for that
        key, if they have been set.

        Fails with `header-error.immutable` if the `fields` are immutable.

        Raises: `wit_world.types.Err(wit_world.imports.types.HeaderError)`
        """
        raise NotImplementedError

    def delete(self, name: str) -> None:
        """
        Delete all values for a key. Does nothing if no values for the key
        exist.

        Fails with `header-error.immutable` if the `fields` are immutable.

        Raises: `wit_world.types.Err(wit_world.imports.types.HeaderError)`
        """
        raise NotImplementedError

    def append(self, name: str, value: bytes) -> None:
        """
        Append a value for a key. Does not change or delete any existing
        values for that key.

        Fails with `header-error.immutable` if the `fields` are immutable.

        Raises: `wit_world.types.Err(wit_world.imports.types.HeaderError)`
        """
        raise NotImplementedError

    def entries(self) -> list[tuple[str, bytes]]:
        """
        Retrieve the full set of keys and values in the Fields. Like the
        constructor, the list represents each key-value pair.

        The outer list represents each key-value pair in the Fields. Keys
        which have multiple values are represented by multiple entries in this
        list with the same key.
        """
        raise NotImplementedError

    def clone(self) -> Self:
        """
        Make a deep copy of the Fields. Equivelant in behavior to calling the
        `fields` constructor on the return value of `entries`. The resulting
        `fields` is mutable.
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class FutureTrailers:
    """
    Represents a future which may eventaully return trailers, or an error.

    In the case that the incoming HTTP Request or Response did not have any
    trailers, this future will resolve to the empty set of trailers once the
    complete Request or Response body has been received.
    """

    def subscribe(self) -> poll.Pollable:
        """
        Returns a pollable which becomes ready when either the trailers have
        been received, or an error has occured. When this pollable is ready,
        the `get` method will return `some`.
        """
        raise NotImplementedError

    def get(self) -> Result[Result[Fields | None, ErrorCode], None] | None:
        """
        Returns the contents of the trailers, or an error which occured,
        once the future is ready.

        The outer `option` represents future readiness. Users can wait on this
        `option` to become `some` using the `subscribe` method.

        The outer `result` is used to retrieve the trailers or error at most
        once. It will be success on the first call in which the outer option
        is `some`, and error on subsequent calls.

        The inner `result` represents that either the HTTP Request or Response
        body, as well as any trailers, were received successfully, or that an
        error occured receiving them. The optional `trailers` indicates whether
        or not trailers were present in the body.

        When some `trailers` are returned by this method, the `trailers`
        resource is immutable, and a child. Use of the `set`, `append`, or
        `delete` methods will return an error, and the resource must be
        dropped before the parent `future-trailers` is dropped.
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class IncomingBody:
    """
    Represents an incoming HTTP Request or Response's Body.

    A body has both its contents - a stream of bytes - and a (possibly
    empty) set of trailers, indicating that the full contents of the
    body have been received. This resource represents the contents as
    an `input-stream` and the delivery of trailers as a `future-trailers`,
    and ensures that the user of this interface may only be consuming either
    the body contents or waiting on trailers at any given time.
    """

    def stream(self) -> streams.InputStream:
        """
        Returns the contents of the body, as a stream of bytes.

        Returns success on first call: the stream representing the contents
        can be retrieved at most once. Subsequent calls will return error.

        The returned `input-stream` resource is a child: it must be dropped
        before the parent `incoming-body` is dropped, or consumed by
        `incoming-body.finish`.

        This invariant ensures that the implementation can determine whether
        the user is consuming the contents of the body, waiting on the
        `future-trailers` to be ready, or neither. This allows for network
        backpressure is to be applied when the user is consuming the body,
        and for that backpressure to not inhibit delivery of the trailers if
        the user does not read the entire body.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    @classmethod
    def finish(cls, this: Self) -> FutureTrailers:
        """
        Takes ownership of `incoming-body`, and returns a `future-trailers`.
        This function will trap if the `input-stream` child is still alive.
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class IncomingRequest:
    """
    Represents an incoming HTTP Request.
    """

    def method(self) -> Method:
        """
        Returns the method of the incoming request.
        """
        raise NotImplementedError

    def path_with_query(self) -> str | None:
        """
        Returns the path with query parameters from the request, as a string.
        """
        raise NotImplementedError

    def scheme(self) -> Scheme | None:
        """
        Returns the protocol scheme from the request.
        """
        raise NotImplementedError

    def authority(self) -> str | None:
        """
        Returns the authority from the request, if it was present.
        """
        raise NotImplementedError

    def headers(self) -> Fields:
        """
        Get the `headers` associated with the request.

        The returned `headers` resource is immutable: `set`, `append`, and
        `delete` operations will fail with `header-error.immutable`.

        The `headers` returned are a child resource: it must be dropped before
        the parent `incoming-request` is dropped. Dropping this
        `incoming-request` before all children are dropped will trap.
        """
        raise NotImplementedError

    def consume(self) -> IncomingBody:
        """
        Gives the `incoming-body` associated with this request. Will only
        return success at most once, and subsequent calls will return error.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class OutgoingBody:
    """
    Represents an outgoing HTTP Request or Response's Body.

    A body has both its contents - a stream of bytes - and a (possibly
    empty) set of trailers, inducating the full contents of the body
    have been sent. This resource represents the contents as an
    `output-stream` child resource, and the completion of the body (with
    optional trailers) with a static function that consumes the
    `outgoing-body` resource, and ensures that the user of this interface
    may not write to the body contents after the body has been finished.

    If the user code drops this resource, as opposed to calling the static
    method `finish`, the implementation should treat the body as incomplete,
    and that an error has occured. The implementation should propogate this
    error to the HTTP protocol by whatever means it has available,
    including: corrupting the body on the wire, aborting the associated
    Request, or sending a late status code for the Response.
    """

    def write(self) -> streams.OutputStream:
        """
        Returns a stream for writing the body contents.

        The returned `output-stream` is a child resource: it must be dropped
        before the parent `outgoing-body` resource is dropped (or finished),
        otherwise the `outgoing-body` drop or `finish` will trap.

        Returns success on the first call: the `output-stream` resource for
        this `outgoing-body` may be retrieved at most once. Subsequent calls
        will return error.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    @classmethod
    def finish(cls, this: Self, trailers: Fields | None) -> None:
        """
        Finalize an outgoing body, optionally providing trailers. This must be
        called to signal that the response is complete. If the `outgoing-body`
        is dropped without calling `outgoing-body.finalize`, the implementation
        should treat the body as corrupted.

        Fails if the body's `outgoing-request` or `outgoing-response` was
        constructed with a Content-Length header, and the contents written
        to the body (via `write`) does not match the value given in the
        Content-Length.

        Raises: `wit_world.types.Err(wit_world.imports.types.ErrorCode)`
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class OutgoingRequest:
    """
    Represents an outgoing HTTP Request.
    """

    def __init__(self, headers: Fields) -> None:
        """
        Construct a new `outgoing-request` with a default `method` of `GET`, and
        `none` values for `path-with-query`, `scheme`, and `authority`.

        * `headers` is the HTTP Headers for the Request.

        It is possible to construct, or manipulate with the accessor functions
        below, an `outgoing-request` with an invalid combination of `scheme`
        and `authority`, or `headers` which are not permitted to be sent.
        It is the obligation of the `outgoing-handler.handle` implementation
        to reject invalid constructions of `outgoing-request`.
        """
        raise NotImplementedError

    def body(self) -> OutgoingBody:
        """
        Returns the resource corresponding to the outgoing Body for this
        Request.

        Returns success on the first call: the `outgoing-body` resource for
        this `outgoing-request` can be retrieved at most once. Subsequent
        calls will return error.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def method(self) -> Method:
        """
        Get the Method for the Request.
        """
        raise NotImplementedError

    def set_method(self, method: Method) -> None:
        """
        Set the Method for the Request. Fails if the string present in a
        `method.other` argument is not a syntactically valid method.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def path_with_query(self) -> str | None:
        """
        Get the combination of the HTTP Path and Query for the Request.
        When `none`, this represents an empty Path and empty Query.
        """
        raise NotImplementedError

    def set_path_with_query(self, path_with_query: str | None) -> None:
        """
        Set the combination of the HTTP Path and Query for the Request.
        When `none`, this represents an empty Path and empty Query. Fails is the
        string given is not a syntactically valid path and query uri component.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def scheme(self) -> Scheme | None:
        """
        Get the HTTP Related Scheme for the Request. When `none`, the
        implementation may choose an appropriate default scheme.
        """
        raise NotImplementedError

    def set_scheme(self, scheme: Scheme | None) -> None:
        """
        Set the HTTP Related Scheme for the Request. When `none`, the
        implementation may choose an appropriate default scheme. Fails if the
        string given is not a syntactically valid uri scheme.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def authority(self) -> str | None:
        """
        Get the HTTP Authority for the Request. A value of `none` may be used
        with Related Schemes which do not require an Authority. The HTTP and
        HTTPS schemes always require an authority.
        """
        raise NotImplementedError

    def set_authority(self, authority: str | None) -> None:
        """
        Set the HTTP Authority for the Request. A value of `none` may be used
        with Related Schemes which do not require an Authority. The HTTP and
        HTTPS schemes always require an authority. Fails if the string given is
        not a syntactically valid uri authority.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def headers(self) -> Fields:
        """
        Get the headers associated with the Request.

        The returned `headers` resource is immutable: `set`, `append`, and
        `delete` operations will fail with `header-error.immutable`.

        This headers resource is a child: it must be dropped before the parent
        `outgoing-request` is dropped, or its ownership is transfered to
        another component by e.g. `outgoing-handler.handle`.
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class RequestOptions:
    """
    Parameters for making an HTTP Request. Each of these parameters is
    currently an optional timeout applicable to the transport layer of the
    HTTP protocol.

    These timeouts are separate from any the user may use to bound a
    blocking call to `wasi:io/poll.poll`.
    """

    def __init__(self) -> None:
        """
        Construct a default `request-options` value.
        """
        raise NotImplementedError

    def connect_timeout(self) -> int | None:
        """
        The timeout for the initial connect to the HTTP Server.
        """
        raise NotImplementedError

    def set_connect_timeout(self, duration: int | None) -> None:
        """
        Set the timeout for the initial connect to the HTTP Server. An error
        return value indicates that this timeout is not supported.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def first_byte_timeout(self) -> int | None:
        """
        The timeout for receiving the first byte of the Response body.
        """
        raise NotImplementedError

    def set_first_byte_timeout(self, duration: int | None) -> None:
        """
        Set the timeout for receiving the first byte of the Response body. An
        error return value indicates that this timeout is not supported.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def between_bytes_timeout(self) -> int | None:
        """
        The timeout for receiving subsequent chunks of bytes in the Response
        body stream.
        """
        raise NotImplementedError

    def set_between_bytes_timeout(self, duration: int | None) -> None:
        """
        Set the timeout for receiving subsequent chunks of bytes in the Response
        body stream. An error return value indicates that this timeout is not
        supported.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class OutgoingResponse:
    """
    Represents an outgoing HTTP Response.
    """

    def __init__(self, headers: Fields) -> None:
        """
        Construct an `outgoing-response`, with a default `status-code` of `200`.
        If a different `status-code` is needed, it must be set via the
        `set-status-code` method.

        * `headers` is the HTTP Headers for the Response.
        """
        raise NotImplementedError

    def status_code(self) -> int:
        """
        Get the HTTP Status Code for the Response.
        """
        raise NotImplementedError

    def set_status_code(self, status_code: int) -> None:
        """
        Set the HTTP Status Code for the Response. Fails if the status-code
        given is not a valid http status code.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def headers(self) -> Fields:
        """
        Get the headers associated with the Request.

        The returned `headers` resource is immutable: `set`, `append`, and
        `delete` operations will fail with `header-error.immutable`.

        This headers resource is a child: it must be dropped before the parent
        `outgoing-request` is dropped, or its ownership is transfered to
        another component by e.g. `outgoing-handler.handle`.
        """
        raise NotImplementedError

    def body(self) -> OutgoingBody:
        """
        Returns the resource corresponding to the outgoing Body for this Response.

        Returns success on the first call: the `outgoing-body` resource for
        this `outgoing-response` can be retrieved at most once. Subsequent
        calls will return error.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class ResponseOutparam:
    """
    Represents the ability to send an HTTP Response.

    This resource is used by the `wasi:http/incoming-handler` interface to
    allow a Response to be sent corresponding to the Request provided as the
    other argument to `incoming-handler.handle`.
    """

    @classmethod
    def set(cls, param: Self, response: Result[OutgoingResponse, ErrorCode]) -> None:
        """
        Set the value of the `response-outparam` to either send a response,
        or indicate an error.

        This method consumes the `response-outparam` to ensure that it is
        called at most once. If it is never called, the implementation
        will respond with an error.

        The user may provide an `error` to `response` to allow the
        implementation determine how to respond with an HTTP error response.
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class IncomingResponse:
    """
    Represents an incoming HTTP Response.
    """

    def status(self) -> int:
        """
        Returns the status code from the incoming response.
        """
        raise NotImplementedError

    def headers(self) -> Fields:
        """
        Returns the headers from the incoming response.

        The returned `headers` resource is immutable: `set`, `append`, and
        `delete` operations will fail with `header-error.immutable`.

        This headers resource is a child: it must be dropped before the parent
        `incoming-response` is dropped.
        """
        raise NotImplementedError

    def consume(self) -> IncomingBody:
        """
        Returns the incoming body. May be called at most once. Returns error
        if called additional times.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


class FutureIncomingResponse:
    """
    Represents a future which may eventaully return an incoming HTTP
    Response, or an error.

    This resource is returned by the `wasi:http/outgoing-handler` interface to
    provide the HTTP Response corresponding to the sent Request.
    """

    def subscribe(self) -> poll.Pollable:
        """
        Returns a pollable which becomes ready when either the Response has
        been received, or an error has occured. When this pollable is ready,
        the `get` method will return `some`.
        """
        raise NotImplementedError

    def get(self) -> Result[Result[IncomingResponse, ErrorCode], None] | None:
        """
        Returns the incoming HTTP Response, or an error, once one is ready.

        The outer `option` represents future readiness. Users can wait on this
        `option` to become `some` using the `subscribe` method.

        The outer `result` is used to retrieve the response or error at most
        once. It will be success on the first call in which the outer option
        is `some`, and error on subsequent calls.

        The inner `result` represents that either the incoming HTTP Response
        status and headers have recieved successfully, or that an error
        occured. Errors may also occur while consuming the response body,
        but those will be reported by the `incoming-body` and its
        `output-stream` child.
        """
        raise NotImplementedError

    def __enter__(self) -> Self:
        """Returns self"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """
        Release this resource.
        """
        raise NotImplementedError


def http_error_code(err: error.Error) -> ErrorCode | None:
    """
    Attempts to extract a http-related `error` from the wasi:io `error`
    provided.

    Stream operations which return
    `wasi:io/stream/stream-error::last-operation-failed` have a payload of
    type `wasi:io/error/error` with more information about the operation
    that failed. This payload can be passed through to this function to see
    if there's http-related information about the error to return.

    Note that this function is fallible because not all io-errors are
    http-related errors.
    """
    raise NotImplementedError

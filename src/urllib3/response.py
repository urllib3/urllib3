import io
import json as _json
import logging
import zlib
from contextlib import contextmanager
from http.client import HTTPMessage as _HttplibHTTPMessage
from http.client import HTTPResponse as _HttplibHTTPResponse
from socket import timeout as SocketTimeout
from typing import (
    TYPE_CHECKING,
    Any,
    Generator,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
    Union,
)

try:
    try:
        import brotlicffi as brotli  # type: ignore[import]
    except ImportError:
        import brotli  # type: ignore[import]
except ImportError:
    brotli = None

from ._collections import HTTPHeaderDict
from .connection import _TYPE_BODY, BaseSSLError, HTTPConnection, HTTPException
from .exceptions import (
    BodyNotHttplibCompatible,
    DecodeError,
    HTTPError,
    IncompleteRead,
    InvalidChunkLength,
    InvalidHeader,
    ProtocolError,
    ReadTimeoutError,
    ResponseNotChunked,
    SSLError,
)
from .util.response import is_fp_closed, is_response_to_head
from .util.retry import Retry

if TYPE_CHECKING:
    from typing_extensions import Literal

    from .connectionpool import HTTPConnectionPool

log = logging.getLogger(__name__)


class ContentDecoder:
    def decompress(self, data: bytes) -> bytes:
        raise NotImplementedError()

    def flush(self) -> bytes:
        raise NotImplementedError()


class DeflateDecoder(ContentDecoder):
    def __init__(self) -> None:
        self._first_try = True
        self._data = b""
        self._obj = zlib.decompressobj()

    def decompress(self, data: bytes) -> bytes:
        if not data:
            return data

        if not self._first_try:
            return self._obj.decompress(data)

        self._data += data
        try:
            decompressed = self._obj.decompress(data)
            if decompressed:
                self._first_try = False
                self._data = None  # type: ignore[assignment]
            return decompressed
        except zlib.error:
            self._first_try = False
            self._obj = zlib.decompressobj(-zlib.MAX_WBITS)
            try:
                return self.decompress(self._data)
            finally:
                self._data = None  # type: ignore[assignment]

    def flush(self) -> bytes:
        return self._obj.flush()


class GzipDecoderState:

    FIRST_MEMBER = 0
    OTHER_MEMBERS = 1
    SWALLOW_DATA = 2


class GzipDecoder(ContentDecoder):
    def __init__(self) -> None:
        self._obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self._state = GzipDecoderState.FIRST_MEMBER

    def decompress(self, data: bytes) -> bytes:
        ret = bytearray()
        if self._state == GzipDecoderState.SWALLOW_DATA or not data:
            return bytes(ret)
        while True:
            try:
                ret += self._obj.decompress(data)
            except zlib.error:
                previous_state = self._state
                # Ignore data after the first error
                self._state = GzipDecoderState.SWALLOW_DATA
                if previous_state == GzipDecoderState.OTHER_MEMBERS:
                    # Allow trailing garbage acceptable in other gzip clients
                    return bytes(ret)
                raise
            data = self._obj.unused_data
            if not data:
                return bytes(ret)
            self._state = GzipDecoderState.OTHER_MEMBERS
            self._obj = zlib.decompressobj(16 + zlib.MAX_WBITS)

    def flush(self) -> bytes:
        return self._obj.flush()


if brotli is not None:

    class BrotliDecoder(ContentDecoder):
        # Supports both 'brotlipy' and 'Brotli' packages
        # since they share an import name. The top branches
        # are for 'brotlipy' and bottom branches for 'Brotli'
        def __init__(self) -> None:
            self._obj = brotli.Decompressor()
            if hasattr(self._obj, "decompress"):
                setattr(self, "decompress", self._obj.decompress)
            else:
                setattr(self, "decompress", self._obj.process)

        def flush(self) -> bytes:
            if hasattr(self._obj, "flush"):
                return self._obj.flush()  # type: ignore[no-any-return]
            return b""


class MultiDecoder(ContentDecoder):
    """
    From RFC7231:
        If one or more encodings have been applied to a representation, the
        sender that applied the encodings MUST generate a Content-Encoding
        header field that lists the content codings in the order in which
        they were applied.
    """

    def __init__(self, modes: str) -> None:
        self._decoders = [_get_decoder(m.strip()) for m in modes.split(",")]

    def flush(self) -> bytes:
        return self._decoders[0].flush()

    def decompress(self, data: bytes) -> bytes:
        for d in reversed(self._decoders):
            data = d.decompress(data)
        return data


def _get_decoder(mode: str) -> ContentDecoder:
    if "," in mode:
        return MultiDecoder(mode)

    if mode == "gzip":
        return GzipDecoder()

    if brotli is not None and mode == "br":
        return BrotliDecoder()

    return DeflateDecoder()


class BaseHTTPResponse(io.IOBase):
    CONTENT_DECODERS = ["gzip", "deflate"]
    if brotli is not None:
        CONTENT_DECODERS += ["br"]
    REDIRECT_STATUSES = [301, 302, 303, 307, 308]

    DECODER_ERROR_CLASSES: Tuple[Type[Exception], ...] = (IOError, zlib.error)
    if brotli is not None:
        DECODER_ERROR_CLASSES += (brotli.error,)

    def __init__(
        self,
        *,
        headers: Optional[Union[Mapping[str, str], Mapping[bytes, bytes]]] = None,
        status: int,
        version: int,
        reason: Optional[str],
        decode_content: bool,
        request_url: Optional[str],
        retries: Optional[Retry] = None,
    ) -> None:
        if isinstance(headers, HTTPHeaderDict):
            self.headers = headers
        else:
            self.headers = HTTPHeaderDict(headers)  # type: ignore[arg-type]
        self.status = status
        self.version = version
        self.reason = reason
        self.decode_content = decode_content
        self.request_url: Optional[str]
        self.retries = retries

        self.chunked = False
        tr_enc = self.headers.get("transfer-encoding", "").lower()
        # Don't incur the penalty of creating a list and then discarding it
        encodings = (enc.strip() for enc in tr_enc.split(","))
        if "chunked" in encodings:
            self.chunked = True

        self._decoder: Optional[ContentDecoder] = None

    def get_redirect_location(self) -> Union[Optional[str], "Literal[False]"]:
        """
        Should we redirect and where to?

        :returns: Truthy redirect location string if we got a redirect status
            code and valid location. ``None`` if redirect status and no
            location. ``False`` if not a redirect status code.
        """
        if self.status in self.REDIRECT_STATUSES:
            return self.headers.get("location")
        return False

    @property
    def data(self) -> bytes:
        raise NotImplementedError()

    def json(self) -> Any:
        """
        Parses the body of the HTTP response as JSON.

        To use a custom JSON decoder pass the result of :attr:`HTTPResponse.data` to the decoder.

        This method can raise either `UnicodeDecodeError` or `json.JSONDecodeError`.

        Read more :ref:`here <json>`.
        """
        data = self.data.decode("utf-8")
        return _json.loads(data)

    @property
    def url(self) -> Optional[str]:
        raise NotImplementedError()

    @property
    def closed(self) -> bool:
        raise NotImplementedError()

    @property
    def connection(self) -> Optional[HTTPConnection]:
        raise NotImplementedError()

    def stream(
        self, amt: Optional[int] = 2 ** 16, decode_content: Optional[bool] = None
    ) -> Iterator[bytes]:
        raise NotImplementedError()

    def read(
        self,
        amt: Optional[int] = None,
        decode_content: Optional[bool] = None,
        cache_content: bool = False,
    ) -> bytes:
        raise NotImplementedError()

    def read_chunked(
        self,
        amt: Optional[int] = None,
        decode_content: Optional[bool] = None,
    ) -> Iterator[bytes]:
        raise NotImplementedError()

    def release_conn(self) -> None:
        raise NotImplementedError()

    def drain_conn(self) -> None:
        raise NotImplementedError()

    def close(self) -> None:
        raise NotImplementedError()

    def _init_decoder(self) -> None:
        """
        Set-up the _decoder attribute if necessary.
        """
        # Note: content-encoding value should be case-insensitive, per RFC 7230
        # Section 3.2
        content_encoding = self.headers.get("content-encoding", "").lower()
        if self._decoder is None:
            if content_encoding in self.CONTENT_DECODERS:
                self._decoder = _get_decoder(content_encoding)
            elif "," in content_encoding:
                encodings = [
                    e.strip()
                    for e in content_encoding.split(",")
                    if e.strip() in self.CONTENT_DECODERS
                ]
                if encodings:
                    self._decoder = _get_decoder(content_encoding)

    def _decode(
        self, data: bytes, decode_content: Optional[bool], flush_decoder: bool
    ) -> bytes:
        """
        Decode the data passed in and potentially flush the decoder.
        """
        if not decode_content:
            return data

        try:
            if self._decoder:
                data = self._decoder.decompress(data)
        except self.DECODER_ERROR_CLASSES as e:
            content_encoding = self.headers.get("content-encoding", "").lower()
            raise DecodeError(
                "Received response with content-encoding: %s, but "
                "failed to decode it." % content_encoding,
                e,
            ) from e
        if flush_decoder:
            data += self._flush_decoder()

        return data

    def _flush_decoder(self) -> bytes:
        """
        Flushes the decoder. Should only be called if the decoder is actually
        being used.
        """
        if self._decoder:
            return self._decoder.decompress(b"") + self._decoder.flush()
        return b""

    # Compatibility methods for `io` module
    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray) -> int:
        temp = self.read(len(b))
        if len(temp) == 0:
            return 0
        else:
            b[: len(temp)] = temp
            return len(temp)

    # Compatibility methods for http.client.HTTPResponse
    def getheaders(self) -> List[Tuple[str, str]]:
        return list(self.headers.items())

    def getheader(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self.headers.get(name, default)

    # Compatibility method for http.cookiejar
    def info(self) -> HTTPHeaderDict:
        return self.headers

    def geturl(self) -> Optional[Union[str, "Literal[False]"]]:
        return self.url


class HTTPResponse(BaseHTTPResponse):
    """
    HTTP Response container.

    Backwards-compatible with :class:`http.client.HTTPResponse` but the response ``body`` is
    loaded and decoded on-demand when the ``data`` property is accessed.  This
    class is also compatible with the Python standard library's :mod:`io`
    module, and can hence be treated as a readable object in the context of that
    framework.

    Extra parameters for behaviour not present in :class:`http.client.HTTPResponse`:

    :param preload_content:
        If True, the response's body will be preloaded during construction.

    :param decode_content:
        If True, will attempt to decode the body based on the
        'content-encoding' header.

    :param original_response:
        When this HTTPResponse wrapper is generated from an :class:`http.client.HTTPResponse`
        object, it's convenient to include the original for debug purposes. It's
        otherwise unused.

    :param retries:
        The retries contains the last :class:`~urllib3.util.retry.Retry` that
        was used during the request.

    :param enforce_content_length:
        Enforce content length checking. Body returned by server must match
        value of Content-Length header, if present. Otherwise, raise error.
    """

    def __init__(
        self,
        body: _TYPE_BODY = "",
        headers: Optional[Union[Mapping[str, str], Mapping[bytes, bytes]]] = None,
        status: int = 0,
        version: int = 0,
        reason: Optional[str] = None,
        preload_content: bool = True,
        decode_content: bool = True,
        original_response: Optional[_HttplibHTTPResponse] = None,
        pool: Optional["HTTPConnectionPool"] = None,
        connection: Optional[HTTPConnection] = None,
        msg: Optional[_HttplibHTTPMessage] = None,
        retries: Optional[Retry] = None,
        enforce_content_length: bool = True,
        request_method: Optional[str] = None,
        request_url: Optional[str] = None,
        auto_close: bool = True,
    ) -> None:
        super().__init__(
            headers=headers,
            status=status,
            version=version,
            reason=reason,
            decode_content=decode_content,
            request_url=request_url,
            retries=retries,
        )

        self.enforce_content_length = enforce_content_length
        self.auto_close = auto_close

        self._body = None
        self._fp: Optional[_HttplibHTTPResponse] = None
        self._original_response = original_response
        self._fp_bytes_read = 0
        self.msg = msg
        if self.retries is not None and self.retries.history:
            self._request_url = self.retries.history[-1].redirect_location
        else:
            self._request_url = request_url

        if body and isinstance(body, (str, bytes)):
            self._body = body

        self._pool = pool
        self._connection = connection

        if hasattr(body, "read"):
            self._fp = body  # type: ignore[assignment]

        # Are we using the chunked-style of transfer encoding?
        self.chunk_left: Optional[int] = None

        # Determine length of response
        self.length_remaining = self._init_length(request_method)

        # If requested, preload the body.
        if preload_content and not self._body:
            self._body = self.read(decode_content=decode_content)

    def release_conn(self) -> None:
        if not self._pool or not self._connection:
            return None

        self._pool._put_conn(self._connection)
        self._connection = None

    def drain_conn(self) -> None:
        """
        Read and discard any remaining HTTP response data in the response connection.

        Unread data in the HTTPResponse connection blocks the connection from being released back to the pool.
        """
        try:
            self.read()
        except (HTTPError, OSError, BaseSSLError, HTTPException):
            pass

    @property
    def data(self) -> bytes:
        # For backwards-compat with earlier urllib3 0.4 and earlier.
        if self._body:
            return self._body  # type: ignore[return-value]

        if self._fp:
            return self.read(cache_content=True)

        return None  # type: ignore[return-value]

    @property
    def connection(self) -> Optional[HTTPConnection]:
        return self._connection

    def isclosed(self) -> bool:
        return is_fp_closed(self._fp)

    def tell(self) -> int:
        """
        Obtain the number of bytes pulled over the wire so far. May differ from
        the amount of content returned by :meth:``urllib3.response.HTTPResponse.read``
        if bytes are encoded on the wire (e.g, compressed).
        """
        return self._fp_bytes_read

    def _init_length(self, request_method: Optional[str]) -> Optional[int]:
        """
        Set initial length value for Response content if available.
        """
        length: Optional[int]
        content_length: Optional[str] = self.headers.get("content-length")

        if content_length is not None:
            if self.chunked:
                # This Response will fail with an IncompleteRead if it can't be
                # received as chunked. This method falls back to attempt reading
                # the response before raising an exception.
                log.warning(
                    "Received response with both Content-Length and "
                    "Transfer-Encoding set. This is expressly forbidden "
                    "by RFC 7230 sec 3.3.2. Ignoring Content-Length and "
                    "attempting to process response as Transfer-Encoding: "
                    "chunked."
                )
                return None

            try:
                # RFC 7230 section 3.3.2 specifies multiple content lengths can
                # be sent in a single Content-Length header
                # (e.g. Content-Length: 42, 42). This line ensures the values
                # are all valid ints and that as long as the `set` length is 1,
                # all values are the same. Otherwise, the header is invalid.
                lengths = {int(val) for val in content_length.split(",")}
                if len(lengths) > 1:
                    raise InvalidHeader(
                        "Content-Length contained multiple "
                        "unmatching values (%s)" % content_length
                    )
                length = lengths.pop()
            except ValueError:
                length = None
            else:
                if length < 0:
                    length = None

        else:  # if content_length is None
            length = None

        # Convert status to int for comparison
        # In some cases, httplib returns a status of "_UNKNOWN"
        try:
            status = int(self.status)
        except ValueError:
            status = 0

        # Check for responses that shouldn't include a body
        if status in (204, 304) or 100 <= status < 200 or request_method == "HEAD":
            length = 0

        return length

    @contextmanager
    def _error_catcher(self) -> Generator[None, None, None]:
        """
        Catch low-level python exceptions, instead re-raising urllib3
        variants, so that low-level exceptions are not leaked in the
        high-level api.

        On exit, release the connection back to the pool.
        """
        clean_exit = False

        try:
            try:
                yield

            except SocketTimeout as e:
                # FIXME: Ideally we'd like to include the url in the ReadTimeoutError but
                # there is yet no clean way to get at it from this context.
                raise ReadTimeoutError(self._pool, None, "Read timed out.") from e  # type: ignore[arg-type]

            except BaseSSLError as e:
                # FIXME: Is there a better way to differentiate between SSLErrors?
                if "read operation timed out" not in str(e):
                    # SSL errors related to framing/MAC get wrapped and reraised here
                    raise SSLError(e) from e

                raise ReadTimeoutError(self._pool, None, "Read timed out.") from e  # type: ignore[arg-type]

            except (HTTPException, OSError) as e:
                # This includes IncompleteRead.
                raise ProtocolError(f"Connection broken: {e!r}", e) from e

            # If no exception is thrown, we should avoid cleaning up
            # unnecessarily.
            clean_exit = True
        finally:
            # If we didn't terminate cleanly, we need to throw away our
            # connection.
            if not clean_exit:
                # The response may not be closed but we're not going to use it
                # anymore so close it now to ensure that the connection is
                # released back to the pool.
                if self._original_response:
                    self._original_response.close()

                # Closing the response may not actually be sufficient to close
                # everything, so if we have a hold of the connection close that
                # too.
                if self._connection:
                    self._connection.close()

            # If we hold the original response but it's closed now, we should
            # return the connection back to the pool.
            if self._original_response and self._original_response.isclosed():
                self.release_conn()

    def read(
        self,
        amt: Optional[int] = None,
        decode_content: Optional[bool] = None,
        cache_content: bool = False,
    ) -> bytes:
        """
        Similar to :meth:`http.client.HTTPResponse.read`, but with two additional
        parameters: ``decode_content`` and ``cache_content``.

        :param amt:
            How much of the content to read. If specified, caching is skipped
            because it doesn't make sense to cache partial content as the full
            response.

        :param decode_content:
            If True, will attempt to decode the body based on the
            'content-encoding' header.

        :param cache_content:
            If True, will save the returned data such that the same result is
            returned despite of the state of the underlying file object. This
            is useful if you want the ``.data`` property to continue working
            after having ``.read()`` the file object. (Overridden if ``amt`` is
            set.)
        """
        self._init_decoder()
        if decode_content is None:
            decode_content = self.decode_content

        if self._fp is None:
            return None  # type: ignore[return-value]

        flush_decoder = False
        fp_closed = getattr(self._fp, "closed", False)

        with self._error_catcher():
            if amt is None:
                # cStringIO doesn't like amt=None
                data = self._fp.read() if not fp_closed else b""
                flush_decoder = True
            else:
                cache_content = False
                data = self._fp.read(amt) if not fp_closed else b""
                if (
                    amt != 0 and not data
                ):  # Platform-specific: Buggy versions of Python.
                    # Close the connection when no data is returned
                    #
                    # This is redundant to what httplib/http.client _should_
                    # already do.  However, versions of python released before
                    # December 15, 2012 (http://bugs.python.org/issue16298) do
                    # not properly close the connection in all cases. There is
                    # no harm in redundantly calling close.
                    self._fp.close()
                    flush_decoder = True
                    if (
                        self.enforce_content_length
                        and self.length_remaining is not None
                        and self.length_remaining != 0
                    ):
                        # This is an edge case that httplib failed to cover due
                        # to concerns of backward compatibility. We're
                        # addressing it here to make sure IncompleteRead is
                        # raised during streaming, so all calls with incorrect
                        # Content-Length are caught.
                        raise IncompleteRead(self._fp_bytes_read, self.length_remaining)

        if data:
            self._fp_bytes_read += len(data)
            if self.length_remaining is not None:
                self.length_remaining -= len(data)

            data = self._decode(data, decode_content, flush_decoder)

            if cache_content:
                self._body = data

        return data

    def stream(
        self, amt: Optional[int] = 2 ** 16, decode_content: Optional[bool] = None
    ) -> Generator[bytes, None, None]:
        """
        A generator wrapper for the read() method. A call will block until
        ``amt`` bytes have been read from the connection or until the
        connection is closed.

        :param amt:
            How much of the content to read. The generator will return up to
            much data per iteration, but may return less. This is particularly
            likely when using compressed data. However, the empty string will
            never be returned.

        :param decode_content:
            If True, will attempt to decode the body based on the
            'content-encoding' header.
        """
        if self.chunked and self.supports_chunked_reads():
            yield from self.read_chunked(amt, decode_content=decode_content)
        else:
            while not is_fp_closed(self._fp):
                data = self.read(amt=amt, decode_content=decode_content)

                if data:
                    yield data

    @classmethod
    def from_httplib(
        ResponseCls: Type["HTTPResponse"], r: _HttplibHTTPResponse, **response_kw: Any
    ) -> "HTTPResponse":
        """
        Given an :class:`http.client.HTTPResponse` instance ``r``, return a
        corresponding :class:`urllib3.response.HTTPResponse` object.

        Remaining parameters are passed to the HTTPResponse constructor, along
        with ``original_response=r``.
        """
        headers = r.msg

        if not isinstance(headers, HTTPHeaderDict):
            headers = HTTPHeaderDict(headers.items())  # type: ignore[assignment]

        resp = ResponseCls(
            body=r,
            headers=headers,  # type: ignore[arg-type]
            status=r.status,
            version=r.version,
            reason=r.reason,
            original_response=r,
            **response_kw,
        )
        return resp

    # Overrides from io.IOBase
    def close(self) -> None:
        if not self.closed and self._fp:
            self._fp.close()

        if self._connection:
            self._connection.close()

        if not self.auto_close:
            io.IOBase.close(self)

    @property
    def closed(self) -> bool:
        if not self.auto_close:
            return io.IOBase.closed.__get__(self)  # type: ignore[no-any-return, attr-defined]
        elif self._fp is None:
            return True
        elif hasattr(self._fp, "isclosed"):
            return self._fp.isclosed()
        elif hasattr(self._fp, "closed"):
            return self._fp.closed
        else:
            return True

    def fileno(self) -> int:
        if self._fp is None:
            raise OSError("HTTPResponse has no file to get a fileno from")
        elif hasattr(self._fp, "fileno"):
            return self._fp.fileno()
        else:
            raise OSError(
                "The file-like object this HTTPResponse is wrapped "
                "around has no file descriptor"
            )

    def flush(self) -> None:
        if (
            self._fp is not None
            and hasattr(self._fp, "flush")
            and not getattr(self._fp, "closed", False)
        ):
            return self._fp.flush()

    def supports_chunked_reads(self) -> bool:
        """
        Checks if the underlying file-like object looks like a
        :class:`http.client.HTTPResponse` object. We do this by testing for
        the fp attribute. If it is present we assume it returns raw chunks as
        processed by read_chunked().
        """
        return hasattr(self._fp, "fp")

    def _update_chunk_length(self) -> None:
        # First, we'll figure out length of a chunk and then
        # we'll try to read it from socket.
        if self.chunk_left is not None:
            return None
        line = self._fp.fp.readline()  # type: ignore[union-attr]
        line = line.split(b";", 1)[0]
        try:
            self.chunk_left = int(line, 16)
        except ValueError:
            # Invalid chunked protocol response, abort.
            self.close()
            raise InvalidChunkLength(self, line) from None

    def _handle_chunk(self, amt: Optional[int]) -> bytes:
        returned_chunk = None
        if amt is None:
            chunk = self._fp._safe_read(self.chunk_left)  # type: ignore[union-attr]
            returned_chunk = chunk
            self._fp._safe_read(2)  # type: ignore[union-attr] # Toss the CRLF at the end of the chunk.
            self.chunk_left = None
        elif self.chunk_left is not None and amt < self.chunk_left:
            value = self._fp._safe_read(amt)  # type: ignore[union-attr]
            self.chunk_left = self.chunk_left - amt
            returned_chunk = value
        elif amt == self.chunk_left:
            value = self._fp._safe_read(amt)  # type: ignore[union-attr]
            self._fp._safe_read(2)  # type: ignore[union-attr] # Toss the CRLF at the end of the chunk.
            self.chunk_left = None
            returned_chunk = value
        else:  # amt > self.chunk_left
            returned_chunk = self._fp._safe_read(self.chunk_left)  # type: ignore[union-attr]
            self._fp._safe_read(2)  # type: ignore[union-attr] # Toss the CRLF at the end of the chunk.
            self.chunk_left = None
        return returned_chunk  # type: ignore[no-any-return]

    def read_chunked(
        self, amt: Optional[int] = None, decode_content: Optional[bool] = None
    ) -> Generator[bytes, None, None]:
        """
        Similar to :meth:`HTTPResponse.read`, but with an additional
        parameter: ``decode_content``.

        :param amt:
            How much of the content to read. If specified, caching is skipped
            because it doesn't make sense to cache partial content as the full
            response.

        :param decode_content:
            If True, will attempt to decode the body based on the
            'content-encoding' header.
        """
        self._init_decoder()
        # FIXME: Rewrite this method and make it a class with a better structured logic.
        if not self.chunked:
            raise ResponseNotChunked(
                "Response is not chunked. "
                "Header 'transfer-encoding: chunked' is missing."
            )
        if not self.supports_chunked_reads():
            raise BodyNotHttplibCompatible(
                "Body should be http.client.HTTPResponse like. "
                "It should have have an fp attribute which returns raw chunks."
            )

        with self._error_catcher():
            # Don't bother reading the body of a HEAD request.
            if self._original_response and is_response_to_head(self._original_response):
                self._original_response.close()
                return None

            # If a response is already read and closed
            # then return immediately.
            if self._fp.fp is None:  # type: ignore[union-attr]
                return None

            while True:
                self._update_chunk_length()
                if self.chunk_left == 0:
                    break
                chunk = self._handle_chunk(amt)
                decoded = self._decode(
                    chunk, decode_content=decode_content, flush_decoder=False
                )
                if decoded:
                    yield decoded

            if decode_content:
                # On CPython and PyPy, we should never need to flush the
                # decoder. However, on Jython we *might* need to, so
                # lets defensively do it anyway.
                decoded = self._flush_decoder()
                if decoded:  # Platform-specific: Jython.
                    yield decoded

            # Chunk content ends with \r\n: discard it.
            while self._fp is not None:
                line = self._fp.fp.readline()
                if not line:
                    # Some sites may not end with '\r\n'.
                    break
                if line == b"\r\n":
                    break

            # We read everything; close the "file".
            if self._original_response:
                self._original_response.close()

    @property
    def url(self) -> Optional[str]:
        """
        Returns the URL that was the source of this response.
        If the request that generated this response redirected, this method
        will return the final redirect location.
        """
        return self._request_url

    @url.setter
    def url(self, url: str) -> None:
        self._request_url = url

    def __iter__(self) -> Iterator[bytes]:
        buffer: List[bytes] = []
        for chunk in self.stream(decode_content=True):
            if b"\n" in chunk:
                chunks = chunk.split(b"\n")
                yield b"".join(buffer) + chunks[0] + b"\n"
                for x in chunks[1:-1]:
                    yield x + b"\n"
                if chunks[-1]:
                    buffer = [chunks[-1]]
                else:
                    buffer = []
            else:
                buffer.append(chunk)
        if buffer:
            yield b"".join(buffer)

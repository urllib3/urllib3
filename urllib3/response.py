from __future__ import absolute_import
from contextlib import contextmanager
import zlib
import io
import logging
from socket import timeout as SocketTimeout
from socket import error as SocketError

import h11

from ._collections import HTTPHeaderDict
from .exceptions import (
    ProtocolError, DecodeError, ReadTimeoutError
)
from .packages.six import string_types as basestring, binary_type
from .util.ssl_ import BaseSSLError

log = logging.getLogger(__name__)


class DeflateDecoder(object):

    def __init__(self):
        self._first_try = True
        self._data = binary_type()
        self._obj = zlib.decompressobj()

    def __getattr__(self, name):
        return getattr(self._obj, name)

    def decompress(self, data):
        if not data:
            return data

        if not self._first_try:
            return self._obj.decompress(data)

        self._data += data
        try:
            decompressed = self._obj.decompress(data)
            if decompressed:
                self._first_try = False
                self._data = None
            return decompressed
        except zlib.error:
            self._first_try = False
            self._obj = zlib.decompressobj(-zlib.MAX_WBITS)
            try:
                return self.decompress(self._data)
            finally:
                self._data = None


class GzipDecoder(object):

    def __init__(self):
        self._obj = zlib.decompressobj(16 + zlib.MAX_WBITS)

    def __getattr__(self, name):
        return getattr(self._obj, name)

    def decompress(self, data):
        if not data:
            return data
        return self._obj.decompress(data)


def _get_decoder(mode):
    if mode == 'gzip':
        return GzipDecoder()

    return DeflateDecoder()


class HTTPResponse(io.IOBase):
    """
    HTTP Response container.

    Backwards-compatible to httplib's HTTPResponse but the response ``body`` is
    loaded and decoded on-demand when the ``data`` property is accessed.  This
    class is also compatible with the Python standard library's :mod:`io`
    module, and can hence be treated as a readable object in the context of that
    framework.

    Extra parameters for behaviour not present in httplib.HTTPResponse:

    :param preload_content:
        If True, the response's body will be preloaded during construction.

    :param decode_content:
        If True, attempts to decode specific content-encoding's based on headers
        (like 'gzip' and 'deflate') will be skipped and raw data will be used
        instead.

    :param retries:
        The retries contains the last :class:`~urllib3.util.retry.Retry` that
        was used during the request.
    """

    CONTENT_DECODERS = ['gzip', 'deflate']
    REDIRECT_STATUSES = [301, 302, 303, 307, 308]

    def __init__(self, body='', headers=None, status=0, version=0, reason=None,
                 strict=0, preload_content=True, decode_content=True,
                 original_response=None, pool=None, connection=None,
                 retries=None, request_method=None):

        if isinstance(headers, HTTPHeaderDict):
            self.headers = headers
        else:
            self.headers = HTTPHeaderDict(headers)
        self.status = status
        self.version = version
        self.reason = reason
        self.strict = strict
        self.decode_content = decode_content
        self.retries = retries

        self._decoder = None
        self._body = None
        self._fp = None
        self._original_response = original_response
        self._fp_bytes_read = 0
        self._buffer = b''

        if body and isinstance(body, (basestring, binary_type)):
            self._body = body
        else:
            self._fp = body

        self._pool = pool
        self._connection = connection

        # If requested, preload the body.
        if preload_content and not self._body:
            self._body = self.read(decode_content=decode_content)

    def get_redirect_location(self):
        """
        Should we redirect and where to?

        :returns: Truthy redirect location string if we got a redirect status
            code and valid location. ``None`` if redirect status and no
            location. ``False`` if not a redirect status code.
        """
        if self.status in self.REDIRECT_STATUSES:
            return self.headers.get('location')

        return False

    async def release_conn(self):
        if not self._pool or not self._connection:
            return

        await self._pool._put_conn(self._connection)
        self._connection = None

    @property
    def data(self):
        # For backwords-compat with earlier urllib3 0.4 and earlier.
        if self._body is not None:
            return self._body

        if self._fp:
            return self.read(cache_content=True)

    @property
    def connection(self):
        return self._connection

    def tell(self):
        """
        Obtain the number of bytes pulled over the wire so far. May differ from
        the amount of content returned by :meth:``HTTPResponse.read`` if bytes
        are encoded on the wire (e.g, compressed).
        """
        return self._fp_bytes_read

    def _init_decoder(self):
        """
        Set-up the _decoder attribute if necessary.
        """
        # Note: content-encoding value should be case-insensitive, per RFC 7230
        # Section 3.2
        content_encoding = self.headers.get('content-encoding', '').lower()
        if self._decoder is None and content_encoding in self.CONTENT_DECODERS:
            self._decoder = _get_decoder(content_encoding)

    def _decode(self, data, decode_content, flush_decoder):
        """
        Decode the data passed in and potentially flush the decoder.
        """
        try:
            if decode_content and self._decoder:
                data = self._decoder.decompress(data)
        except (IOError, zlib.error) as e:
            content_encoding = self.headers.get('content-encoding', '').lower()
            raise DecodeError(
                "Received response with content-encoding: %s, but "
                "failed to decode it." % content_encoding, e)

        if flush_decoder and decode_content:
            data += self._flush_decoder()

        return data

    def _flush_decoder(self):
        """
        Flushes the decoder. Should only be called if the decoder is actually
        being used.
        """
        if self._decoder:
            buf = self._decoder.decompress(b'')
            return buf + self._decoder.flush()

        return b''

    @contextmanager
    def _error_catcher(self):
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

            except SocketTimeout:
                # FIXME: Ideally we'd like to include the url in the ReadTimeoutError but
                # there is yet no clean way to get at it from this context.
                raise ReadTimeoutError(self._pool, None, 'Read timed out.')

            except BaseSSLError as e:
                # FIXME: Is there a better way to differentiate between SSLErrors?
                if 'read operation timed out' not in str(e):  # Defensive:
                    # This shouldn't happen but just in case we're missing an edge
                    # case, let's avoid swallowing SSL errors.
                    raise

                raise ReadTimeoutError(self._pool, None, 'Read timed out.')

            except (h11.ProtocolError, SocketError) as e:
                # This includes IncompleteRead.
                raise ProtocolError('Connection broken: %r' % e, e)

            except GeneratorExit:
                # We swallow GeneratorExit when it is emitted: this allows the
                # use of the error checker inside stream()
                pass

            # If no exception is thrown, we should avoid cleaning up
            # unnecessarily.
            clean_exit = True
        finally:
            # If we didn't terminate cleanly, we need to throw away our
            # connection.
            if not clean_exit:
                self.close()

            # If we hold the original response but it's finished now, we should
            # return the connection back to the pool.
            # XXX
            if False and self._original_response and self._original_response.complete:
                self.release_conn()

    async def read(self, amt=None, decode_content=None, cache_content=False):
        """
        Similar to :meth:`httplib.HTTPResponse.read`, but with two additional
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
        # TODO: refactor this method to better handle buffered output.
        # This method is a weird one. We treat this read() like a buffered
        # read, meaning that it never reads "short" unless there is an EOF
        # condition at work. However, we have a decompressor in play here,
        # which means our read() returns decompressed data.
        #
        # This means the buffer can only meaningfully buffer decompressed data.
        # This makes this method prone to over-reading, and forcing too much
        # data into the buffer. That's unfortunate, but right now I'm not smart
        # enough to come up with a way to solve that problem.
        if self._fp is None and not self._buffer:
            return b''

        data = self._buffer

        with self._error_catcher():
            if amt is None:
                async for chunk in self.stream(decode_content):
                    data += chunk
                self._buffer = b''

                # We only cache the body data for simple read calls.
                self._body = data
            else:
                data_len = len(data)
                chunks = [data]
                streamer = self.stream(decode_content)

                while data_len < amt:
                    try:
                        chunk = next(streamer)
                    except StopIteration:
                        break
                    else:
                        chunks.append(chunk)
                        data_len += len(chunk)

                data = b''.join(chunks)
                self._buffer = data[amt:]
                data = data[:amt]

        return data

    async def stream(self, decode_content=None):
        """
        A generator wrapper for the read() method.

        :param decode_content:
            If True, will attempt to decode the body based on the
            'content-encoding' header.
        """
        # Short-circuit evaluation for exhausted responses.
        if self._fp is None:
            return

        self._init_decoder()
        if decode_content is None:
            decode_content = self.decode_content

        with self._error_catcher():
            async for raw_chunk in self._fp:
                self._fp_bytes_read += len(raw_chunk)
                decoded_chunk = self._decode(
                    raw_chunk, decode_content, flush_decoder=False
                )
                if decoded_chunk:
                    yield decoded_chunk

            # This branch is speculative: most decoders do not need to flush,
            # and so this produces no output. However, it's here because
            # anecdotally some platforms on which we do not test (like Jython)
            # do require the flush. For this reason, we exclude this from code
            # coverage. Happily, the code here is so simple that testing the
            # branch we don't enter is basically entirely unnecessary (it's
            # just a yield statement).
            final_chunk = self._decode(
                b'', decode_content, flush_decoder=True
            )
            if final_chunk:  # Platform-specific: Jython
                yield final_chunk

            self._fp = None

    @classmethod
    def from_base(ResponseCls, r, **response_kw):
        """
        Given an :class:`urllib3.base.Response` instance ``r``, return a
        corresponding :class:`urllib3.response.HTTPResponse` object.

        Remaining parameters are passed to the HTTPResponse constructor, along
        with ``original_response=r``.
        """
        resp = ResponseCls(body=r.body,
                           headers=r.headers,
                           status=r.status_code,
                           version=r.version,
                           original_response=r,
                           connection=r.body,
                           **response_kw)
        return resp

    # Backwards-compatibility methods for httplib.HTTPResponse
    def getheaders(self):
        return self.headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    # Overrides from io.IOBase
    def close(self):
        if not self.closed:
            self._fp.close()
            self._buffer = b''
            self._fp = None

        if self._connection:
            self._connection.close()

    @property
    def closed(self):
        # This method is required for `io` module compatibility.
        if self._fp is None and not self._buffer:
            return True
        elif hasattr(self._fp, 'complete'):
            return self._fp.complete
        else:
            return False

    def fileno(self):
        # This method is required for `io` module compatibility.
        if self._fp is None:
            raise IOError("HTTPResponse has no file to get a fileno from")
        elif hasattr(self._fp, "fileno"):
            return self._fp.fileno()
        else:
            raise IOError("The file-like object this HTTPResponse is wrapped "
                          "around has no file descriptor")

    def readable(self):
        # This method is required for `io` module compatibility.
        return True

    def readinto(self, b):
        # This method is required for `io` module compatibility.
        temp = self.read(len(b))
        if len(temp) == 0:
            return 0
        else:
            b[:len(temp)] = temp
            return len(temp)

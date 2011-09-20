import gzip
import logging
import zlib


try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO # pylint: disable-msg=W0404


from .exceptions import HTTPError


log = logging.getLogger(__name__)


def decode_gzip(data):
    gzipper = gzip.GzipFile(fileobj=StringIO(data))
    return gzipper.read()


def decode_deflate(data):
    try:
        return zlib.decompress(data)
    except zlib.error:
        return zlib.decompress(data, -zlib.MAX_WBITS)


class HTTPResponse(object):
    """
    HTTP Response container.

    Backwards-compatible to httplib's HTTPResponse but the response ``body`` is
    loaded and decoded on-demand when the ``data`` property is accessed.

    Extra parameters for behaviour not present in httplib.HTTPResponse:

    preload_body
        If True, the response's body will be preloaded during construction.

    skip_decode
        If True, attempts to decode specific content-encoding's based on headers
        (like 'gzip' and 'deflate') will be skipped and raw data will be used
        instead.

    original_response
        When this HTTPResponse wrapper is generated from an httplib.HTTPResponse
        object, it's convenient to include the original for debug purposes. It's
        otherwise unused.
    """

    CONTENT_DECODERS = {
        'gzip': decode_gzip,
        'deflate': decode_deflate,
    }

    def __init__(self, body='', headers=None, status=0, version=0, reason=None,
                 strict=0, preload_body=True, skip_decode=False,
                 original_response=None):
        self.headers = headers or {}
        self.status = status
        self.version = version
        self.reason = reason
        self.strict = strict

        self._skip_decode = skip_decode
        self._body = None
        self._fp = None
        self._original_response = original_response

        if hasattr(body, 'read'):
            self._fp = body

        if preload_body:
            self._body = self.read()

    @property
    def data(self):
        # For backwords-compat with earlier urllib3 0.4 and earlier.
        if self._body:
            return self._body

        if self._fp:
            return self.read()


    def read(self, amt=None, decode_body=True, cache_body=True):
        """
        Similar to ``httplib.HTTPResponse.read(amt=None)`` but adds two more
        behaviours:

        decode_body
            If True, will attempt to decode the body based on the
            'content-encoding' header.

        cache_body
            If True, will save the returned data such that the same result is
            returned despite of the state of the underlying file object. This
            is useful if you want the ``.data`` property to continue working
            after having ``.read()`` the file object.

        """
        content_encoding = self.headers.get('content-encoding')
        decoder = self.CONTENT_DECODERS.get(content_encoding)

        data = self._fp and self._fp.read(amt)

        if not decode_body or not decoder:
            if cache_body:
                self._body = data

            return data

        try:
            data = decoder(data)
        except IOError:
            raise HTTPError("Received response with content-encoding: %s, but "
                            "failed to decode it." % content_encoding)

        if cache_body:
            self._body = data

        return data

    @staticmethod
    def from_httplib(r, preload_body=True, skip_decode=False):
        """
        Given an httplib.HTTPResponse instance ``r``, return a corresponding
        urllib3.HTTPResponse object.

        Remaining parameters are passed to the HTTPResponse constructor, along
        with ``original_response=r``.
        """

        return HTTPResponse(body=r,
                    headers=dict(r.getheaders()),
                    status=r.status,
                    version=r.version,
                    reason=r.reason,
                    strict=r.strict,
                    preload_body=preload_body,
                    skip_decode=skip_decode,
                    original_response=r)

    # Backwards-compatibility methods for httplib.HTTPResponse
    def getheaders(self):
        return self.headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

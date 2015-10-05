import zlib
from ..packages.six import binary_type

# The supported content-codings.
CONTENT_ENCODINGS = {}

# Any errors that may be raised during decoding.
DECODING_ERRORS = ()


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
            return self._obj.decompress(data)
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


def register_content_encoding(name, decoder, exceptions=()):
    """
    Adds a handler for a new kind of content-encoding.

    Calling this function enables urllib3 to handle a specific kind of HTTP
    content-encoding, such as gzip or deflate. When called, urllib3 will become
    able to advertise support for this content-encoding (via
    :meth:`make_headers <urllib3.util.request.make_headers>`) and will become
    able to transparently decode that content-encoding when a response is
    received that uses it.

    :param name: The name of the content-encoding, as used in the
                 Accept-Encoding and Content-Encoding header fields.
    :param decoder: A decoder object that supports incremental decompression.
    :param exceptions: (optional) Any extra exceptions that may be raised by
                       this decoder on decompression failure.
    """
    global DECODING_ERRORS

    CONTENT_ENCODINGS[name] = decoder
    if exceptions:
        DECODING_ERRORS = tuple(set(DECODING_ERRORS + exceptions))


def get_decoder(name):
    """
    Gets the decoder for a given content-encoding. For historical reasons, this
    method will return the :class:`DeflateDecoder
    <urllib3.util.codings.DeflateDecoder>` object if no other encoding matches.
    """
    return CONTENT_ENCODINGS.get(name, DeflateDecoder)()


def decoding_errors():
    """
    All exceptions that may be raised by the content decoders.
    """
    return DECODING_ERRORS


def content_encodings():
    """
    All currently-supported content_encodings.
    """
    return list(CONTENT_ENCODINGS)


register_content_encoding('deflate', DeflateDecoder, (IOError, zlib.error))
register_content_encoding('gzip', GzipDecoder, (IOError, zlib.error))

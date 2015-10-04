"""
Support for Brotli compression as content-encoding.

This needs the brotlipy package installed from PyPI. You can install it with
the following command:

    pip install brotlipy

To activate Brotli support, call
:func:`~urllib3.contrib.brotli.inject_into_urllib3` from your Python code
before you start making HTTP requests, like this::

    try:
        import urllib3.contrib.brotlipy
        urllib3.contrib.brotlipy.inject_into_urllib3()
    except ImportError:
        pass

Now you can use :mod:`urllib3` as you normally would, and it will support
Brotli content-encoding when the required modules are installed.
"""
import brotli

from .. import response
from ..util import request

# Original _get_decoder method.
original_decoder = response._get_decoder


# New _get_decoder method.
def _new_decoder(mode):
    if mode == 'brotli':
        return BrotliDecoder()

    return original_decoder(mode)


class BrotliDecoder(object):
    def __init__(self):
        self._obj = brotli.Decompressor()

    def __getattr__(self, name):
        return getattr(self._obj, name)

    def decompress(self, data):
        if not data:
            return data
        return self._obj.decompress(data)


def inject_into_urllib3():
    response.HTTPResponse.CONTENT_DECODERS.append('brotli')
    request.ACCEPT_ENCODING += ',brotli'
    response._get_decoder = _new_decoder

# -*- coding: utf-8 -*-
"""
This module provides the base structure of the Request/Response objects that
urllib3 passes around to manage its HTTP semantic layer.

These objects are the lowest common denominator: that is, they define the
Request/Response functionality that is always supported by urllib3. This means
they do not include any extra function required for asynchrony: that
functionality is handled elsewhere. Any part of urllib3 is required to be able
to work with one of these objects.
"""
from ._collections import HTTPHeaderDict


class Request(object):
    """
    The base, common, Request object.

    This object provides a *semantic* representation of a HTTP request. It
    includes all the magical parts of a HTTP request that we have come to know
    and love: it has a method, a target (the path & query portions of a URI),
    some headers, and optionally a body.

    All of urllib3 manipulates these Request objects, passing them around and
    changing them as necessary. The low-level layers know how to send these
    objects.
    """
    def __init__(self, method, target, headers=None, body=None):
        #: The HTTP method in use. Must be a byte string.
        self.method = method

        #: The request target: that is, the path and query portions of the URI.
        self.target = target

        #: The request headers. These are always stored as a HTTPHeaderDict.
        self.headers = HTTPHeaderDict(headers)

        #: The request body. This is allowed to be one a few kind of objects:
        #:    - A byte string.
        #:    - A "readable" object.
        #:    - An iterable of byte strings.
        #:    - A text string (not recommended, auto-encoded to UTF-8)
        self.body = body

    def add_host(self, host):
        """
        Add the Host header, as needed.

        This helper method exists to circumvent an ordering problem: the best
        layer to add the Host header is the bottom layer, but it is the layer
        that will add headers last. That means that they will appear at the
        bottom of the header block.

        Proxies, caches, and other intermediaries *hate* it when clients do
        that because the Host header is routing information, and they'd like to
        see it as early as possible. For this reason, this method ensures that
        the Host header will be the first one emitted. It also ensures that we
        do not duplicate the host header: if there already is one, we just use
        that one.
        """
        if b'host' not in self.headers:
            headers = HTTPHeaderDict(host=host)
            headers._copy_from(self.headers)
            self.headers = headers


class Response(object):
    """
    The abstract low-level Response object that urllib3 works on. This is not
    the high-level helpful Response object that is exposed at the higher layers
    of urllib3: it's just a simple object that just exposes the lowest-level
    HTTP semantics to allow processing by the higher levels.
    """
    def __init__(self, status_code, headers, body, version):
        #: The HTTP status code of the response.
        self.status_code = status_code

        #: The headers on the response, as a HTTPHeaderDict.
        self.headers = HTTPHeaderDict(headers)

        #: The request body. This is an iterable of bytes, and *must* be
        #: iterated if the connection is to be preserved.
        self.body = body

        #: The HTTP version of the response. Stored as a bytestring.
        self.version = version

    @property
    def complete(self):
        """
        If the response can be safely returned to the connection pool, returns
        True.
        """
        return self.body.complete

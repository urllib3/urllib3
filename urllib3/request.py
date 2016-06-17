from __future__ import absolute_import
try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

from .filepost import encode_multipart_formdata, iter_field_objects


__all__ = ['RequestMethods']


class RequestMethods(object):
    """
    Convenience mixin for classes who implement a :meth:`urlopen` method, such
    as :class:`~urllib3.connectionpool.HTTPConnectionPool` and
    :class:`~urllib3.poolmanager.PoolManager`.

    Provides behavior for making common types of HTTP request methods and
    decides which type of request field encoding to use.

    Specifically,

    :meth:`.request_encode_url` is for sending requests whose fields are
    encoded in the URL (such as GET, HEAD, DELETE).

    :meth:`.request_encode_body` is for sending requests whose fields are
    encoded in the *body* of the request using multipart or www-form-urlencoded
    (such as for POST, PUT, PATCH).

    :meth:`.request` is for making any kind of request, it will look up the
    appropriate encoding format and use one of the above two methods to make
    the request.

    Initializer parameters:

    :param headers:
        Headers to include with all requests, unless other headers are given
        explicitly.
    """

    _encode_url_methods = set(['DELETE', 'GET', 'HEAD', 'OPTIONS'])

    def __init__(self, headers=None):
        self.headers = headers or {}

    def urlopen(self, method, url, body=None, headers=None,
                encode_multipart=True, multipart_boundary=None,
                **kw):  # Abstract
        raise NotImplemented("Classes extending RequestMethods must implement "
                             "their own ``urlopen`` method.")

    def request(self, method, url, fields=None, headers=None, body=None, **urlopen_kw):
        """
        Make a request using :meth:`urlopen` with the appropriate encoding of
        ``fields`` based on the ``method`` used.

        This is a convenience method that requires the least amount of manual
        effort. It can be used in most situations, while still having the
        option to drop down to more specific methods when necessary, such as
        :meth:`request_encode_url`, :meth:`request_encode_body`,
        or even the lowest level :meth:`urlopen`.
        """
        pops = [
            'encode_multipart',
            'multipart_boundary',
            'form_fields',
            'url_params',
            'fields'
        ]
        method = method.upper()
        if headers is None:
            headers = self.headers.copy()

        url = self.encode_url(method, url, fields=fields, **urlopen_kw)

        headers, body = self.encode_body_and_headers(method, body=body, fields=fields,
                                                     headers=headers, **urlopen_kw)
        for each in pops:
            urlopen_kw.pop(each, None)

        return self.urlopen(method, url, headers=headers, body=body, **urlopen_kw)

    def encode_body_and_headers(self, method, body=None, fields=None,
                                form_fields=None, headers=None, encode_multipart=True,
                                multipart_boundary=None, **kw):
        """
        Encode and return a request body and headers to match
        """
        headers = headers or dict()
        form_fields = form_fields or []
        fields = fields or []

        if fields or form_fields:

            content_type = None

            if body is not None:
                raise TypeError(
                    "request got values for both 'fields' and 'body', can only specify one.")

            if encode_multipart and method not in self._encode_url_methods:
                fields = iter_field_objects(fields, form_fields)
                body, content_type = encode_multipart_formdata(fields, boundary=multipart_boundary)
            elif method not in self._encode_url_methods:
                body = ''
                if fields:
                    body += urlencode(fields)
                    if form_fields:
                        body += '&'
                if form_fields:
                    body += urlencode(form_fields)
                content_type = 'application/x-www-form-urlencoded'

            if content_type:
                headers.update({'Content-Type': content_type})

        return headers, body

    def encode_url(self, method, url, fields=None, url_params=None, **kw):
        """
        Encode relevant fields into the URL; we have to do them separately,
        as they might be coming in as different object types.
        """
        url_params = url_params or []
        fields = fields or []
        querystring = ''
        if method in self._encode_url_methods and fields:
            querystring += urlencode(fields)
            if querystring and url_params:
                querystring += '&'

        if url_params:
            querystring += urlencode(url_params)

        if querystring:
            url += '?' + querystring

        return url

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
        headers, body = self.encode_body_and_headers(method, body=body, fields=fields, headers=headers, **urlopen_kw)
        for each in pops:
            urlopen_kw.pop(each, None)
        return self.urlopen(method, url, headers=headers, body=body, **urlopen_kw)

    def encode_body_and_headers(self, method, body=None, fields=None, form_fields=None,
                                headers=None, encode_multipart=True, multipart_boundary=None, **kw):
        """
        Encode and return a request body and headers to match
        """
        form_fields = form_fields or []
        fields = fields or []

        if fields or form_fields:
            if body is not None:
                raise TypeError(
                    "request got values for both 'fields' and 'body', can only specify one.")

            if encode_multipart and method not in self._encode_url_methods:
                fields = iter_field_objects(fields, form_fields)
                body, content_type = encode_multipart_formdata(fields, boundary=multipart_boundary)
            else:
                body = ''
                if fields and method not in self._encode_url_methods:
                    body += urlencode(fields)
                    if form_fields:
                        body += '&'
                if form_fields:
                    body += urlencode(form_fields)
                content_type = 'application/x-www-form-urlencoded'

            headers.update({'Content-Type':content_type})

        return headers, body


    def encode_url(self, method, url, fields=None, url_params=None, **kw):
        """
        Encode relevant fields into the URL; we need to do a bit of manipulation
        first, as we don't have a guarantee that both will be in the same format.
        """
        url_params = url_params or []
        fields = fields or []
        querystring = ''
        if method in self._encode_url_methods and fields:
            print(fields)
            querystring += urlencode(fields)
            if querystring and url_params:
                querystring += '&'
        if url_params:
            print(url_params)
            querystring += urlencode(url_params)

        if querystring:
            url += '?' + querystring

        return url


    def request_encode_url(self, method, url, fields=None, headers=None,
                           **urlopen_kw):
        """
        Make a request using :meth:`urlopen` with the ``fields`` encoded in
        the url. This is useful for request methods like GET, HEAD, DELETE, etc.
        """
        if headers is None:
            headers = self.headers

        extra_kw = {'headers': headers}
        extra_kw.update(urlopen_kw)

        if fields:
            url += '?' + urlencode(fields)

        return self.urlopen(method, url, **extra_kw)


    def request_encode_body(self, method, url, fields=None, headers=None,
                            encode_multipart=True, multipart_boundary=None,
                            **urlopen_kw):
        """
        Make a request using :meth:`urlopen` with the ``fields`` encoded in
        the body. This is useful for request methods like POST, PUT, PATCH, etc.

        When ``encode_multipart=True`` (default), then
        :meth:`urllib3.filepost.encode_multipart_formdata` is used to encode
        the payload with the appropriate content type. Otherwise
        :meth:`urllib.urlencode` is used with the
        'application/x-www-form-urlencoded' content type.

        Multipart encoding must be used when posting files, and it's reasonably
        safe to use it in other times too. However, it may break request
        signing, such as with OAuth.

        Supports an optional ``fields`` parameter of key/value strings AND
        key/filetuple. A filetuple is a (filename, data, MIME type) tuple where
        the MIME type is optional. For example::

            fields = {
                'foo': 'bar',
                'fakefile': ('foofile.txt', 'contents of foofile'),
                'realfile': ('barfile.txt', open('realfile').read()),
                'typedfile': ('bazfile.bin', open('bazfile').read(),
                              'image/jpeg'),
                'nonamefile': 'contents of nonamefile field',
            }

        When uploading a file, providing a filename (the first parameter of the
        tuple) is optional but recommended to best mimick behavior of browsers.

        Note that if ``headers`` are supplied, the 'Content-Type' header will
        be overwritten because it depends on the dynamic random boundary string
        which is used to compose the body of the request. The random boundary
        string can be explicitly set with the ``multipart_boundary`` parameter.
        """
        if headers is None:
            headers = self.headers

        extra_kw = {'headers': {}}

        if fields:
            if 'body' in urlopen_kw:
                raise TypeError(
                    "request got values for both 'fields' and 'body', can only specify one.")

            if encode_multipart:
                body, content_type = encode_multipart_formdata(fields, boundary=multipart_boundary)
            else:
                body, content_type = urlencode(fields), 'application/x-www-form-urlencoded'

            extra_kw['body'] = body
            extra_kw['headers'] = {'Content-Type': content_type}

        extra_kw['headers'].update(headers)
        extra_kw.update(urlopen_kw)

        return self.urlopen(method, url, **extra_kw)

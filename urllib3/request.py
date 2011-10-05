# urllib3/request.py
# Copyright 2008-2011 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php


from urllib import urlencode

from .filepost import encode_multipart_formdata


__all__ = ['RequestMethods']


class RequestMethods(object):

    def urlopen(self, method, url, body=None, headers=None, **kw):
        raise NotImplemented("Classes extending RequestMethods must implement "
                             "their own ``urlopen`` method.")

    def request(self, method, url, fields=None, headers=None, **urlopen_kw):
        """
        Make a request using ``urlopen`` with the proper encoding of ``fields``
        based on the ``method`` used.
        """
        method = method.upper()

        if method in self._encode_url_methods:
            return self._request_encode_url(method, url, fields=fields,
                                            headers=headers,
                                            **urlopen_kw)
        else:
            return self._request_encode_body(method, url, fields=fields,
                                             headers=headers,
                                             **urlopen_kw)

    def _request_encode_url(self, method, url, fields=None, **urlopen_kw):
        """
        Make a request with the ``fields`` encoded in the url.
        """
        if fields:
            url += '?' + urlencode(fields)
        return self.urlopen(method, url, **urlopen_kw)

    def _request_encode_body(self, method, url, fields=None, headers=None,
                             encode_multipart=True, multipart_boundary=None,
                             **urlopen_kw):
        """
        Make a request with the ``fields`` encoded in the body.

        If ``encode_multipart=True`` (default), then
        ``urllib3.filepost.encode_multipart_formdata`` is used to encode the
        payload with the appropriate content type. Otherwise
        ``urllib.urlencode`` is used with 'application/x-www-form-urlencoded'
        content type.

        Multipart encoding must be used when posting files, and it's reasonably
        safe to use it other times too. It may break request signing, such as
        OAuth.

        Supports an optional ``fields`` parameter of key/value strings AND
        key/filetuple. A filetuple is a (filename, data) tuple. For example:

        fields = {
            'foo': 'bar',
            'foofile': ('foofile.txt', 'contents of foofile'),
        }

        NOTE: If ``headers`` are supplied, the 'Content-Type' value will be
        overwritten because it depends on the dynamic random boundary string
        which is used to compose the body of the request.
        OAuth.
        """
        if encode_multipart:
            body, content_type = encode_multipart_formdata(fields or {},
                                    boundary=multipart_boundary)
        else:
            body, content_type = (urlencode(fields or {}),
                                    'application/x-www-form-urlencoded')

        headers = headers or {}
        headers.update({'Content-Type': content_type})

        return self.urlopen(method, url, body, headers=headers, **urlopen_kw)

    # url-encoded methods:

    def get_url(self, url, fields=None, **urlopen_kw):
        return self._request_encode_url('GET', url, fields=fields,
                                        **urlopen_kw)

    def head_url(self, url, fields=None, **urlopen_kw):
        return self._request_encode_url('HEAD', url, fields=fields,
                                        **urlopen_kw)

    def delete_url(self, url, fields=None, **urlopen_kw):
        return self._request_encode_url('DELETE', url, fields=fields,
                                        **urlopen_kw)

    # body-encoded methods:

    def post_url(self, url, fields=None, headers=None, **urlopen_kw):
        return self._request_encode_body('POST', url, fields=fields,
                                         headers=headers,
                                         **urlopen_kw)

    def put_url(self, url, fields=None, headers=None, **urlopen_kw):
        return self._request_encode_body('PUT', url, fields=fields,
                                         headers=headers,
                                         **urlopen_kw)

    def patch_url(self, url, fields=None, headers=None, **urlopen_kw):
        return self._request_encode_body('PATCH', url, fields=fields,
                                         headers=headers,
                                         **urlopen_kw)

    _encode_url_methods = {
        'DELETE': delete_url,
        'GET': get_url,
        'HEAD': head_url,
    }

    _encode_body_methods = {
        'PATCH': patch_url,
        'POST': post_url,
        'PUT': put_url,
    }

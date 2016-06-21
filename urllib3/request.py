from __future__ import absolute_import

import logging

from .filepost import encode_multipart_formdata
from .exceptions import MaxRetryError
from .util.url import parse_url

from .packages.six.moves.urllib.parse import urlencode
from .packages.six.moves.urllib.parse import urljoin

__all__ = ['RequestMethods', 'Request']

log = logging.getLogger(__name__)


class Request(object):
    """
    Implements some of the interface of the stdlib Request object, but does it
    in our own way, so we're free from the constrains of urllib/urllib2
    """
    def __init__(self, method, url, headers=None, body=None, redirected_by=None):
        self.method = method
        self.url = url
        self.headers = headers or dict()
        self.body = body
        self.redirect_source = redirected_by
        self.kwargs = {}
        if self.has_header('Cookie'):
            self._cookies = self.get_header('Cookie').split('; ')
        else:
            self._cookies = []

    def add_cookies(self, *cookies):
        """
        Add cookies to the request, updating the Cookie header with each one.
        """
        for each in cookies:
            if each not in self._cookies:
                self._cookies.append(each)
        self.headers['Cookie'] = '; '.join(self._cookies)

    def get_full_url(self):
        """
        Get the request's full URL
        """
        return self.full_url

    @property
    def full_url(self):
        return self.url

    @property
    def host(self):
        return parse_url(self.url).host

    @property
    def type(self):
        return parse_url(self.url).scheme

    @property
    def unverifiable(self):
        return self.is_unverifiable()

    @property
    def origin_req_host(self):
        return parse_url(self.redirect_source).host or self.host

    def is_unverifiable(self):
        """
        This determines if the request is "verifiable" for cookie handling
        purposes - generally, a request is "verifiable" if the user has an
        opportunity to change the URL pre-request. In the context of urllib3,
        this is generally not the case only if a redirect happened.
        """
        if self.redirect_source and self.redirect_source != self.url:
            return True
        else:
            return False

    def has_header(self, header):
        return header in self.headers

    def get_header(self, header, default=None):
        return self.headers.get(header, default)

    def get_kwargs(self):
        """
        Gives us a set of keywords we can **expand into urlopen
        """
        kw = {
            'method': self.method,
            'url': self.url,
            'headers': self.headers,
            'body': self.body
        }
        kw.update(self.kwargs)
        return kw


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

    def request(self, method, url, fields=None, headers=None, **urlopen_kw):
        """
        Make a request using :meth:`urlopen` with the appropriate encoding of
        ``fields`` based on the ``method`` used.

        This is a convenience method that requires the least amount of manual
        effort. It can be used in most situations, while still having the
        option to drop down to more specific methods when necessary, such as
        :meth:`request_encode_url`, :meth:`request_encode_body`,
        or even the lowest level :meth:`urlopen`.
        """
        method = method.upper()

        if method in self._encode_url_methods:
            return self.request_encode_url(method, url, fields=fields,
                                           headers=headers,
                                           **urlopen_kw)
        else:
            return self.request_encode_body(method, url, fields=fields,
                                            headers=headers,
                                            **urlopen_kw)

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

    def redirect(self, response, method, retries, **kwargs):
        """
        Abstracts the redirect process to be used from any :class:`RequestMethods` object
        """
        url = kwargs.pop('url', '')
        redirect_location = urljoin(url, response.get_redirect_location())
        method = retries.redirect_method(method, response.status)
        try:
            pool = kwargs.pop('pool', self)
            retries = retries.increment(method, url, response=response, _pool=pool)
        except MaxRetryError:
            if retries.raise_on_redirect:
                # Release the connection for this response, since we're not
                # returning it to be released manually.
                response.release_conn()
                raise
            return response

        log.info("Redirecting %s -> %s", url, redirect_location)
        return self.urlopen(method=method, url=redirect_location, retries=retries, **kwargs)

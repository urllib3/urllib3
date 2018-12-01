from __future__ import absolute_import
import email.utils
import mimetypes

from .packages import six


def guess_content_type(filename, default='application/octet-stream'):
    """
    Guess the "Content-Type" of a file.

    :param filename:
        The filename to guess the "Content-Type" of using :mod:`mimetypes`.
    :param default:
        If no "Content-Type" can be guessed, default to `default`.
    """
    if filename:
        return mimetypes.guess_type(filename)[0] or default
    return default


def format_header_param_rfc2231(name, value):
    """
    Helper function to format and quote a single header parameter.

    Particularly useful for header parameters which might contain
    non-ASCII values, like file names. This follows RFC 2231, as
    suggested by RFC 2388 Section 4.4.

    :param name:
        The name of the parameter, a string expected to be ASCII only.
    :param value:
        The value of the parameter, provided as a unicode string.
    :ret:
        An RFC-2231-formatted unicode string.
    """
    if not any(ch in value for ch in '"\\\r\n'):
        result = u'%s="%s"' % (name, value)
        try:
            result.encode('ascii')
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        else:
            return result

    if not six.PY3:  # Python 2:
        value = value.encode('utf-8')

    # encode_rfc2231 accepts an encoded string and returns an ascii-encoded
    # string in Python 2 but accepts and returns unicode strings in Python 3
    value = email.utils.encode_rfc2231(value, 'utf-8')
    value = '%s*=%s' % (name, value)

    if not six.PY3:  # Python 2:
        value = value.decode('utf-8')

    return value


def format_header_param_html5(name, value):
    """
    Helper function to format and quote a single header parameter.

    Particularly useful for header parameters which might contain
    non-ASCII values, like file names. This follows the HTML5 Working Draft
    Section 4.10.22.7 (http://w3c.github.io/html/sec-forms.html#multipart-form-data)

    :param name:
        The name of the parameter, a string expected to be ASCII only.
    :param value:
        The value of the parameter, provided as a unicode string.
    :ret:
        A unicode string, stripped of troublesome characters.
    """

    value = value.replace(u'\\', u'\\\\').replace(u'"', u'\\"')
    value = value.replace(u'\r', u' ').replace(u'\n', u' ')

    return u'%s="%s"' % (name, value)


format_header_param = format_header_param_rfc2231  # For backwards-compatibility


class RequestField(object):
    header_formatter = staticmethod(format_header_param_html5)

    """
    A data container for request body parameters.

    :param name:
        The name of this request field. Must be unicode.
    :param data:
        The data/value body.
    :param filename:
        An optional filename of the request field. Must be unicode.
    :param headers:
        An optional dict-like object of headers to initially use for the field.
    """
    def __init__(self, name, data, filename=None, headers=None):
        self._name = name
        self._filename = filename
        self.data = data
        self.headers = {}
        if headers:
            self.headers = dict(headers)

    @classmethod
    def from_tuples(cls, fieldname, value):
        """
        A :class:`~urllib3.fields.RequestField` factory from old-style tuple parameters.

        Supports constructing :class:`~urllib3.fields.RequestField` from
        parameter of key/value strings AND key/filetuple. A filetuple is a
        (filename, data, MIME type) tuple where the MIME type is optional.
        For example::

            'foo': 'bar',
            'fakefile': ('foofile.txt', 'contents of foofile'),
            'realfile': ('barfile.txt', open('realfile').read()),
            'typedfile': ('bazfile.bin', open('bazfile').read(), 'image/jpeg'),
            'nonamefile': 'contents of nonamefile field',

        Field names and filenames must be unicode.
        """
        if isinstance(value, tuple):
            if len(value) == 3:
                filename, data, content_type = value
            else:
                filename, data = value
                content_type = guess_content_type(filename)
        else:
            filename = None
            content_type = None
            data = value

        request_param = cls(fieldname, data, filename=filename)
        request_param.make_multipart(content_type=content_type)

        return request_param

    def _render_part(self, name, value):
        """
        Overridable helper function to format a single header parameter.

        :param name:
            The name of the parameter, a string expected to be ASCII only.
        :param value:
            The value of the parameter, provided as a unicode string.
        """

        return type(self).header_formatter(name, value)

    def _render_parts(self, header_parts):
        """
        Helper function to format and quote a single header.

        Useful for single headers that are composed of multiple items. E.g.,
        'Content-Disposition' fields.

        :param header_parts:
            A sequence of (k, v) tuples or a :class:`dict` of (k, v) to format
            as `k1="v1"; k2="v2"; ...`.
        """
        parts = []
        iterable = header_parts
        if isinstance(header_parts, dict):
            iterable = header_parts.items()

        for name, value in iterable:
            if value is not None:
                parts.append(self._render_part(name, value))

        return u'; '.join(parts)

    def render_headers(self):
        """
        Renders the headers for this request field.
        """
        lines = []

        sort_keys = ['Content-Disposition', 'Content-Type', 'Content-Location']
        for sort_key in sort_keys:
            if self.headers.get(sort_key, False):
                lines.append(u'%s: %s' % (sort_key, self.headers[sort_key]))

        for header_name, header_value in self.headers.items():
            if header_name not in sort_keys:
                if header_value:
                    lines.append(u'%s: %s' % (header_name, header_value))

        lines.append(u'\r\n')
        return u'\r\n'.join(lines)

    def make_multipart(self, content_disposition=None, content_type=None,
                       content_location=None):
        """
        Makes this request field into a multipart request field.

        This method overrides "Content-Disposition", "Content-Type" and
        "Content-Location" headers to the request parameter.

        :param content_type:
            The 'Content-Type' of the request body.
        :param content_location:
            The 'Content-Location' of the request body.

        """
        self.headers['Content-Disposition'] = content_disposition or u'form-data'
        self.headers['Content-Disposition'] += u'; '.join([
            u'', self._render_parts(
                ((u'name', self._name), (u'filename', self._filename))
            )
        ])
        self.headers['Content-Type'] = content_type
        self.headers['Content-Location'] = content_location

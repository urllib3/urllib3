# urllib3/fields.py
# Copyright 2008-2013 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

import mimetypes


def guess_content_type(filename, default='application/octet-stream'):
    """
    Guess the "Content-Type" of a file.

    :param filename:
        The filename to guess the "Content-Type" of using :mod:`mimetimes`.
    :param default:
        If no "Content-Type" can be guessed, default to `default`.
    """
    if filename:
        return mimetypes.guess_type(filename)[0] or default
    return default


class RequestField(object):
    """
    A data container for request body parameters.

    :param name:
        The name of this request field.
    :param data:
        The data/value body.
    :param filename:
        An optional filename of the request field.
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

      Supports constructing :class:`~urllib3.fields.RequestField` from parameter
      of key/value strings AND key/filetuple. A filetuple is a (filename, data, MIME type)
      tuple where the MIME type is optional. For example: ::

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

    def _render_parts(self, header_parts):
      """
      Helper function to format and quote a single header.

      Useful for single headers that are composed of multiple items. E.g.,
      'Content-Disposition' fields.

      :param header_parts:
          A sequence of (k, v) typles or a :class:`dict` of (k, v) to format as
          `k1="v1"; k2="v2"; ...`.
      """
      parts = []
      iterable = header_parts
      if isinstance(header_parts, dict):
          iterable = header_parts.items()

      for name, value in iterable:
          if value:
              parts.append('%s="%s"' % (name, value))
      return '; '.join(parts)

    def make_multipart(self, content_disposition=None, content_type=None, content_location=None):
      """
      Makes this request field into a multipart request field.

      This method overrides "Content-Disposition", "Content-Type" and
      "Content-Location" headers to the request parameter.

      :param content_type:
          The 'Content-Type' of the request body.
      :param content_location:
          The 'Content-Location' of the request body.

      """
      self.headers['Content-Disposition'] = content_disposition or 'form-data'
      self.headers['Content-Disposition'] += '; '.join(['', self._render_parts((('name', self._name), ('filename', self._filename)))])
      self.headers['Content-Type'] = content_type
      self.headers['Content-Location'] = content_location

    def render_headers(self):
      """
      Renders the headers for this request field.
      """
      lines = []
      sort_keys = ['Content-Disposition', 'Content-Type', 'Content-Location']
      for sort_key in sort_keys:
          if self.headers.get(sort_key, False):
              lines.append('%s: %s' % (sort_key, self.headers[sort_key]))
      for header_name, header_value in self.headers.items():
          if header_name not in sort_keys:
              if header_value:
                  lines.append('%s: %s' % (header_name, header_value))
      lines.append('\r\n')
      return '\r\n'.join(lines)

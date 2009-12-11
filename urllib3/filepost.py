import httplib

import mimetools, mimetypes

ENCODE_TEMPLATE= """--%(boundary)s
Content-Disposition: form-data; name="%(name)s"

%(value)s
""".replace('\n','\r\n')

ENCODE_TEMPLATE_FILE = """--%(boundary)s
Content-Disposition: form-data; name="%(name)s"; filename="%(filename)s"
Content-Type: %(contenttype)s

%(value)s
""".replace('\n','\r\n')

# TODO: is replace('\n', '\r\n') going to cause problems on other platforms?
# Are we better off building a list of strings and doing '\r\n'.join(body)?

def get_content_type(filename):
    return mimetypes.guess_type(filename)[0] or 'application/octet-stream'

def encode_multipart_formdata(fields):
    """
    Given a dictionary field parameters, returns the HTTP request body and the
    content_type (which includes the boundary string), to be used with an
    httplib-like call.

    Normal key/value items are treated as regular parameters, but key/tuple
    items are treated as files, where a value tuple is a (filename, data) tuple.

    For example:

    fields = {
        'foo': 'bar',
        'foofile': ('foofile.txt', 'contents of foofile'),
    }

    body, content_type = encode_multipart_formdata(fields)
    """

    BOUNDARY = mimetools.choose_boundary()

    body = ""

    # NOTE: Every non-binary possibly-unicode variable must be casted to str()
    # because if a unicode value pollutes the `body` string, then all of body
    # will become unicode. Appending a binary file string to a unicode string
    # will cast the binary data to unicode, which will raise an encoding
    # exception. Long story short, we want to stick to plain strings.
    # This is not ideal, but if anyone has a better method, I'd love to hear it.

    for key, value in fields.iteritems():
        if isinstance(value, tuple):
            filename, value = value
            body += ENCODE_TEMPLATE_FILE % {
                        'boundary': BOUNDARY,
                        'name': str(key),
                        'value': str(value),
                        'filename': str(filename),
                        'contenttype': str(get_content_type(filename))
                    }
        else:
            body += ENCODE_TEMPLATE % {
                        'boundary': BOUNDARY,
                        'name': str(key),
                        'value': str(value)
                    }

    body += '--%s--\n\r' % BOUNDARY
    content_type = 'multipart/form-data; boundary=%s' % BOUNDARY

    return body, content_type

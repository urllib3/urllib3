from __future__ import print_function

import collections
import gzip
import json
import logging
import sys
import time
import zlib

from io import BytesIO
from tornado.wsgi import HTTPRequest

try:
    from urllib.parse import urlsplit
except ImportError:
    from urlparse import urlsplit

log = logging.getLogger(__name__)


class Response(object):
    def __init__(self, body='', status='200 OK', headers=None):
        if not isinstance(body, bytes):
            body = body.encode('utf8')

        self.body = body
        self.status = status
        self.headers = headers or [("Content-type", "text/plain")]

    def __call__(self, environ, start_response):
        start_response(self.status, self.headers)
        return [self.body]


class WSGIHandler(object):
    pass


class TestingApp(WSGIHandler):
    """
    Simple app that performs various operations, useful for testing an HTTP
    library.

    Given any path, it will attempt to load a corresponding local method if
    it exists. Status code 200 indicates success, 400 indicates failure. Each
    method has its own conditions for success/failure.
    """
    def __call__(self, environ, start_response):
        """ Call the correct method in this class based on the incoming URI """
        req = HTTPRequest(environ)

        req.params = {}
        for k, v in req.arguments.items():
            req.params[k] = next(iter(v))

        path = req.path[:]
        if not path.startswith('/'):
            path = urlsplit(path).path

        target = path[1:].replace('/', '_')
        method = getattr(self, target, self.index)
        resp = method(req)

        if dict(resp.headers).get('Connection') == 'close':
            # FIXME: Can we kill the connection somehow?
            pass

        return resp(environ, start_response)

    def index(self, _request):
        "Render simple message"
        return Response("Dummy server!")

    def source_address(self, request):
        """Return the requester's IP address."""
        return Response(request.remote_ip)

    def set_up(self, request):
        test_type = request.params.get('test_type')
        test_id = request.params.get('test_id')
        if test_id:
            print('\nNew test %s: %s' % (test_type, test_id))
        else:
            print('\nNew test %s' % test_type)
        return Response("Dummy server is ready!")

    def specific_method(self, request):
        "Confirm that the request matches the desired method type"
        method = request.params.get('method')
        if method and not isinstance(method, str):
            method = method.decode('utf8')

        if request.method != method:
            return Response("Wrong method: %s != %s" %
                            (method, request.method), status='400 Bad Request')
        return Response()

    def upload(self, request):
        "Confirm that the uploaded file conforms to specification"
        # FIXME: This is a huge broken mess
        param = request.params.get('upload_param', 'myfile').decode('ascii')
        filename = request.params.get('upload_filename', '').decode('utf-8')
        size = int(request.params.get('upload_size', '0'))
        files_ = request.files.get(param)

        if len(files_) != 1:
            return Response("Expected 1 file for '%s', not %d" %(param, len(files_)),
                                                    status='400 Bad Request')
        file_ = files_[0]

        data = file_['body']
        if int(size) != len(data):
            return Response("Wrong size: %d != %d" %
                            (size, len(data)), status='400 Bad Request')

        if filename != file_['filename']:
            return Response("Wrong filename: %s != %s" %
                            (filename, file_.filename),
                            status='400 Bad Request')

        return Response()

    def redirect(self, request):
        "Perform a redirect to ``target``"
        target = request.params.get('target', '/')
        headers = [('Location', target)]
        return Response(status='303 See Other', headers=headers)

    def keepalive(self, request):
        if request.params.get('close', b'0') == b'1':
            headers = [('Connection', 'close')]
            return Response('Closing', headers=headers)

        headers = [('Connection', 'keep-alive')]
        return Response('Keeping alive', headers=headers)

    def sleep(self, request):
        "Sleep for a specified amount of ``seconds``"
        seconds = float(request.params.get('seconds', '1'))
        time.sleep(seconds)
        return Response()

    def echo(self, request):
        "Echo back the params"
        if request.method == 'GET':
            return Response(request.query)

        return Response(request.body)

    def encodingrequest(self, request):
        "Check for UA accepting gzip/deflate encoding"
        data = b"hello, world!"
        encoding = request.headers.get('Accept-Encoding', '')
        headers = None
        if encoding == 'gzip':
            headers = [('Content-Encoding', 'gzip')]
            file_ = BytesIO()
            zipfile = gzip.GzipFile('', mode='w', fileobj=file_)
            zipfile.write(data)
            zipfile.close()
            data = file_.getvalue()
        elif encoding == 'deflate':
            headers = [('Content-Encoding', 'deflate')]
            data = zlib.compress(data)
        elif encoding == 'garbage-gzip':
            headers = [('Content-Encoding', 'gzip')]
            data = 'garbage'
        elif encoding == 'garbage-deflate':
            headers = [('Content-Encoding', 'deflate')]
            data = 'garbage'
        return Response(data, headers=headers)

    def headers(self, request):
        return Response(json.dumps(request.headers))

    def successful_retry(self, request):
        """ Handler which will return an error and then success

        It's not currently very flexible as the number of retries is hard-coded.
        """
        test_name = request.headers.get('test-name', None)
        if not test_name:
            return Response("test-name header not set",
                            status="400 Bad Request")

        if not hasattr(self, 'retry_test_names'):
            self.retry_test_names = collections.defaultdict(int)
        self.retry_test_names[test_name] += 1

        if self.retry_test_names[test_name] >= 2:
            return Response("Retry successful!")
        else:
            return Response("need to keep retrying!", status="418 I'm A Teapot")

    def shutdown(self, request):
        sys.exit()


# RFC2231-aware replacement of internal tornado function
def _parse_header(line):
    r"""Parse a Content-type like header.

    Return the main content-type and a dictionary of options.

    >>> d = _parse_header("CD: fd; foo=\"bar\"; file*=utf-8''T%C3%A4st")[1]
    >>> d['file'] == 'T\u00e4st'
    True
    >>> d['foo']
    'bar'
    """
    import tornado.httputil
    import email.utils
    from urllib3.packages import six
    if not six.PY3:
        line = line.encode('utf-8')
    parts = tornado.httputil._parseparam(';' + line)
    key = next(parts)
    # decode_params treats first argument special, but we already stripped key
    params = [('Dummy', 'value')]
    for p in parts:
        i = p.find('=')
        if i >= 0:
            name = p[:i].strip().lower()
            value = p[i + 1:].strip()
            params.append((name, value))
    params = email.utils.decode_params(params)
    params.pop(0) # get rid of the dummy again
    pdict = {}
    for name, value in params:
        value = email.utils.collapse_rfc2231_value(value)
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        pdict[name] = value
    return key, pdict

# TODO: make the following conditional as soon as we know a version
#       which does not require this fix.
#       See https://github.com/facebook/tornado/issues/868
if True:
    import tornado.httputil
    tornado.httputil._parse_header = _parse_header

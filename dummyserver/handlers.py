from __future__ import print_function

import gzip
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

    Given any path, it will attempt to convert it will load a corresponding
    local method if it exists. Status code 200 indicates success, 400 indicates
    failure. Each method has its own conditions for success/failure.
    """
    def __call__(self, environ, start_response):
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
                            (method, request.method), status='400')
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
                                                    status='400')
        file_ = files_[0]

        data = file_['body']
        if int(size) != len(data):
            return Response("Wrong size: %d != %d" %
                            (size, len(data)), status='400')

        if filename != file_['filename']:
            return Response("Wrong filename: %s != %s" %
                            (filename, file_.filename), status='400')

        return Response()

    def redirect(self, request):
        "Perform a redirect to ``target``"
        target = request.params.get('target', '/')
        headers = [('Location', target)]
        return Response(status='303', headers=headers)

    def keepalive(self, request):
        if request.params.get('close', '0') == '1':
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
        if 'gzip' in encoding:
            headers = [('Content-Encoding', 'gzip')]
            file_ = BytesIO()
            gzip.GzipFile('', mode='w', fileobj=file_).write(data)
            data = file_.getvalue()
        elif 'deflate' in encoding:
            headers = [('Content-Encoding', 'deflate')]
            data = zlib.compress(data)
        return Response(data, headers=headers)

    def shutdown(self, request):
        sys.exit()

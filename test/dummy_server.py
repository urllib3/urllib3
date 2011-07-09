#!/usr/bin/env python

"""
Dummy server used for unit testing
"""

import gzip
import time
import zlib

from cgi import FieldStorage
from StringIO import StringIO
from webob import Request, Response, exc


class TestingApp(object):
    """
    Simple app that performs various operations, useful for testing an HTTP
    library.

    Given any path, it will attempt to convert it will load a corresponding
    local method if it exists. Status code 200 indicates success, 400 indicates
    failure. Each method has its own conditions for success/failure.
    """
    def __call__(self, environ, start_response):
        req = Request(environ)
        target = req.path_info[1:].replace('/', '_')
        method = getattr(self, target, self.index)
        resp = method(req)
        return resp(environ, start_response)

    def index(self, request):
        "Render simple message"
        return Response("Dummy server!")

    def specific_method(self, request):
        "Confirm that the request matches the desired method type"
        method = request.params.get('method')
        if request.method != method:
            return Response("Wrong method: %s != %s" %
                            (method, request.method), status='400')
        return Response()

    def upload(self, request):
        "Confirm that the uploaded file conforms to specification"
        param = request.params.get('upload_param', 'myfile')
        filename = request.params.get('upload_filename', '')
        size = int(request.params.get('upload_size', '0'))
        file = request.params.get(param)

        if not isinstance(file, FieldStorage):
            return Response("'%s' is not a file: %r" %
                            (param, file), status='400')

        data = file.value
        if int(size) != len(data):
            return Response("Wrong size: %d != %d" %
                            (size, len(data)), status='400')

        if filename != file.filename:
            return Response("Wrong filename: %s != %s" %
                            (filename, file.filename), status='400')

        return Response()

    def redirect(self, request):
        "Perform a redirect to ``target``"
        target = request.params.get('target', '/')
        return exc.HTTPSeeOther(location=target)

    def keepalive(self, request):
        if request.params.get('close', '0') == '1':
            response = Response('Closing')
            response.headers['Connection'] = 'close'
        else:
            response = Response('Keeping alive')
            response.headers['Connection'] = 'keep-alive'
        return response

    def sleep(self, request):
        "Sleep for a specified amount of ``seconds``"
        seconds = float(request.params.get('seconds', '1'))
        time.sleep(seconds)
        return Response()

    def echo(self, request):
        """Echo back the params"""
        return Response("%s" % request.body)

    def encodingrequest(self, request):
        "Check for UA accepting gzip/defkate encoding"
        data = "hello, world!"
        encoding = request.headers.get('Accept-Encoding', '')
        headers = {}
        if 'gzip' in encoding:
            headers = {'Content-Encoding': 'gzip'}
            file = StringIO()
            gzip.GzipFile('', mode='w', fileobj=file).write(data)
            data = file.getvalue()
        elif 'deflate' in encoding:
            headers = {'Content-Encoding': 'deflate'}
            data = zlib.compress(data)
        return Response(data, headers=headers)


def make_server(HOST="localhost", PORT=8081):
    app = TestingApp()
    from wsgiref.simple_server import make_server

    print 'Creating server on http://%s:%s' % (HOST, PORT)
    return make_server(HOST, PORT, app)


if __name__ == '__main__':
    if __debug__:
        # BaseHTTPServer raises an assertion error with __debug__
        # enabled when responding with a "Connection" header
        from sys import argv
        print "The Keep-alive test will fail because __debug__ is active!"
        print ""
        print "To properly test keep-alive, re-run in optimized mode:"
        print ""
        print "  $ python -O %s" % argv[0]
        print ""
    httpd = make_server()
    httpd.serve_forever()

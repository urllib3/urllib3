#!/usr/bin/env python

"""
Dummy server used for unit testing.
"""

import gzip
import logging
import sys
import os
import time
import zlib

from cgi import FieldStorage
from StringIO import StringIO
from webob import Request, Response, exc

from eventlet import wsgi
import eventlet
import unittest


log = logging.getLogger(__name__)

CERTS_PATH = os.path.join(os.path.dirname(__file__), 'certs')
CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'server.crt'),
    'keyfile': os.path.join(CERTS_PATH, 'server.key'),
}


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

        if resp.headers.get('Connection') == 'close':
            # Can we kill the connection somehow?
            pass

        return resp(environ, start_response)

    def index(self, _request):
        "Render simple message"
        return Response("Dummy server!")

    def set_up(self, request):
        test_type = request.params.get('test_type')
        test_id = request.params.get('test_id')
        if test_id:
            print '\nNew test %s: %s' % (test_type, test_id)
        else:
            print '\nNew test %s' % test_type
        return Response("Dummy server is ready!")

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
        file_ = request.params.get(param)

        if not isinstance(file_, FieldStorage):
            return Response("'%s' is not a file: %r" %
                            (param, file_), status='400')

        data = file_.value
        if int(size) != len(data):
            return Response("Wrong size: %d != %d" %
                            (size, len(data)), status='400')

        if filename != file_.filename:
            return Response("Wrong filename: %s != %s" %
                            (filename, file_.filename), status='400')

        return Response()

    def redirect(self, request):
        "Perform a redirect to ``target``"
        target = request.params.get('target', '/')
        return exc.HTTPSeeOther(location=target)

    def keepalive(self, request):
        if request.params.get('close', '0') == '1':
            response = Response('Closing')
            response.headers['Connection'] = 'close'
            return response

        response = Response('Keeping alive')
        response.headers['Connection'] = 'keep-alive'
        return response

    def sleep(self, request):
        "Sleep for a specified amount of ``seconds``"
        seconds = float(request.params.get('seconds', '1'))
        time.sleep(seconds)
        return Response()

    def echo(self, request):
        "Echo back the params"
        if request.method == 'GET':
            return Response(request.query_string)

        return Response(request.body)

    def encodingrequest(self, request):
        "Check for UA accepting gzip/deflate encoding"
        data = "hello, world!"
        encoding = request.headers.get('Accept-Encoding', '')
        headers = {}
        if 'gzip' in encoding:
            headers = {'Content-Encoding': 'gzip'}
            file_ = StringIO()
            gzip.GzipFile('', mode='w', fileobj=file_).write(data)
            data = file_.getvalue()
        elif 'deflate' in encoding:
            headers = {'Content-Encoding': 'deflate'}
            data = zlib.compress(data)
        return Response(data, headers=headers)

    def shutdown(self, request):
        sys.exit()


def make_server(host="localhost", port=8081, scheme='http', **kw):
    socket = eventlet.listen((host, port))

    if scheme == 'https':
        socket = eventlet.wrap_ssl(socket, server_side=True, **CERTS)

    dummy_log_fp = open(os.devnull, 'a')

    return wsgi.server(socket, TestingApp(), log=dummy_log_fp, **kw)


def make_server_thread(**kw):
    import threading
    t = threading.Thread(target=make_server, kwargs=kw)
    t.start()
    return t


class HTTPDummyServerTestCase(unittest.TestCase):
    scheme = 'http'
    host = 'localhost'
    port = 18081

    @classmethod
    def setUpClass(cls):
        cls.server_thread = make_server_thread(host=cls.host, port=cls.port,
                                               scheme=cls.scheme)

        # TODO: Loop-check here instead
        import time
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        import urllib # Yup, that's right.
        try:
            urllib.urlopen(cls.scheme + '://' + cls.host + ':' + str(cls.port) + '/shutdown')
        except IOError:
            pass
        cls.server_thread.join()


class HTTPSDummyServerTestCase(HTTPDummyServerTestCase):
    scheme = 'https'
    host = 'localhost'
    port = 18082


if __name__ == '__main__':
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler(sys.stderr))

    from urllib3 import get_host

    url = "http://localhost:8081"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    scheme, host, port = get_host(url)
    make_server(scheme=scheme, host=host, port=port)

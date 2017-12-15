from __future__ import print_function

import collections
import contextlib
import gzip
import json
import logging
import sys
import time
import zlib

from io import BytesIO
from tornado.web import RequestHandler
from tornado import httputil
from datetime import datetime
from datetime import timedelta

from urllib3.packages.six.moves.http_client import responses
from urllib3.packages.six.moves.urllib.parse import urlsplit

log = logging.getLogger(__name__)


class Response(object):
    def __init__(self, body='', status='200 OK', headers=None):
        self.body = body
        self.status = status
        self.headers = headers or [("Content-type", "text/plain")]

    def __call__(self, request_handler):
        status, reason = self.status.split(' ', 1)
        request_handler.set_status(int(status), reason)
        for header, value in self.headers:
            request_handler.add_header(header, value)

        # chunked
        if isinstance(self.body, list):
            for item in self.body:
                if not isinstance(item, bytes):
                    item = item.encode('utf8')
                request_handler.write(item)
                request_handler.flush()
        else:
            body = self.body
            if not isinstance(body, bytes):
                body = body.encode('utf8')

            request_handler.write(body)


RETRY_TEST_NAMES = collections.defaultdict(int)


class TestingApp(RequestHandler):
    """
    Simple app that performs various operations, useful for testing an HTTP
    library.

    Given any path, it will attempt to load a corresponding local method if
    it exists. Status code 200 indicates success, 400 indicates failure. Each
    method has its own conditions for success/failure.
    """
    def get(self):
        """ Handle GET requests """
        self._call_method()

    def post(self):
        """ Handle POST requests """
        self._call_method()

    def put(self):
        """ Handle PUT requests """
        self._call_method()

    def options(self):
        """ Handle OPTIONS requests """
        self._call_method()

    def head(self):
        """ Handle HEAD requests """
        self._call_method()

    def _call_method(self):
        """ Call the correct method in this class based on the incoming URI """
        req = self.request
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

        resp(self)

    def index(self, _request):
        "Render simple message"
        return Response("Dummy server!")

    def certificate(self, request):
        """Return the requester's certificate."""
        cert = request.get_ssl_certificate()
        subject = dict()
        if cert is not None:
            subject = dict((k, v) for (k, v) in [y for z in cert['subject']
                                                 for y in z])
        return Response(json.dumps(subject))

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
        param = request.params.get('upload_param', b'myfile').decode('ascii')
        filename = request.params.get('upload_filename', b'').decode('utf-8')
        size = int(request.params.get('upload_size', '0'))
        files_ = request.files.get(param)

        if len(files_) != 1:
            return Response("Expected 1 file for '%s', not %d" % (param, len(files_)),
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
        status = request.params.get('status', '303 See Other')
        if len(status) == 3:
            status = '%s Redirect' % status.decode('latin-1')

        headers = [('Location', target)]
        return Response(status=status, headers=headers)

    def not_found(self, request):
        return Response('Not found', status='404 Not Found')

    def multi_redirect(self, request):
        "Performs a redirect chain based on ``redirect_codes``"
        codes = request.params.get('redirect_codes', b'200').decode('utf-8')
        head, tail = codes.split(',', 1) if "," in codes else (codes, None)
        status = "{0} {1}".format(head, responses[int(head)])
        if not tail:
            return Response("Done redirecting", status=status)

        headers = [('Location', '/multi_redirect?redirect_codes=%s' % tail)]
        return Response(status=status, headers=headers)

    def keepalive(self, request):
        if request.params.get('close', b'0') == b'1':
            headers = [('Connection', 'close')]
            return Response('Closing', headers=headers)

        headers = [('Connection', 'keep-alive')]
        return Response('Keeping alive', headers=headers)

    def sleep(self, request):
        "Sleep for a specified amount of ``seconds``"
        # DO NOT USE THIS, IT'S DEPRECATED.
        # FIXME: Delete this once appengine tests are fixed to not use this handler.
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
            with contextlib.closing(gzip.GzipFile('', mode='w', fileobj=file_)) as zipfile:
                zipfile.write(data)
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
        return Response(json.dumps(dict(request.headers)))

    def successful_retry(self, request):
        """ Handler which will return an error and then success

        It's not currently very flexible as the number of retries is hard-coded.
        """
        test_name = request.headers.get('test-name', None)
        if not test_name:
            return Response("test-name header not set",
                            status="400 Bad Request")

        RETRY_TEST_NAMES[test_name] += 1

        if RETRY_TEST_NAMES[test_name] >= 2:
            return Response("Retry successful!")
        else:
            return Response("need to keep retrying!", status="418 I'm A Teapot")

    def chunked(self, request):
        return Response(['123'] * 4)

    def chunked_gzip(self, request):
        chunks = []
        compressor = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)

        for uncompressed in [b'123'] * 4:
            chunks.append(compressor.compress(uncompressed))

        chunks.append(compressor.flush())

        return Response(chunks, headers=[('Content-Encoding', 'gzip')])

    def nbytes(self, request):
        length = int(request.params.get('length'))
        data = b'1' * length
        return Response(
            data,
            headers=[('Content-Type', 'application/octet-stream')])

    def status(self, request):
        status = request.params.get("status", "200 OK")

        return Response(status=status)

    def retry_after(self, request):
        if datetime.now() - self.application.last_req < timedelta(seconds=1):
            status = request.params.get("status", b"429 Too Many Requests")
            return Response(
                    status=status.decode('utf-8'),
                    headers=[('Retry-After', '1')])

        self.application.last_req = datetime.now()

        return Response(status="200 OK")

    def redirect_after(self, request):
        "Perform a redirect to ``target``"
        date = request.params.get('date')
        if date:
            retry_after = str(httputil.format_timestamp(
                    datetime.fromtimestamp(float(date))))
        else:
            retry_after = '1'
        target = request.params.get('target', '/')
        headers = [('Location', target), ('Retry-After', retry_after)]
        return Response(status='303 See Other', headers=headers)

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
    params.pop(0)  # get rid of the dummy again
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

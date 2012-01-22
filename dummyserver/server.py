#!/usr/bin/env python

"""
Dummy server used for unit testing.
"""

import logging
import os
import sys
import threading

from dummyserver.app import TestingApp


log = logging.getLogger(__name__)

CERTS_PATH = os.path.join(os.path.dirname(__file__), 'certs')
DEFAULT_CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'server.crt'),
    'keyfile': os.path.join(CERTS_PATH, 'server.key'),
}
DEFAULT_CA = os.path.join(CERTS_PATH, 'cacert.pem')
DEFAULT_CA_BAD = os.path.join(CERTS_PATH, 'client_bad.pem')


def eventlet_server(host="localhost", port=8081, scheme='http', certs=None, **kw):
    import eventlet
    import eventlet.wsgi

    certs = certs or {}

    socket = eventlet.listen((host, port))

    if scheme == 'https':
        socket = eventlet.wrap_ssl(socket, server_side=True, **certs)

    dummy_log_fp = open(os.devnull, 'a')

    return eventlet.wsgi.server(socket, TestingApp(), log=dummy_log_fp, **kw)

class EventletServerThread(threading.Thread):
    def __init__(self, host, port, scheme='http', certs=None, **kw):
        import eventlet
        import eventlet.wsgi  # We need to check the imports in the main thread
        
        threading.Thread.__init__(self)
        self.host = host
        self.port = port
        self.scheme = scheme
        self.certs = certs
        self.kw = kw
    
    def run(self):
        eventlet_server(self.host, self.port, self.scheme, self.certs, **self.kw)
    
    def stop(self):
        import urllib # Yup, that's right.
        try:
            urllib.urlopen(self.scheme + '://' + self.host + ':' + str(self.port) + '/shutdown')
        except IOError:
            pass
        self.join()

def tornado_server(host, port, scheme='http', certs=None, **kw):
    import tornado.wsgi
    import tornado.httpserver
    container = tornado.wsgi.WSGIContainer(TestingApp())
    if scheme == 'https':
        http_server = tornado.httpserver.HTTPServer(container, ssl_options=certs)
    else:
        http_server = tornado.httpserver.HTTPServer(container)
    http_server.listen(port)
    return http_server
    
class TornadoServerThread(threading.Thread):
    def __init__(self, host, port, **kw):
        import tornado.wsgi
        threading.Thread.__init__(self)
        self.host = host
        self.port = port
        self.kw = kw
    
    def run(self):
        import tornado.ioloop
        self.server = tornado_server(self.host, self.port, **self.kw)
        self.ioloop = tornado.ioloop.IOLoop.instance()
        self.ioloop.start()
    
    def stop(self):
        self.server.stop()
        self.ioloop.stop()
        #self.ioloop.close()
        import time
        time.sleep(0.1)

def simple_server(host="localhost", port=8081, **kw):
    from wsgiref.simple_server import make_server
    return make_server(host, port, TestingApp())

class SimpleServerThread(threading.Thread):
    def __init__(self, host, port, **kw):
        threading.Thread.__init__(self)
        self.server = simple_server(host, port, **kw)
    
    def run(self):
        self.server.serve_forever()
    
    def stop(self):
        self.server.shutdown()

def make_server(**kw):
    try:
        return eventlet_server(**kw)
    except ImportError:
        return simple_server(**kw)

def make_server_thread(**kw):
    try:
        t = EventletServerThread(**kw)
    except ImportError:
        try:
            t = TornadoServerThread(**kw)
        except ImportError:
            t = SimpleServerThread(**kw)
    t.start()
    return t


if __name__ == '__main__':
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler(sys.stderr))

    from urllib3 import get_host

    url = "http://localhost:8081"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    print "Starting server at: %s" % url

    scheme, host, port = get_host(url)
    make_server(scheme=scheme, host=host, port=port)

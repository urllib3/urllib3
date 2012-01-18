"""For tests: a thread that opens a listening socket then invokes a callback.

Many `urllib3` tests are full integration tests, that let the whole
library and its `httplib` dependencies work together to open a real
socket and have an HTTP conversation over it.  To support these tests
without requiring a separate process or an HTTP server (that then would
become yet another piece of code that we were testing), we provide two
simple functions `start_server()` and `read_request()` that encourage
tests to look like this::

    def test_example(self):

        def server(listener):
            address, sock = listener.accept()
            request = read_request(sock)
            # ...
            # ... self.assertEquals(request, 'GET / HTTP/1.1\r\n...') ...
            # ... further recv() and send() activity to power the test ...
            # ...

        port = start_server(server)  # Creates a server socket, calls server()
        # ...
        # ... We can now spin up whatever we are testing, for example: ...
        # ... pool = HTTPConnectionPool(host, port) ...
        # ... response = pool.request('GET', '/', retries=0) ...
        # ... and we can see if the response is what we expected, etc ...
        # ...

The reason that we provide `start_server()` as an explicit callback,
instead of trying to make it disappear into `setUp()` as a fixture or
making it a test-method decorator, is that an explicit call is not only
a bit easier to read (less magic) but is also necessary so that each
test can choose the `server()` function that it passes in.  Some tests
will need to define their own very-specific `server()` functions inline,
but series of similar tests can define a single `server()`-style
function up at the module level that they can all share.

"""
import socket
from threading import Thread
from Queue import Queue

def read_request(sock):
    """Read `sock` until a double CR-LF, and return the data received."""
    s = ''
    while not s.endswith('\r\n\r\n'):
        s += sock.recv(65536)
    return s

def start_server(server_function):
    """Create a listening server socket and publish its port on a queue."""

    def server_thread():
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        address = sock.getsockname()
        sock.listen(1)  # Once listen() returns, the server socket is ready
        q.put(address)     # ... so we can safely tell the client to use it now
        server_function(sock)

    q = Queue()
    t = Thread(target=server_thread)
    t.daemon = True
    t.start()
    return q.get()  # Wait until the server has started up, then return.

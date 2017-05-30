"""
Low-level synchronous connection tests.

These tests involve mocking out the network layer to cause specific unusual
behaviours to occur. The goal is to ensure that the synchronous connection
layer can handle unexpected network weather without falling over, and without
expending undue effort to arrange that these effects actually happen on a real
network.
"""
import collections
import errno
import socket
import ssl
import unittest

import h11

from urllib3.base import Request
from urllib3.sync_connection import SyncHTTP1Connection
from urllib3.util import selectors


# Objects and globals for handling scenarios.
Event = collections.namedtuple('Event', ['expected_object', 'event', 'meta'])

SELECTOR = "SELECTOR"
SOCKET = "SOCKET"
RAISE_EAGAIN = "RAISE_EAGAIN"
RAISE_WANT_READ = "RAISE_WANT_READ"
RAISE_WANT_WRITE = "RAISE_WANT_WRITE"

EVENT_SELECT = "EVENT_SELECT"

EVENT_SEND = "EVENT_SEND"
SEND_ALL = "SEND_ALL"

EVENT_RECV = "EVENT_RECV"
RECV_ALL = "RECV_ALL"


# A number of helpful shorthands for common events.
SELECT_UPLOAD_WRITE = Event(
    SELECTOR,
    EVENT_SELECT,
    (selectors.EVENT_READ | selectors.EVENT_WRITE, selectors.EVENT_WRITE)
)
SELECT_UPLOAD_READ = Event(
    SELECTOR,
    EVENT_SELECT,
    (selectors.EVENT_READ | selectors.EVENT_WRITE, selectors.EVENT_READ)
)
SELECT_DOWNLOAD_READ = Event(
    SELECTOR, EVENT_SELECT, (selectors.EVENT_READ, selectors.EVENT_READ)
)
SELECT_DOWNLOAD_WRITE = Event(
    SELECTOR, EVENT_SELECT, (selectors.EVENT_READ, selectors.EVENT_READ)
)
SELECT_WRITABLE_WRITE = Event(
    SELECTOR, EVENT_SELECT, (selectors.EVENT_WRITE, selectors.EVENT_WRITE)
)
SOCKET_SEND_ALL = Event(SOCKET, EVENT_SEND, (SEND_ALL,))
SOCKET_SEND_5 = Event(SOCKET, EVENT_SEND, (5,))
SOCKET_SEND_EAGAIN = Event(SOCKET, EVENT_SEND, (RAISE_EAGAIN,))
SOCKET_SEND_WANTREAD = Event(SOCKET, EVENT_SEND, (RAISE_WANT_READ,))
SOCKET_SEND_WANTWRITE = Event(SOCKET, EVENT_SEND, (RAISE_WANT_WRITE,))
SOCKET_RECV_ALL = Event(SOCKET, EVENT_RECV, (RECV_ALL,))
SOCKET_RECV_5 = Event(SOCKET, EVENT_RECV, (5,))
SOCKET_RECV_EAGAIN = Event(SOCKET, EVENT_RECV, (RAISE_EAGAIN,))
SOCKET_RECV_WANTREAD = Event(SOCKET, EVENT_RECV, (RAISE_WANT_READ,))
SOCKET_RECV_WANTWRITE = Event(SOCKET, EVENT_RECV, (RAISE_WANT_WRITE,))


REQUEST = (
    b'GET / HTTP/1.1\r\n'
    b'host: localhost\r\n'
    b'\r\n'
)
RESPONSE = (
    b'HTTP/1.1 200 OK\r\n'
    b'Server: totallyarealserver/1.0.0\r\n'
    b'Content-Length: 8\r\n'
    b'Content-Type: text/plain\r\n'
    b'\r\n'
    b'complete'
)


class ScenarioError(Exception):
    """
    An error occurred with running the scenario.
    """
    pass


class ScenarioSelector(object):
    """
    A mock Selector object. This selector implements a tiny bit of the selector
    API (only that which is used by the higher layers), and response to select
    based on the scenario it is provided.
    """
    def __init__(self, scenario, sock):
        self._scenario = scenario
        self._fd = sock
        self._events = None

    def register(self, fd, events):
        if fd is not self._fd:
            raise ScenarioError("Registered unexpected socket!")
        self._events = events

    def modify(self, fd, events):
        if fd is not self._fd:
            raise ScenarioError("Modifying unexpected socket!")
        self._events = events

    def select(self, timeout=None):
        expected_object, event, args = self._scenario.pop(0)
        if expected_object is not SELECTOR:
            raise ScenarioError("Received non selector event!")

        if event is not EVENT_SELECT:
            raise ScenarioError("Expected EVENT_SELECT, got %s" % event)

        expected_events, returned_event = args
        if self._events != expected_events:
            raise ScenarioError(
                "Expected events %s, got %s" % (self._events, expected_events)
            )

        key = self.get_key(self._fd)
        return [(key, returned_event)]

    def get_key(self, fd):
        if fd is not self._fd:
            raise ScenarioError("Querying unexpected socket!")
        return selectors.SelectorKey(
            self._fd,
            1,
            self._events,
            None
        )

    def close(self):
        pass


class ScenarioSocket(object):
    """
    A mock Socket object. This object implements a tiny bit of the socket API
    (only that which is used by the synchronous connection), and responds to
    socket calls based on the scenario it is provided.
    """
    def __init__(self, scenario):
        self._scenario = scenario
        self._data_to_send = RESPONSE
        self._data_sent = b''
        self._closed = False

    def _raise_errors(self, possible_error):
        if possible_error is RAISE_EAGAIN:
            raise socket.error(errno.EAGAIN, "try again later")
        elif possible_error is RAISE_WANT_READ:
            raise ssl.SSLWantReadError("Want read")
        elif possible_error is RAISE_WANT_WRITE:
            raise ssl.SSLWantWriteError("Want write")

    def send(self, data):
        expected_object, event, args = self._scenario.pop(0)
        if expected_object is not SOCKET:
            raise ScenarioError("Received non selector event!")

        if event is not EVENT_SEND:
            raise ScenarioError("Expected EVENT_SEND, got %s" % event)

        amount, = args
        self._raise_errors(amount)
        if amount is SEND_ALL:
            amount = len(data)

        self._data_sent += data[:amount].tobytes()
        return amount

    def recv(self, amt):
        expected_object, event, args = self._scenario.pop(0)
        if expected_object is not SOCKET:
            raise ScenarioError("Received non selector event!")

        if event is not EVENT_RECV:
            raise ScenarioError("Expected EVENT_RECV, got %s" % event)

        amount, = args
        self._raise_errors(amount)
        if amount is RECV_ALL:
            amount = min(len(RESPONSE), amt)

        rdata = self._data_to_send[:amount]
        self._data_to_send = self._data_to_send[amount:]
        return rdata

    def setblocking(self, *args):
        pass

    def close(self):
        self._closed = True


class TestUnusualSocketConditions(unittest.TestCase):
    """
    This class contains tests that take strict control over sockets and
    selectors. The goal here is to simulate unusual network conditions that are
    extremely difficult to reproducibly simulate even with socketlevel tests in
    which we control both ends of the connection. For example, these tests
    will trigger WANT_READ and WANT_WRITE errors in TLS stacks which are
    otherwise extremely hard to trigger, and will also fire EAGAIN on sockets
    marked readable/writable, which can technically happen but are extremely
    tricky to trigger by using actual sockets and the loopback interface.

    These tests are necessarily not a perfect replacement for actual realworld
    examples, but those are so prohibitively difficult to trigger that these
    will have to do instead.
    """
    # A stub value of the read timeout that will be used by the selector.
    # This should not be edited by tests: only used as a reference for what
    # delay values they can use to force things to time out.
    READ_TIMEOUT = 5

    def run_scenario(self, scenario):
        conn = SyncHTTP1Connection('localhost', 80)
        conn._state_machine = h11.Connection(our_role=h11.CLIENT)
        conn._sock = sock = ScenarioSocket(scenario)
        conn._selector = ScenarioSelector(scenario, sock)

        request = Request(method=b'GET', target=b'/')
        request.add_host(host=b'localhost', port=80, scheme='http')
        response = conn.send_request(request, read_timeout=self.READ_TIMEOUT)
        body = b''.join(response.body)

        # The scenario should be totally consumed.
        self.assertFalse(scenario)

        # Validate that the response is complete.
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, b'complete')
        self.assertEqual(response.version, b'HTTP/1.1')
        self.assertEqual(len(response.headers), 3)
        self.assertEqual(response.headers['server'], 'totallyarealserver/1.0.0')
        self.assertEqual(response.headers['content-length'], '8')
        self.assertEqual(response.headers['content-type'], 'text/plain')

        return sock

    def test_happy_path(self):
        """
        When everything goes smoothly, the response is cleanly consumed.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_ALL,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

    def test_handle_recv_eagain_download(self):
        """
        When a socket is marked readable during response body download but
        returns EAGAIN when read from, the code simply retries the read.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_ALL,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_EAGAIN,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_EAGAIN,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

    def test_handle_recv_want_read_download(self):
        """
        When a socket is marked readable during response body download but
        returns SSL_WANT_READ when read from, the code simply retries the read.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_ALL,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_WANTREAD,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_WANTREAD,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

    def test_handle_recv_eagain_upload(self):
        """
        When a socket is marked readable during request upload but returns
        EAGAIN when read from, the code ignores it and continues with upload.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_5,
            SELECT_UPLOAD_READ,
            SOCKET_RECV_EAGAIN,
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_ALL,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

    def test_handle_recv_wantread_upload(self):
        """
        When a socket is marked readable during request upload but returns
        WANT_READ when read from, the code ignores it and continues with upload.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_5,
            SELECT_UPLOAD_READ,
            SOCKET_RECV_WANTREAD,
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_ALL,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

    def test_handle_send_eagain_upload(self):
        """
        When a socket is marked writable during request upload but returns
        EAGAIN when written to, the code ignores it and continues with upload.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_5,
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_EAGAIN,
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_ALL,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

    def test_handle_send_wantwrite_upload(self):
        """
        When a socket is marked writable during request upload but returns
        WANT_WRITE when written to, the code ignores it and continues with
        upload.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_5,
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_WANTWRITE,
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_ALL,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

    def test_handle_early_response(self):
        """
        When a socket is marked readable during request upload, and any data is
        read from the socket, the upload immediately stops and the response is
        read.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_5,
            SELECT_UPLOAD_READ,
            SOCKET_RECV_5,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST[:5])
        self.assertTrue(sock._closed)

    def test_handle_want_read_during_upload(self):
        """
        When a socket is marked writable during request upload but returns
        WANT_READ when written to, the code waits for the socket to become
        readable and issues the write again.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_5,
            # Return WANT_READ twice for good measure.
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_WANTREAD,
            SELECT_DOWNLOAD_READ,
            SOCKET_SEND_WANTREAD,
            SELECT_DOWNLOAD_READ,
            SOCKET_SEND_ALL,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

    def test_handle_want_write_during_download(self):
        """
        When a socket is marked readable during response download but returns
        WANT_WRITE when read from, the code waits for the socket to become
        writable and issues the read again.
        """
        scenario = [
            SELECT_UPLOAD_WRITE,
            SOCKET_SEND_ALL,
            # Return WANT_WRITE twice for good measure.
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_WANTWRITE,
            SELECT_WRITABLE_WRITE,
            SOCKET_RECV_WANTWRITE,
            SELECT_WRITABLE_WRITE,
            SOCKET_RECV_5,
            SELECT_DOWNLOAD_READ,
            SOCKET_RECV_ALL,
        ]
        sock = self.run_scenario(scenario)
        self.assertEqual(sock._data_sent, REQUEST)

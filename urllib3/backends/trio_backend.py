import trio

from . import LoopAbort
from ._util import is_readable

BUFSIZE = 65536


class TrioBackend:
    async def connect(
            self, host, port, source_address=None, socket_options=None):
        if source_address is not None:
            # You can't really combine source_address= and happy eyeballs
            # (can we get rid of source_address? or at least make it a source
            # ip, no port?)
            raise NotImplementedError(
                "trio backend doesn't support setting source_address")

        stream = await trio.open_tcp_stream(host, port)
        for (level, optname, value) in socket_options:
            stream.setsockopt(level, optname, value)

        return TrioSocket(stream)

# XX it turns out that we don't need SSLStream to be robustified against
# cancellation, but we probably should do something to detect when the stream
# has been broken by cancellation (e.g. a timeout) and make is_readable return
# True so the connection won't be reused.


class TrioSocket:
    def __init__(self, stream):
        self._stream = stream

    async def start_tls(self, server_hostname, ssl_context):
        wrapped = trio.ssl.SSLStream(
            self._stream, ssl_context,
            server_hostname=server_hostname,
            https_compatible=True)
        return TrioSocket(wrapped)

    def getpeercert(self, binary=False):
        return self._stream.getpeercert(binary=binary)

    async def receive_some(self):
        return await self._stream.receive_some(BUFSIZE)

    async def send_and_receive_for_a_while(self, produce_bytes, consume_bytes):
        async def sender():
            while True:
                outgoing = await produce_bytes()
                if outgoing is None:
                    break
                await self._stream.send_all(outgoing)

        async def receiver():
            while True:
                incoming = await self._stream.receive_some(BUFSIZE)
                consume_bytes(incoming)

        try:
            async with trio.open_nursery() as nursery:
                nursery.spawn(sender)
                nursery.spawn(receiver)
        except LoopAbort:
            pass

    def forceful_close(self):
        self._stream.forceful_close()

    def is_readable(self):
        # This is a bit of a hack, but I can't think of a better API that trio
        # *could* provide, since what we want to check here is such an odd
        # thing.
        sock_stream = self._stream
        # Strip off SSLStream wrappings
        while hasattr(sock_stream, "transport_stream"):
            sock_stream = sock_stream.transport_stream
        sock = sock_stream.socket
        return is_readable(sock)

    def set_readable_watch_state(self, enabled):
        pass

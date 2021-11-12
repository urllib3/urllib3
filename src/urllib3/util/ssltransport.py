import io
import socket
import ssl
from typing import (
    TYPE_CHECKING,
    Any,
    BinaryIO,
    Callable,
    List,
    Optional,
    TextIO,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

from ..exceptions import ProxySchemeUnsupported

if TYPE_CHECKING:

    from typing_extensions import Literal

    from .ssl_ import _TYPE_PEER_CERT_RET, _TYPE_PEER_CERT_RET_DICT


_SelfT = TypeVar("_SelfT", bound="SSLTransport")
_WriteBuffer = Union[bytearray, memoryview]
_ReturnValue = TypeVar("_ReturnValue")

SSL_BLOCKSIZE = 16384


class SSLTransport:
    """
    The SSLTransport wraps an existing socket and establishes an SSL connection.

    Contrary to Python's implementation of SSLSocket, it allows you to chain
    multiple TLS connections together. It's particularly useful if you need to
    implement TLS within TLS.

    The class supports most of the socket API operations.
    """

    @staticmethod
    def _validate_ssl_context_for_tls_in_tls(ssl_context: "ssl.SSLContext") -> None:
        """
        Raises a ProxySchemeUnsupported if the provided ssl_context can't be used
        for TLS in TLS.

        The only requirement is that the ssl_context provides the 'wrap_bio'
        methods.
        """

        if not hasattr(ssl_context, "wrap_bio"):
            raise ProxySchemeUnsupported(
                "TLS in TLS requires SSLContext.wrap_bio() which isn't "
                "available on non-native SSLContext"
            )

    def __init__(
        self,
        socket: socket.socket,
        ssl_context: "ssl.SSLContext",
        server_hostname: Optional[str] = None,
        suppress_ragged_eofs: bool = True,
    ) -> None:
        """
        Create an SSLTransport around socket using the provided ssl_context.
        """
        self.incoming = ssl.MemoryBIO()
        self.outgoing = ssl.MemoryBIO()

        self.suppress_ragged_eofs = suppress_ragged_eofs
        self.socket = socket

        self.sslobj = ssl_context.wrap_bio(
            self.incoming, self.outgoing, server_hostname=server_hostname
        )

        # Perform initial handshake.
        self._ssl_io_loop(self.sslobj.do_handshake)

    def __enter__(self: _SelfT) -> _SelfT:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def fileno(self) -> int:
        return self.socket.fileno()

    def read(self, len: int = 1024, buffer: Optional[Any] = None) -> Union[int, bytes]:
        return self._wrap_ssl_read(len, buffer)

    def recv(self, buflen: int = 1024, flags: int = 0) -> Union[int, bytes]:
        if flags != 0:
            raise ValueError("non-zero flags not allowed in calls to recv")
        return self._wrap_ssl_read(buflen)

    def recv_into(
        self,
        buffer: _WriteBuffer,
        nbytes: Optional[int] = None,
        flags: int = 0,
    ) -> Union[None, int, bytes]:
        if flags != 0:
            raise ValueError("non-zero flags not allowed in calls to recv_into")
        if nbytes is None:
            nbytes = len(buffer)
        return self.read(nbytes, buffer)

    def sendall(self, data: bytes, flags: int = 0) -> None:
        if flags != 0:
            raise ValueError("non-zero flags not allowed in calls to sendall")
        count = 0
        with memoryview(data) as view, view.cast("B") as byte_view:
            amount = len(byte_view)
            while count < amount:
                v = self.send(byte_view[count:])
                count += v

    def send(self, data: bytes, flags: int = 0) -> int:
        if flags != 0:
            raise ValueError("non-zero flags not allowed in calls to send")
        return self._ssl_io_loop(self.sslobj.write, data)

    def makefile(
        self,
        mode: str,
        buffering: Optional[int] = None,
        *,
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        newline: Optional[str] = None,
    ) -> Union[BinaryIO, TextIO, socket.SocketIO]:
        """
        Python's httpclient uses makefile and buffered io when reading HTTP
        messages and we need to support it.

        This is unfortunately a copy and paste of socket.py makefile with small
        changes to point to the socket directly.
        """
        if not set(mode) <= {"r", "w", "b"}:
            raise ValueError(f"invalid mode {mode!r} (only r, w, b allowed)")

        writing = "w" in mode
        reading = "r" in mode or not writing
        assert reading or writing
        binary = "b" in mode
        rawmode = ""
        if reading:
            rawmode += "r"
        if writing:
            rawmode += "w"
        raw = socket.SocketIO(self, rawmode)  # type: ignore[arg-type]
        self.socket._io_refs += 1  # type: ignore[attr-defined]
        if buffering is None:
            buffering = -1
        if buffering < 0:
            buffering = io.DEFAULT_BUFFER_SIZE
        if buffering == 0:
            if not binary:
                raise ValueError("unbuffered streams must be binary")
            return raw
        buffer: BinaryIO
        if reading and writing:
            buffer = io.BufferedRWPair(raw, raw, buffering)  # type: ignore[assignment]
        elif reading:
            buffer = io.BufferedReader(raw, buffering)
        else:
            assert writing
            buffer = io.BufferedWriter(raw, buffering)
        if binary:
            return buffer
        text = io.TextIOWrapper(buffer, encoding, errors, newline)
        text.mode = mode  # type: ignore[misc]
        return text

    def unwrap(self) -> None:
        self._ssl_io_loop(self.sslobj.unwrap)

    def close(self) -> None:
        self.socket.close()

    @overload
    def getpeercert(
        self, binary_form: "Literal[False]" = ...
    ) -> Optional["_TYPE_PEER_CERT_RET_DICT"]:
        ...

    @overload
    def getpeercert(self, binary_form: "Literal[True]") -> Optional[bytes]:
        ...

    def getpeercert(self, binary_form: bool = False) -> "_TYPE_PEER_CERT_RET":
        return self.sslobj.getpeercert(binary_form)  # type: ignore[return-value]

    def version(self) -> Optional[str]:
        return self.sslobj.version()

    def cipher(self) -> Optional[Tuple[str, str, int]]:
        return self.sslobj.cipher()

    def selected_alpn_protocol(self) -> Optional[str]:
        return self.sslobj.selected_alpn_protocol()

    def selected_npn_protocol(self) -> Optional[str]:
        return self.sslobj.selected_npn_protocol()

    def shared_ciphers(self) -> Optional[List[Tuple[str, str, int]]]:
        return self.sslobj.shared_ciphers()

    def compression(self) -> Optional[str]:
        return self.sslobj.compression()

    def settimeout(self, value: Optional[float]) -> None:
        self.socket.settimeout(value)

    def gettimeout(self) -> Optional[float]:
        return self.socket.gettimeout()

    def _decref_socketios(self) -> None:
        self.socket._decref_socketios()  # type: ignore[attr-defined]

    def _wrap_ssl_read(
        self, len: int, buffer: Optional[bytearray] = None
    ) -> Union[int, bytes]:
        try:
            return self._ssl_io_loop(self.sslobj.read, len, buffer)
        except ssl.SSLError as e:
            if e.errno == ssl.SSL_ERROR_EOF and self.suppress_ragged_eofs:
                return 0  # eof, return 0.
            else:
                raise

    # func is sslobj.do_handshake or sslobj.unwrap
    @overload
    def _ssl_io_loop(self, func: Callable[[], None]) -> None:
        ...

    # func is sslobj.write, arg1 is data
    @overload
    def _ssl_io_loop(self, func: Callable[[bytes], int], arg1: bytes) -> int:
        ...

    # func is sslobj.read, arg1 is len, arg2 is buffer
    @overload
    def _ssl_io_loop(
        self,
        func: Callable[[int, Optional[bytearray]], bytes],
        arg1: int,
        arg2: Optional[bytearray],
    ) -> bytes:
        ...

    def _ssl_io_loop(
        self,
        func: Callable[..., _ReturnValue],
        arg1: Union[None, bytes, int] = None,
        arg2: Optional[bytearray] = None,
    ) -> _ReturnValue:
        """Performs an I/O loop between incoming/outgoing and the socket."""
        should_loop = True
        ret = None

        while should_loop:
            errno = None
            try:
                if arg1 is None and arg2 is None:
                    ret = func()
                elif arg2 is None:
                    ret = func(arg1)
                else:
                    ret = func(arg1, arg2)
            except ssl.SSLError as e:
                if e.errno not in (ssl.SSL_ERROR_WANT_READ, ssl.SSL_ERROR_WANT_WRITE):
                    # WANT_READ, and WANT_WRITE are expected, others are not.
                    raise e
                errno = e.errno

            buf = self.outgoing.read()
            self.socket.sendall(buf)

            if errno is None:
                should_loop = False
            elif errno == ssl.SSL_ERROR_WANT_READ:
                buf = self.socket.recv(SSL_BLOCKSIZE)
                if buf:
                    self.incoming.write(buf)
                else:
                    self.incoming.write_eof()
        return cast(_ReturnValue, ret)

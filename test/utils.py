import socket
from typing import Optional


def simple_read_http_request(sock: socket.socket) -> bytes:
    """
    Read in an HTTP Request from a socket, handling both content length and
    chunked encoding.

    This assumes that the request is well formed, and only supports either content length
    or chunked encoding. This is only meant for use in tests!

    Returns the bytes of the request
    """
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(65536)
    # seperate the headers from the eventual body
    header_buf, buf = buf.split(b"\r\n\r\n", maxsplit=1)
    # check for any content
    content_length: Optional[int] = None
    chunked_content: bool = False
    for header_line in header_buf.split(b"\r\n"):
        if header_line.decode("ascii").lower().startswith("content-length"):
            content_length = int(header_line.split(b":")[1].decode("ascii"))
            break
        if header_line.decode("ascii").lower().startswith("transfer-encoding"):
            encoding = header_line.split(b":")[1].decode("ascii").strip()
            if encoding != "chunked":
                raise ValueError("Unsupported encoding")
            chunked_content = True
    if chunked_content:
        final_content = b""
        state = "read-length"
        next_chunk_length: Optional[int] = None
        while state != "done":
            while state == "read-length":
                maybe_split = buf.split(b"\r\n", maxsplit=1)
                if len(maybe_split) == 2:
                    # get the length
                    len_str, buf = maybe_split
                    final_content += len_str + b"\r\n"
                    next_chunk_length = int(len_str, 16)
                    state = "read-chunk"
                else:
                    buf += sock.recv(65536)
            while state == "read-chunk":
                if next_chunk_length == 0:
                    # chunk of 0 length indicates being done
                    # let's make sure to read in the remaining
                    # buffer data though (at least the newline)
                    while len(buf) < 2:
                        buf += sock.recv(65536)
                    final_content += buf
                    state = "done"
                    break
                assert next_chunk_length is not None
                while len(buf) < next_chunk_length + 2:
                    buf += sock.recv(65536)
                # we now have our chunk and the CRLF
                final_content += buf[: next_chunk_length + 2]
                # trim the CRLF as it's not part of the data
                buf = buf[(next_chunk_length + 2) :]
                next_chunk_length, state = None, "read-length"
        # we are now done
        return header_buf + b"\r\n\r\n" + final_content
    else:
        # read unchunked content
        if content_length is not None and len(buf) < content_length:
            buf += sock.recv(content_length - len(buf))
        return header_buf + b"\r\n\r\n" + buf

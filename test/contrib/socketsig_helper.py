import socket
import sys


def socket_signature_validators():
    """
    Return dictionary with socket function calls that should be
    valid for a socket.socket instance. Using inspect.getargspec
    doesn't work on built-in socket._socket so we're relyinng on
    documentation to build the list of supported function calls
    """

    # python version selectors
    python_all = lambda v: v  # noqa
    python_less_than_34 = lambda v: v if sys.hexversion < 0x03040000 else []  # noqa
    python_34_or_newer = lambda v: v if sys.hexversion >= 0x03040000 else []  # noqa

    # common socket method validators. Each one of them takes
    # a 'self' parameter and tries calling the corresponding method
    # with a set of parameters that should be supported by a genuine
    # socket.socket object
    validators = {
        "close": [python_all([lambda s: s.close()])],
        "fileno": [python_all([lambda s: s.fileno()])],
        "gettimeout": [python_all([lambda s: s.gettimeout()])],
        "makefile": [
            python_less_than_34(
                [
                    lambda s: s.makefile(),
                    lambda s: s.makefile("r"),
                    lambda s: s.makefile("r", 512),
                ]
            ),
            python_34_or_newer(
                [
                    lambda s: s.makefile(mode="r"),
                    lambda s: s.makefile(mode="r", buffering=0),
                    lambda s: s.makefile(mode="r", buffering=0, encoding="ascii"),
                    lambda s: s.makefile(
                        mode="r", buffering=0, encoding="ascii", errors="ignore"
                    ),
                    lambda s: s.makefile(
                        mode="r",
                        buffering=0,
                        encoding="ascii",
                        errors="ignore",
                        newline="\n",
                    ),
                ]
            ),
        ],
        "recv": [python_all([lambda s: s.recv(512), lambda s: s.recv(512, 0)])],
        "recv_into": [
            python_all(
                [
                    lambda s: s.recv_into(bytearray(512)),
                    lambda s: s.recv_into(bytearray(512), 512),
                    lambda s: s.recv_into(bytearray(512), 512, 0),
                ]
            )
        ],
        "send": [python_all([lambda s: s.sendall(""), lambda s: s.sendall("", 0)])],
        "sendall": [python_all([lambda s: s.sendall(""), lambda s: s.sendall("", 0)])],
        "settimeout": [python_all([lambda s: s.settimeout(1)])],
        "shutdown": [python_all([lambda s: s.shutdown(socket.SHUT_RDWR)])],
    }
    return validators

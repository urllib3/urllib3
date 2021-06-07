import hmac
import os
import socket
import sys
import warnings
from binascii import unhexlify
from hashlib import md5, sha1, sha256
from typing import TYPE_CHECKING, Dict, Optional, Tuple, Union, cast, overload

from ..exceptions import ProxySchemeUnsupported, SNIMissingWarning, SSLError
from .url import _BRACELESS_IPV6_ADDRZ_RE, _IPV4_RE

SSLContext = None
SSLTransport = None
HAS_SNI = False
IS_PYOPENSSL = False
IS_SECURETRANSPORT = False
ALPN_PROTOCOLS = ["http/1.1"]
USE_DEFAULT_SSLCONTEXT_CIPHERS = False

# Maps the length of a digest to a possible hash function producing this digest
HASHFUNC_MAP = {32: md5, 40: sha1, 64: sha256}


def _is_ge_openssl_v1_1_1(
    openssl_version_text: str, openssl_version_number: int
) -> bool:
    """Returns True for OpenSSL 1.1.1+ (>=0x10101000)
    LibreSSL reports a version number of 0x20000000 for
    OpenSSL version number so we need to filter out LibreSSL.
    """
    return (
        not openssl_version_text.startswith("LibreSSL")
        and openssl_version_number >= 0x10101000
    )


if TYPE_CHECKING:
    from typing_extensions import Literal

    from .ssltransport import SSLTransport as SSLTransportType

try:  # Do we have ssl at all?
    import ssl
    from ssl import (  # type: ignore
        CERT_REQUIRED,
        HAS_SNI,
        OP_NO_COMPRESSION,
        OP_NO_TICKET,
        OPENSSL_VERSION,
        OPENSSL_VERSION_NUMBER,
        PROTOCOL_TLS,
        PROTOCOL_TLS_CLIENT,
        OP_NO_SSLv2,
        OP_NO_SSLv3,
        SSLContext,
    )

    USE_DEFAULT_SSLCONTEXT_CIPHERS = _is_ge_openssl_v1_1_1(
        OPENSSL_VERSION, OPENSSL_VERSION_NUMBER
    )
    PROTOCOL_SSLv23 = PROTOCOL_TLS
    from .ssltransport import SSLTransport  # type: ignore
except ImportError:
    OP_NO_COMPRESSION = 0x20000  # type: ignore
    OP_NO_TICKET = 0x4000  # type: ignore
    OP_NO_SSLv2 = 0x1000000  # type: ignore
    OP_NO_SSLv3 = 0x2000000  # type: ignore
    PROTOCOL_SSLv23 = PROTOCOL_TLS = 2
    PROTOCOL_TLS_CLIENT = 16


_PCTRTT = Tuple[Tuple[str, str], ...]
_PCTRTTT = Tuple[_PCTRTT, ...]
PeerCertRetDictType = Dict[str, Union[str, _PCTRTTT, _PCTRTT]]
PeerCertRetType = Union[PeerCertRetDictType, bytes, None]


# A secure default.
# Sources for more information on TLS ciphers:
#
# - https://wiki.mozilla.org/Security/Server_Side_TLS
# - https://www.ssllabs.com/projects/best-practices/index.html
# - https://hynek.me/articles/hardening-your-web-servers-ssl-ciphers/
#
# The general intent is:
# - prefer cipher suites that offer perfect forward secrecy (DHE/ECDHE),
# - prefer ECDHE over DHE for better performance,
# - prefer any AES-GCM and ChaCha20 over any AES-CBC for better performance and
#   security,
# - prefer AES-GCM over ChaCha20 because hardware-accelerated AES is common,
# - disable NULL authentication, MD5 MACs, DSS, and other
#   insecure ciphers for security reasons.
# - NOTE: TLS 1.3 cipher suites are managed through a different interface
#   not exposed by CPython (yet!) and are enabled by default if they're available.
DEFAULT_CIPHERS = ":".join(
    [
        "ECDHE+AESGCM",
        "ECDHE+CHACHA20",
        "DHE+AESGCM",
        "DHE+CHACHA20",
        "ECDH+AESGCM",
        "DH+AESGCM",
        "ECDH+AES",
        "DH+AES",
        "RSA+AESGCM",
        "RSA+AES",
        "!aNULL",
        "!eNULL",
        "!MD5",
        "!DSS",
        "!AESCCM",
    ]
)


def assert_fingerprint(cert: Optional[bytes], fingerprint: str) -> None:
    """
    Checks if given fingerprint matches the supplied certificate.

    :param cert:
        Certificate as bytes object.
    :param fingerprint:
        Fingerprint as string of hexdigits, can be interspersed by colons.
    """

    if cert is None:
        raise SSLError("No certificate for the peer.")

    fingerprint = fingerprint.replace(":", "").lower()
    digest_length = len(fingerprint)
    hashfunc = HASHFUNC_MAP.get(digest_length)
    if not hashfunc:
        raise SSLError(f"Fingerprint of invalid length: {fingerprint}")

    # We need encode() here for py32; works on py2 and p33.
    fingerprint_bytes = unhexlify(fingerprint.encode())

    cert_digest = hashfunc(cert).digest()

    if not hmac.compare_digest(cert_digest, fingerprint_bytes):
        raise SSLError(
            f'Fingerprints did not match. Expected "{fingerprint}", got "{cert_digest.hex()}".'
        )


def resolve_cert_reqs(candidate: Union[None, int, str]) -> int:
    """
    Resolves the argument to a numeric constant, which can be passed to
    the wrap_socket function/method from the ssl module.
    Defaults to :data:`ssl.CERT_REQUIRED`.
    If given a string it is assumed to be the name of the constant in the
    :mod:`ssl` module or its abbreviation.
    (So you can specify `REQUIRED` instead of `CERT_REQUIRED`.
    If it's neither `None` nor a string we assume it is already the numeric
    constant which can directly be passed to wrap_socket.
    """
    if candidate is None:
        return CERT_REQUIRED

    if isinstance(candidate, str):
        res = getattr(ssl, candidate, None)
        if res is None:
            res = getattr(ssl, "CERT_" + candidate)
        return cast(int, res)

    return candidate


def resolve_ssl_version(candidate: Union[None, int, str]) -> int:
    """
    like resolve_cert_reqs
    """
    if candidate is None:
        return PROTOCOL_TLS

    if isinstance(candidate, str):
        res = getattr(ssl, candidate, None)
        if res is None:
            res = getattr(ssl, "PROTOCOL_" + candidate)
        return cast(int, res)

    return candidate


def create_urllib3_context(
    ssl_version: Optional[int] = None,
    cert_reqs: Optional[int] = None,
    options: Optional[int] = None,
    ciphers: Optional[str] = None,
) -> "ssl.SSLContext":
    """All arguments have the same meaning as ``ssl_wrap_socket``.

    By default, this function does a lot of the same work that
    ``ssl.create_default_context`` does on Python 3.4+. It:

    - Disables SSLv2, SSLv3, and compression
    - Sets a restricted set of server ciphers

    If you wish to enable SSLv3, you can do::

        from urllib3.util import ssl_
        context = ssl_.create_urllib3_context()
        context.options &= ~ssl_.OP_NO_SSLv3

    You can do the same to enable compression (substituting ``COMPRESSION``
    for ``SSLv3`` in the last line above).

    :param ssl_version:
        The desired protocol version to use. This will default to
        PROTOCOL_SSLv23 which will negotiate the highest protocol that both
        the server and your installation of OpenSSL support.
    :param cert_reqs:
        Whether to require the certificate verification. This defaults to
        ``ssl.CERT_REQUIRED``.
    :param options:
        Specific OpenSSL options. These default to ``ssl.OP_NO_SSLv2``,
        ``ssl.OP_NO_SSLv3``, ``ssl.OP_NO_COMPRESSION``, and ``ssl.OP_NO_TICKET``.
    :param ciphers:
        Which cipher suites to allow the server to select. Defaults to either system configured
        ciphers if OpenSSL 1.1.1+, otherwise uses a secure default set of ciphers.
    :returns:
        Constructed SSLContext object with specified options
    :rtype: SSLContext
    """
    if SSLContext is None:
        raise TypeError("Can't create an SSLContext object without an ssl module")

    # PROTOCOL_TLS is deprecated in Python 3.10 so we pass PROTOCOL_TLS_CLIENT instead.
    if ssl_version in (None, PROTOCOL_TLS):
        ssl_version = PROTOCOL_TLS_CLIENT

    context = SSLContext(ssl_version)

    # Unless we're given ciphers defer to either system ciphers in
    # the case of OpenSSL 1.1.1+ or use our own secure default ciphers.
    if ciphers is not None or not USE_DEFAULT_SSLCONTEXT_CIPHERS:
        context.set_ciphers(ciphers or DEFAULT_CIPHERS)

    # Setting the default here, as we may have no ssl module on import
    cert_reqs = ssl.CERT_REQUIRED if cert_reqs is None else cert_reqs

    if options is None:
        options = 0
        # SSLv2 is easily broken and is considered harmful and dangerous
        options |= OP_NO_SSLv2
        # SSLv3 has several problems and is now dangerous
        options |= OP_NO_SSLv3
        # Disable compression to prevent CRIME attacks for OpenSSL 1.0+
        # (issue #309)
        options |= OP_NO_COMPRESSION
        # TLSv1.2 only. Unless set explicitly, do not request tickets.
        # This may save some bandwidth on wire, and although the ticket is encrypted,
        # there is a risk associated with it being on wire,
        # if the server is not rotating its ticketing keys properly.
        options |= OP_NO_TICKET

    context.options |= options

    # Enable post-handshake authentication for TLS 1.3, see GH #1634. PHA is
    # necessary for conditional client cert authentication with TLS 1.3.
    # The attribute is None for OpenSSL <= 1.1.0 or does not exist in older
    # versions of Python.  We only enable on Python 3.7.4+ or if certificate
    # verification is enabled to work around Python issue #37428
    # See: https://bugs.python.org/issue37428
    if (cert_reqs == ssl.CERT_REQUIRED or sys.version_info >= (3, 7, 4)) and getattr(
        context, "post_handshake_auth", None
    ) is not None:
        context.post_handshake_auth = True

    # The order of the below lines setting verify_mode and check_hostname
    # matter due to safe-guards SSLContext has to prevent an SSLContext with
    # check_hostname=True, verify_mode=NONE/OPTIONAL.
    if cert_reqs == ssl.CERT_REQUIRED:
        context.verify_mode = cert_reqs
        context.check_hostname = True
    else:
        context.check_hostname = False
        context.verify_mode = cert_reqs

    if hasattr(context, "hostname_checks_common_name"):
        context.hostname_checks_common_name = False

    # Enable logging of TLS session keys via defacto standard environment variable
    # 'SSLKEYLOGFILE', if the feature is available (Python 3.8+). Skip empty values.
    if hasattr(context, "keylog_filename"):
        sslkeylogfile = os.environ.get("SSLKEYLOGFILE")
        if sslkeylogfile:
            context.keylog_filename = sslkeylogfile

    return context


@overload
def ssl_wrap_socket(
    sock: socket.socket,
    keyfile: Optional[str] = ...,
    certfile: Optional[str] = ...,
    cert_reqs: Optional[int] = ...,
    ca_certs: Optional[str] = ...,
    server_hostname: Optional[str] = ...,
    ssl_version: Optional[int] = ...,
    ciphers: Optional[str] = ...,
    ssl_context: Optional["ssl.SSLContext"] = ...,
    ca_cert_dir: Optional[str] = ...,
    key_password: Optional[str] = ...,
    ca_cert_data: Union[None, str, bytes] = ...,
    tls_in_tls: "Literal[False]" = ...,
) -> "ssl.SSLSocket":
    ...


@overload
def ssl_wrap_socket(
    sock: socket.socket,
    keyfile: Optional[str] = ...,
    certfile: Optional[str] = ...,
    cert_reqs: Optional[int] = ...,
    ca_certs: Optional[str] = ...,
    server_hostname: Optional[str] = ...,
    ssl_version: Optional[int] = ...,
    ciphers: Optional[str] = ...,
    ssl_context: Optional["ssl.SSLContext"] = ...,
    ca_cert_dir: Optional[str] = ...,
    key_password: Optional[str] = ...,
    ca_cert_data: Union[None, str, bytes] = ...,
    tls_in_tls: bool = ...,
) -> Union["ssl.SSLSocket", "SSLTransportType"]:
    ...


def ssl_wrap_socket(
    sock: socket.socket,
    keyfile: Optional[str] = None,
    certfile: Optional[str] = None,
    cert_reqs: Optional[int] = None,
    ca_certs: Optional[str] = None,
    server_hostname: Optional[str] = None,
    ssl_version: Optional[int] = None,
    ciphers: Optional[str] = None,
    ssl_context: Optional["ssl.SSLContext"] = None,
    ca_cert_dir: Optional[str] = None,
    key_password: Optional[str] = None,
    ca_cert_data: Union[None, str, bytes] = None,
    tls_in_tls: bool = False,
) -> Union["ssl.SSLSocket", "SSLTransportType"]:
    """
    All arguments except for server_hostname, ssl_context, and ca_cert_dir have
    the same meaning as they do when using :func:`ssl.wrap_socket`.

    :param server_hostname:
        When SNI is supported, the expected hostname of the certificate
    :param ssl_context:
        A pre-made :class:`SSLContext` object. If none is provided, one will
        be created using :func:`create_urllib3_context`.
    :param ciphers:
        A string of ciphers we wish the client to support.
    :param ca_cert_dir:
        A directory containing CA certificates in multiple separate files, as
        supported by OpenSSL's -CApath flag or the capath argument to
        SSLContext.load_verify_locations().
    :param key_password:
        Optional password if the keyfile is encrypted.
    :param ca_cert_data:
        Optional string containing CA certificates in PEM format suitable for
        passing as the cadata parameter to SSLContext.load_verify_locations()
    :param tls_in_tls:
        Use SSLTransport to wrap the existing socket.
    """
    context = ssl_context
    if context is None:
        # Note: This branch of code and all the variables in it are only used in tests.
        # We should consider deprecating and removing this code.
        context = create_urllib3_context(ssl_version, cert_reqs, ciphers=ciphers)

    if ca_certs or ca_cert_dir or ca_cert_data:
        try:
            context.load_verify_locations(ca_certs, ca_cert_dir, ca_cert_data)
        except OSError as e:
            raise SSLError(e)

    elif ssl_context is None and hasattr(context, "load_default_certs"):
        # try to load OS default certs; works well on Windows (require Python3.4+)
        context.load_default_certs()

    # Attempt to detect if we get the goofy behavior of the
    # keyfile being encrypted and OpenSSL asking for the
    # passphrase via the terminal and instead error out.
    if keyfile and key_password is None and _is_key_file_encrypted(keyfile):
        raise SSLError("Client private key is encrypted, password is required")

    if certfile:
        if key_password is None:
            context.load_cert_chain(certfile, keyfile)
        else:
            context.load_cert_chain(certfile, keyfile, key_password)

    try:
        if hasattr(context, "set_alpn_protocols"):
            context.set_alpn_protocols(ALPN_PROTOCOLS)
    except NotImplementedError:  # Defensive: in CI, we always have set_alpn_protocols
        pass

    if not HAS_SNI and server_hostname and not is_ipaddress(server_hostname):
        warnings.warn(
            "An HTTPS request has been made, but the SNI (Server Name "
            "Indication) extension to TLS is not available on this platform. "
            "This may cause the server to present an incorrect TLS "
            "certificate, which can cause validation failures. You can upgrade to "
            "a newer version of Python to solve this. For more information, see "
            "https://urllib3.readthedocs.io/en/latest/advanced-usage.html"
            "#tls-warnings",
            SNIMissingWarning,
        )

    ssl_sock = _ssl_wrap_socket_impl(sock, context, tls_in_tls, server_hostname)
    return ssl_sock


def is_ipaddress(hostname: Union[str, bytes]) -> bool:
    """Detects whether the hostname given is an IPv4 or IPv6 address.
    Also detects IPv6 addresses with Zone IDs.

    :param str hostname: Hostname to examine.
    :return: True if the hostname is an IP address, False otherwise.
    """
    if isinstance(hostname, bytes):
        # IDN A-label bytes are ASCII compatible.
        hostname = hostname.decode("ascii")
    return bool(_IPV4_RE.match(hostname) or _BRACELESS_IPV6_ADDRZ_RE.match(hostname))


def _is_key_file_encrypted(key_file: str) -> bool:
    """Detects if a key file is encrypted or not."""
    with open(key_file) as f:
        for line in f:
            # Look for Proc-Type: 4,ENCRYPTED
            if "ENCRYPTED" in line:
                return True

    return False


def _ssl_wrap_socket_impl(
    sock: socket.socket,
    ssl_context: "ssl.SSLContext",
    tls_in_tls: bool,
    server_hostname: Optional[str] = None,
) -> Union["ssl.SSLSocket", "SSLTransportType"]:
    if tls_in_tls:
        if not SSLTransport:
            # Import error, ssl is not available.
            raise ProxySchemeUnsupported(
                "TLS in TLS requires support for the 'ssl' module"
            )

        SSLTransport._validate_ssl_context_for_tls_in_tls(ssl_context)
        return SSLTransport(sock, ssl_context, server_hostname)

    return ssl_context.wrap_socket(sock, server_hostname=server_hostname)

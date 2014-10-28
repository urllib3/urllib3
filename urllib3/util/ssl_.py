from binascii import hexlify, unhexlify
from hashlib import md5, sha1

from ..exceptions import SSLError


try:  # Test for SSL features
    SSLContext = None
    HAS_SNI = False

    import ssl
    from ssl import wrap_socket, CERT_NONE, PROTOCOL_SSLv23
    from ssl import SSLContext  # Modern SSL?
    from ssl import HAS_SNI  # Has SNI?
except ImportError:
    pass


try:
    from ssl import OP_NO_SSLv2, OP_NO_SSLv3
except ImportError:
    OP_NO_SSLv2, OP_NO_SSLv3 = 0x1000000, 0x2000000


class TLSOptions(object):
    """Provide one way of specifying what TLS options you want urllib3 to use.

    This allows the user to pass one item instead of several options for
    enabling and disabling TLS specific features. For example::

        opts = TLSOptions(allow_sslv3=True)

    .. attribute:: allow_compression

        Default: ``False``.

    .. attribute:: ciphers

        Default: 'TLS_ECDHE_RSA_AES_GCM_SHA_256'

    .. attribute:: versions

        Default: ['TLSv1_1', 'TLSv1_2']

    .. attribute:: allow_sslv3

        Default: False

    """

    def __init__(self, **kwargs):
        # Default options: (option_name, default)
        options = (('allow_compression', False),
                   ('allow_sslv3', False),
                   ('ciphers', 'TLS_ECDHE_RSA_AES_GCM_SHA_256'),
                   ('versions', ['TLSv1_1', 'TLSv1_2']),
                   )
        _setattr = super(TLSOptions, self).__setattr__
        for option, default in options:
            _setattr(option, kwargs.get(option, default))

    def __setattr__(self, attr, value):
        return TypeError('Attribute "{0}" is not mutable'.format(attr))


def assert_fingerprint(cert, fingerprint):
    """
    Checks if given fingerprint matches the supplied certificate.

    :param cert:
        Certificate as bytes object.
    :param fingerprint:
        Fingerprint as string of hexdigits, can be interspersed by colons.
    """

    # Maps the length of a digest to a possible hash function producing
    # this digest.
    hashfunc_map = {
        16: md5,
        20: sha1
    }

    fingerprint = fingerprint.replace(':', '').lower()
    digest_length, odd = divmod(len(fingerprint), 2)

    if odd or digest_length not in hashfunc_map:
        raise SSLError('Fingerprint is of invalid length.')

    # We need encode() here for py32; works on py2 and p33.
    fingerprint_bytes = unhexlify(fingerprint.encode())

    hashfunc = hashfunc_map[digest_length]

    cert_digest = hashfunc(cert).digest()

    if not cert_digest == fingerprint_bytes:
        raise SSLError('Fingerprints did not match. Expected "{0}", got "{1}".'
                       .format(hexlify(fingerprint_bytes),
                               hexlify(cert_digest)))


def resolve_cert_reqs(candidate):
    """
    Resolves the argument to a numeric constant, which can be passed to
    the wrap_socket function/method from the ssl module.
    Defaults to :data:`ssl.CERT_NONE`.
    If given a string it is assumed to be the name of the constant in the
    :mod:`ssl` module or its abbrevation.
    (So you can specify `REQUIRED` instead of `CERT_REQUIRED`.
    If it's neither `None` nor a string we assume it is already the numeric
    constant which can directly be passed to wrap_socket.
    """
    if candidate is None:
        return CERT_NONE

    if isinstance(candidate, str):
        res = getattr(ssl, candidate, None)
        if res is None:
            res = getattr(ssl, 'CERT_' + candidate)
        return res

    return candidate


def resolve_ssl_version(candidate):
    """
    like resolve_cert_reqs
    """
    if candidate is None:
        return PROTOCOL_SSLv23

    if isinstance(candidate, str):
        res = getattr(ssl, candidate, None)
        if res is None:
            res = getattr(ssl, 'PROTOCOL_' + candidate)
        return res

    return candidate


if SSLContext is not None:  # Python 3.2+
    def ssl_wrap_socket(sock, keyfile=None, certfile=None, cert_reqs=None,
                        ca_certs=None, server_hostname=None,
                        ssl_version=None):
        """
        All arguments except `server_hostname` have the same meaning as for
        :func:`ssl.wrap_socket`

        :param server_hostname:
            Hostname of the expected certificate
        """
        context = SSLContext(ssl_version)
        context.verify_mode = cert_reqs

        # Disable TLS compression to migitate CRIME attack (issue #309)
        OP_NO_COMPRESSION = 0x20000
        context.options |= OP_NO_COMPRESSION
        # Disable SSLv2 and SSLv3. Both are terrible (issues #471, #487)
        context.options |= OP_NO_SSLv2
        context.options |= OP_NO_SSLv3

        if ca_certs:
            try:
                context.load_verify_locations(ca_certs)
            # Py32 raises IOError
            # Py33 raises FileNotFoundError
            except Exception as e:  # Reraise as SSLError
                raise SSLError(e)
        if certfile:
            # FIXME: This block needs a test.
            context.load_cert_chain(certfile, keyfile)
        if HAS_SNI:  # Platform-specific: OpenSSL with enabled SNI
            return context.wrap_socket(sock, server_hostname=server_hostname)
        return context.wrap_socket(sock)

else:  # Python 3.1 and earlier
    def ssl_wrap_socket(sock, keyfile=None, certfile=None, cert_reqs=None,
                        ca_certs=None, server_hostname=None,
                        ssl_version=None):
        return wrap_socket(sock, keyfile=keyfile, certfile=certfile,
                           ca_certs=ca_certs, cert_reqs=cert_reqs,
                           ssl_version=ssl_version)

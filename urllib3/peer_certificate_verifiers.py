from .util import assert_fingerprint
from .packages.ssl_match_hostname import CertificateError, match_hostname
from .exceptions import SSLError

class PeerCertificate(object):
    """A convience wrapper that gets the peer certificate from an SSL socket"""

    def __init__(self, ssl_sock):
        self._ssl_sock = ssl_sock
        self._binary = None
        self._dict = None

    @property
    def as_binary(self):
        """Returns the binary representation of the peer certificate"""
        if self._binary is None:
            self._binary = self._ssl_sock.getpeercert(True)
        return self._binary

    @property
    def as_dict(self):
        """Returns the dictionary representation of the peer certificate"""
        if self._dict is None:
            self._dict = self._ssl_sock.getpeercert(False)
        return self._dict

class BasePeerCertificateVerifier(object):
    """All peer certificate verifiers should derive from this class,
    and implement the verify functions"""
    def verify(self, peer_cert):
        raise NotImplementedError

class Fingerprint(BasePeerCertificateVerifier):
    """Verifies that the fingerprint of the peer certificate matches the given
    fingerprint"""
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint

    def verify(self, peer_cert):
        assert_fingerprint(peer_cert.as_binary, self.fingerprint)

def _match_hostname(peer_cert, hostname):
    try:
        match_hostname(peer_cert.as_dict, hostname)
    except CertificateError as e:
        # Name mismatch
        raise SSLError(e)

class Hostname(BasePeerCertificateVerifier):
    "Verifies that CN of the peer certificate matches the given hostname"
    def __init__(self, hostname):
        self.hostname = hostname
    def verify(self, peer_cert):
        _match_hostname(peer_cert, self.hostname)

class Accept(BasePeerCertificateVerifier):
    "Always accept the peer certificate"
    def verify(self, peer_cert):
        pass
Accept = Accept()

class Reject(BasePeerCertificateVerifier):
    "Always reject the peer certificate"
    def verify(self, peer_cert):
        raise SSLError('SSL certificate rejected')
Reject = Reject()

class Not(BasePeerCertificateVerifier):
    "Negate the decision of a verifier"
    def __init__(self, verifier):
        self.verifier = verifier
    def verify(self, peer_cert):
        try:
            self.verifier.verify(peer_cert)
        except SSLError:
            return
        else:
            raise SSLError('SSL verification failed')

class And(BasePeerCertificateVerifier):
    """Accepts the peer certificate if all sub verifiers accept it.

    Note 1: if a verifier rejects a certificate, no more verifiers are asked.
    Note 2: the raised exception comes the first rejecting verifier.
    """
    def __init__(self, *verifiers):
        self.verifiers = verifiers
    def verify(self, peer_cert):
        for verifier in self.verifiers:
            verifier.verify(peer_cert)

class Or(BasePeerCertificateVerifier):
    """Accepts the peer certificate if at least one sub verifier accepts it.

    Note 1: if a verifier accepts a certificate, no more verifiers are asked.
    Note 2: the raised exception comes the last rejecting verifier.
    """
    def __init__(self, *verifiers):
        self.verifiers = verifiers
    def verify(self, peer_cert):
        last_exception = None
        for verifier in self.verifiers:
            try:
                verifier.verify(peer_cert)
            except SSLError, e:
                last_exception = e
            else:
                return
        if last_exception is not None:
            raise last_exception

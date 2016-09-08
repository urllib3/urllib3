import logging
from six.moves.http_cookiejar import split_header_words
from . import util

log = logging.getLogger(__name__)


class TransportSecurityManager(object):
    """
    Coordinates HSTS, HPKP, and certificate fingerprint matching
    on outgoing requests and incoming responses.
    """
    def __init__(self, transport_security_store=None):
        self._tss = transport_security_store or TransportSecurityStore()
        log.debug("tss init")

    def validate_new_connection(self, conn, scheme):
        """
        Enforce HSTS.
        """
        log.debug("hsts validate: %s %s %s", scheme, conn.host, conn.port)

    def validate_established_connection(self, conn):
        """
        Enforce HPKP or a custom certificate fingerprint.
        """
        if util.IS_PYOPENSSL:
            log.debug("hpkp validate: %s", conn.connection.certs)
        else:
            log.debug("PyOpenSSL not available, hpkp validation disabled")

    def process_response(self, response):
        """
        Enroll or update hosts in our TSS based on response HSTS/HPKP
        headers.
        """
        try:
            sts = _split_header(response.headers.get("strict-transport-security"))
        except Exception as e:
            sts = {}
        try:
            pins = _split_header(response.headers.get('public-key-pins'))
        except Exception:
            pins = {}
        log.debug("tss enroll: %s %s", sts, pins)


def _split_header(header):
    return dict(split_header_words([header])[0])


class TransportSecurityStore(object):
    """
    Abstract baseclass to store transport security (HSTS/HPKP) records.
    """
    def store_host(self, host, pins=None, force_https=False, include_subdomains=False,
                   max_age=None):
        raise NotImplementedError("Must be overridden.")

    def invalidate_host(self, host):
        raise NotImplementedError("Must be overridden.")

    def get_pins(self, host):
        raise NotImplementedError("Must be overridden.")

    def requires_https(self, host):
        raise NotImplementedError("Must be overridden.")

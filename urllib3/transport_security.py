import logging
from six.moves.http_cookiejar import split_header_words

__all__ = ['TransportSecurityManager', 'TransportSecurityStore']


log = logging.getLogger(__name__)


def parse_header(header):
    return split_header_words([header])[0]


class TransportSecurityManager(object):
    """
    Coordinates transport security checks (HSTS, HPKP, certificate
    fingerprint matching, or custom checks) on outgoing requests and
    incoming responses.

    :param transport_security_store:
        A :class:`urllib3.transport_security.TransportSecurityStore`
        instance to be used for persisting host transport security
        preferences.

    """
    def __init__(self, transport_security_store=None):
        self._tss = transport_security_store or TransportSecurityStore()

    def validate_connection(self, conn):
        """
        Enforce connection security checks such as HSTS and HPKP.
        This is a stub, to be implemented later.

        :param conn:
            A :class:`urllib3.connection.HTTPConnection` instance.
        """

    def process_response(self, response):
        """
        Enroll or update hosts in our TSS based on response HSTS/HPKP
        headers.
        This is a stub, to be implemented later.

        :param response:
            A :class:`urllib3.response.HTTPResponse` instance.
        """


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

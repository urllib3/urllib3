import socket
import logging
import time
from collections import defaultdict
from six.moves.http_cookiejar import split_header_words

from .connection import HTTPSConnection
from .exceptions import HSTSError

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

    def validate_hsts(self, conn):
        """
        Enforce connection security checks such as HSTS. This can be called
        multiple times on the same connection before each request,
        since new HSTS headers may be processed in the meantime.

        :param conn:
            A :class:`urllib3.connection.HTTPConnection` instance.

        """
        if not isinstance(conn, HTTPSConnection):
            if self._tss.requires_https(conn.host):
                msg = 'Host {0} has set an HSTS policy preventing plain HTTP connections'
                raise HSTSError(msg.format(conn.host))

    def validate_hpkp(self, conn):
        """
        Enforce HPKP on an SSL connection.

        This is a stub, to be implemented later.

        :param conn:
            A :class:`urllib3.connection.VerifiedHTTPSConnection` instance in a
            connected state.
        """

    def process_response(self, response, conn):
        """
        Enroll or update hosts in our TSS based on response HSTS/HPKP
        headers.

        :param response:
            A :class:`urllib3.response.HTTPResponse` instance.
        :param conn:
            A :class:`urllib3.connection.HTTPSConnection` instance over which the response was
            received.
        """
        if isinstance(conn, HTTPSConnection):
            sts_header = response.headers.get("strict-transport-security")
            if sts_header:
                self._process_sts_header(sts_header, conn.host)

    def _process_sts_header(self, sts_header, host):
        try:
            parsed_sts_header = parse_header(sts_header)
            sts_directives = dict((k.lower(), v) for k, v in parsed_sts_header)
            if len(sts_directives) < len(parsed_sts_header):
                raise HSTSError("Repeating directives in HSTS header, ignoring")
            max_age = sts_directives.get("max-age", "")
            if not max_age.isdigit():
                raise HSTSError("Missing or invalid HSTS max-age directive, ignoring")
            if is_ipaddress(host):
                raise HSTSError("HSTS requested for an IP address, ignoring")
            if "." not in host:
                raise HSTSError("HSTS requested for a non-dot-separated name, ignoring")
            if max_age == "0":
                self._tss.invalidate_host(host)
            else:
                self._tss.store_host(host, force_https=True, max_age=max_age,
                                     include_subdomains="includesubdomains" in sts_directives)
        except Exception as e:
            log.debug(e)


class TransportSecurityStore(object):
    """
    Provides in-memory storage for transport security (HSTS/HPKP) records.
    """
    MAX_AGE_LIMIT = 7776000  # 90 days; see https://tools.ietf.org/html/rfc6797#section-11.2

    def __init__(self):
        self._store = defaultdict(dict)

    def store_host(self, host, pins=None, force_https=False, include_subdomains=False,
                   max_age=None):
        max_age = min(int(max_age), self.MAX_AGE_LIMIT)
        expires = int(time.time()) + max_age
        self._store[host].update(force_https=force_https, include_subdomains=include_subdomains,
                                 expires=expires)

    def invalidate_host(self, host):
        if host in self._store:
            del self._store[host]

    def get_pins(self, host):
        raise NotImplementedError()

    def requires_https(self, host):
        parts = host.split(".")
        for i in range(len(parts)-1):
            superdomain = ".".join(parts[i:])
            if superdomain in self._store:
                tss_record = self._store[superdomain]
                if tss_record["expires"] < time.time():
                    self.invalidate_host(host)
                    continue
                if superdomain == host or tss_record.get("include_subdomains"):
                    if tss_record.get("force_https"):
                        return True
        return False


def is_ipaddress(domain):
    """
    Test wether a string is an IP address
    :param domain:
    :type domain: str
    """
    return is_v4address(domain) or is_v6address(domain)


def _check_inet_pton(family, domain):
    try:
        socket.inet_pton(family, domain)
    except socket.error:
        return False

    return True


def is_v6address(domain):
    """
    Test wether a string is an IPv6 address
    :param domain:
    :type domain: str
    """
    return _check_inet_pton(socket.AF_INET6, domain)


def is_v4address(domain):
    """
    Test wether a string is an IPv4 address
    :param domain:
    :type domain: str
    """
    return _check_inet_pton(socket.AF_INET, domain)

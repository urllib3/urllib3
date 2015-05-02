from datetime import datetime, timedelta
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest
# FIXME will this break on appengine?
import socket

from urllib3.packages import six


split_header_words = six.moves.http_cookiejar.split_header_words


class ExpiringRecord(object):
    """
    Mixin to add expiration to objects.

    :param max_age: Lifetime of the object in seconds.
    :type max_age: int

    :param _timestamp: The time to assume to be `now`.
    :type _timestamp: datetime.datetime
    """
    def __init__(self, max_age, _timestamp=None):
        self.timestamp = _timestamp or self._now()
        self.max_age = max_age

    @property
    def end(self):
        """
        The moment this object expires.

        :rtype: datetime.datetime
        """
        return self.timestamp + timedelta(seconds=self.max_age)

    def is_expired(self, _now=None):
        """
        Wether this object is expired.

        :param _now: The time to assume to be `now`.
        :type _now: datetime.datetime

        :rtype: bool
        """
        now = _now or self._now()
        return self.end < now

    def _now(self):
        """
        A custom implementation of `now()`.

        :note: Handy for mocking.
        """
        return datetime.now()


def _split_header_word(header):
    return split_header_words([header])[0]


def parse_max_age(directive):
    """
    Parse a `max-age` directive as defined by HPKP (:rfc:`7469#section-2.1.2`)
    and HSTS (:rfc:`6797#section-6.1.1`).

    :param directive: The value of the directive to parse.
    :type directive: str

    :returns: A successfully parsed positive integer or `None`
    :rtype: int, NoneType
    """
    if directive is None:
        return None

    try:
        max_age = int(directive)
    except ValueError:
        return None

    if max_age < 0:
        return None

    return max_age


def parse_directives_header(header):
    """
    Parses a header with directives to `(key, value)` tuples.
    The `value` part may be `None`.
    `Keys` re normalized to lowercase.

    :param header:
    :type header: string

    :rtype: Iterable over :class:`tuple`(:class:`str`, :class:`str`).
    """

    for k, v in _split_header_word(header):
        yield k.lower(), v


# FIXME idna?
def _split_domain(domain):
    return domain.split('.')


def match_domains(sub, sup, include_subdomains=False):
    """
    Test wether of two domains are equal, optionally testing for subdomains

    :param sub: The first domain.
                If ``include_subdomains=True`` this is assumend to be the
                *longer/child* domain.
    :type sub: str

    :param sup: The second domain.
    :type sup: str

    :param include_subdomains: Wether to perform subdomain matching.
    :type include_subdomains: bool

    :rtype: bool
    """
    for p, b in zip_longest(
            reversed(_split_domain(sup)),
            reversed(_split_domain(sub))):

        if b is None:
            return False

        if p is None:
            return include_subdomains

        if p != b:
            return False

    return True


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

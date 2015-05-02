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
    def __init__(self, max_age, _timestamp):
        self.timestamp = _timestamp or self._now()
        self.max_age = max_age

    @property
    def end(self):
        return self.timestamp + timedelta(seconds=self.max_age)

    def is_expired(self, _now=None):
        now = _now or self._now()
        return self.end < now

    # for mocking
    def _now(self):
        return datetime.now()


def _split_header_word(header):
    return split_header_words([header])[0]


def parse_max_age(string):
    if string is None:
        return None

    try:
        max_age = int(string)
    except ValueError:
        return None

    if max_age < 0:
        return None

    return max_age


def parse_directives_header(header):
    seen_directives = set()

    for k, v in _split_header_word(header):
        k = k.lower()

        if k in seen_directives:
            yield None, None

        seen_directives.add(k)

        yield k, v


# FIXME idna?
def split_domain(domain):
    return domain.split('.')


def match_domains(sub, sup, include_subdomains):
    for p, b in zip_longest(
            reversed(split_domain(sup)),
            reversed(split_domain(sub))):

        if b is None:
            return False

        if p is None:
            return include_subdomains

        if p != b:
            return False

    return True


def is_ipaddress(domain):
    return is_v4address(domain) or is_v6address(domain)


def _check_inet_pton(family, domain):
    try:
        socket.inet_pton(family, domain)
    except socket.error:
        return False

    return True


def is_v6address(domain):
    return _check_inet_pton(socket.AF_INET6, domain)


def is_v4address(domain):
    return _check_inet_pton(socket.AF_INET, domain)

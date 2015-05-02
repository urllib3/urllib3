from datetime import datetime, timedelta
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest
# FIXME will this break on appengine?
import socket

from urllib3.packages import six


split_header_words = six.moves.http_cookiejar.split_header_words


class HSTSRecord(object):
    def __init__(self, domain, max_age, include_subdomains, _timestamp=None):
        self.domain = domain
        self.max_age = max_age
        self.include_subdomains = include_subdomains
        self.timestamp = _timestamp or datetime.now()

    @property
    def end(self):
        return self.timestamp + timedelta(seconds=self.max_age)

    def is_expired(self, _now=None):
        now = _now or datetime.now()
        return self.end < now

    def matches(self, other):
        return match_domains(other, self.domain, self.include_subdomains)


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


class HSTSStore(object):
    def store_record(self, record):
        raise NotImplementedError("Must be overridden.")

    def invalidate_record(self, domain):
        raise NotImplementedError("Must be overridden.")

    def iter_records(self):
        raise NotImplementedError("Must be overridden.")

    def valid_records(self):
        for record in list(self.iter_records()):
            if record.is_expired():
                self.invalidate_record(record.domain)
            else:
                yield record

    def __len__(self):
        return len(list(self.valid_records()))


class MemoryHSTSStore(HSTSStore):
    def __init__(self):
        self._records = {}

    def iter_records(self):
        return self._records.values()

    def store_record(self, record):
        self._records[record.domain] = record

    def invalidate_record(self, domain):
        self._records.pop(domain, None)


class HSTSManager(object):
    def __init__(self, database):
        self.db = database

    def must_rewrite(self, domain):
        if not domain or is_ipaddress(domain):
            return False

        for record in list(self.db.valid_records()):
            if record.matches(domain):
                return True
        return False

    @staticmethod
    def translate_port(port):
        if port == 80:
            port = 443

        return port

    def rewrite_url(self, url):
        return url._replace(scheme='https', port=self.translate_port(url.port))

    def process_response(self, domain, scheme, response):
        sts = response.getheader('strict-transport-security')

        if not sts or scheme != 'https' or is_ipaddress(domain):
            return

        record = parse_hsts_header(sts, domain)

        if record is None:
            return

        if not record.max_age or record.is_expired():
            self.db.invalidate_record(domain)
        else:
            self.db.store_record(record)


def parse_hsts_header(header, domain):
    max_age = None
    include_subdomains = False

    seen_directives = set()

    # split_header_words needs it argument wrapped in a list and returns a
    # list of list

    result = split_header_words([header])
    for k, v in result[0]:
        k = k.lower()

        if k in seen_directives:
            return None

        if k == 'max-age':
            try:
                max_age = int(v)
            except ValueError:
                continue

        elif k == 'includesubdomains':
                include_subdomains = True

        seen_directives.add(k)

    if max_age is None:
        return None

    return HSTSRecord(domain, max_age, include_subdomains)


# FIXME idna?
def split_domain(domain):
    return domain.split('.')


# FIXME move somewhere else
def is_ipaddress(domain):
    return is_v4address(domain) or is_v6address(domain)


def is_v6address(domain):
    try:
        socket.inet_pton(socket.AF_INET6, domain)
    except socket.error:
        return False

    return True


def is_v4address(domain):
    try:
        socket.inet_pton(socket.AF_INET, domain)
    except socket.error:
        return False

    return True

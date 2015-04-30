from datetime import datetime, timedelta
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest

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
        return self.timestamp + timedelta(self.max_age)

    def is_expired(self, _now=None):
        now = _now or datetime.now()
        return self.end < now

    def matches(self, domain):
        for i, d in zip_longest(split_domain(self.issuer),
                                split_domain(domain)):
            if i != d:
                return False

            if d is None:
                return False

            if i is None:
                return self.include_subdomains

        return True


class HSTSStore(object):
    def store_record(self, record):
        raise NotImplementedError("Must be overridden.")

    def invalidate_record(self, domain):
        raise NotImplementedError("Must be overridden.")

    def iter_records(self):
        raise NotImplementedError("Must be overridden.")

    def __len__(self):
        return len(self.iter_records())


class EphemeralHSTSStore(HSTSStore):
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

        for record in self.db.iter_records():
            if record.is_expired:
                self.db.invalidate_record(record.domain)
            elif record.matches(domain):
                return True
        return False

    @staticmethod
    def scheme_and_port(self, scheme, port):
        if port == 80:
            port = 443

        return 'https', port

    def rewrite_url(self, url):
        new_scheme, new_port = self.scheme_and_port(url.scheme, url.port)
        return url._replace(scheme=new_scheme, port=new_port)

    def process_response(self, domain, scheme, response):
        sts = response.getheader('strict-transport-security')

        if not sts or scheme != 'https':
            return

        record = parse_hsts_header(sts, domain)

        if record is None:
            return

        if not record.max_age or record.is_expired():
            self.db.invalidate_record(domain)

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
            return
        else:
            seen_directives.add(k)

        if k == 'max-age':
            try:
                max_age = int(v)
            except ValueError:
                return
        elif k == 'includesubdomains':
            if v is None:
                include_subdomains = True
            else:
                return

    return HSTSRecord(domain, max_age, include_subdomains)


# FIXME idna?
def split_domain(domain):
    return domain.split('.')


# FIXME this is dirty
def is_ipaddress(domain):
    # assume v6
    if ':' in domain:
        return True

    try:
        int(domain.replace('.', ''))
    except ValueError:
        return False

    return True

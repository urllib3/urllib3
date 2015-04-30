from datetime import datetime, timedelta
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest
from threading import Lock

from urllib3.packages import six


split_header_words = six.moves.http_cookiejar.split_header_words


class HSTSRecord(object):
    def __init__(self, issuer, max_age, include_subdomains, _timestamp=None):
        self.issuer = issuer
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
    def __init__(self):
        self._records = []
        self._lock = Lock()

    def __len__(self):
        return len(self._records)

    def should_enable_hsts(self, domain):
        for record in self._records:
            if not record.is_expired and record.matches(domain):
                return True
        return False

    def scheme_and_port(self, scheme, port):
        if port == 80:
            port = 443

        return 'https', port

    def _rewrite_url(self, url):
        new_scheme, new_port = self.scheme_and_port(url.scheme, url.port)
        return url._replace(scheme=new_scheme, port=new_port)

    def _prune(self):
        with self._lock:
            self._records = [x for x in self._records if not self.is_expired]

    def add_header(self, domain, header):
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

            if k == 'includesubdomains':
                if v is None:
                    include_subdomains = True
                else:
                    return

        self._records.append(HSTSRecord(domain, max_age, include_subdomains))


# FIXME idna?
def split_domain(domain):
    return domain.split('.')

from datetime import datetime, timedelta
try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest
# FIXME will this break on appengine?
import socket

from urllib3.packages import six


split_header_words = six.moves.http_cookiejar.split_header_words


__all__ = ['HSTSManager', 'HSTSStore', 'MemoryHSTSStore']


class HSTSRecord(object):
    """
    A single HSTS record.
    """
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
    """
    Abstract baseclass to store :class:`HSTSRecords <.HSTSRecord>`.
    """
    def store_record(self, record):
        """
        :note: Implement in subclasses.

        :param record:
        :type record: .HSTSRecord
        """
        raise NotImplementedError("Must be overridden.")

    def invalidate_record(self, domain):
        """
        :note: Implement in subclasses.

        :param domain:
        :type domain: str
        """
        raise NotImplementedError("Must be overridden.")

    def iter_records(self):
        """
        :note: Implement in subclasses.

        :rtype: iterable over :class:`HSTSRecords <.HSTSRecord>`.
        """
        raise NotImplementedError("Must be overridden.")

    def valid_records(self):
        """
        Yields all valid :class:`HSTSRecords <.HSTSRecord>` in the store,
        explicitly deleting expired entries as it encounters them.

        :rtype: iterable over :class:`HSTSRecords <.HSTSRecord>`.
        """
        for record in list(self.iter_records()):
            if record.is_expired():
                self.invalidate_record(record.domain)
            else:
                yield record

    def __len__(self):
        return len(list(self.valid_records()))


class MemoryHSTSStore(HSTSStore):
    """
    The default, in-memory HSTS store.

    :warning:
       This does not persist any records, so its usefulnet is only limited.
       You are strongly encouraged to provide use your own, persistent
       :class:`.HSTSStore`.
    """
    def __init__(self):
        self._records = {}

    def iter_records(self):
        return self._records.values()

    def store_record(self, record):
        self._records[record.domain] = record

    def invalidate_record(self, domain):
        self._records.pop(domain, None)


class HSTSManager(object):
    """
    :param database: The backend to store all records.
    :type database: :class:`.HSTSStore`
    """
    def __init__(self, database):
        self.db = database

    def must_rewrite(self, domain):
        """
        Test if we have to rewrite requests to a domain against our database.

        :param url: The domain to check.
        :type url: str

        :returns: Wether we have to rewrite requests to this domain.
        :rtype: bool
        """
        if not domain or is_ipaddress(domain):
            return False

        for record in list(self.db.valid_records()):
            if record.matches(domain):
                return True
        return False

    def rewrite_url(self, url):
        """
        Rewrites an URL in compliance with HSTS

        :param url: The original URL.
        :type header: str

        :returns: The rewritten URL.
        :rtype: str
        """
        return url._replace(scheme='https', port=translate_port(url.port))

    def process_header(self, domain, scheme, header):
        """ Processes a ``Strict-Transport-Security`` header

        This checks wether the scheme is corrent and the header is present.
        If so it adds a new record to the database.

        :param domain: The domain of the response was received from.
        :type domain: str

        :param scheme: The protocol scheme the response was received over.
        :type scheme: str

        :param header: The contents of a ``Strict-Transport-Security`` header.
        :type header: str

        :returns: Wether a new record has been added to the database.
        :rtype: bool
        """
        if not header or scheme != 'https' or is_ipaddress(domain):
            return False

        record = parse_hsts_header(header, domain)

        if record is None:
            return False

        if not record.max_age or record.is_expired():
            self.db.invalidate_record(domain)
        else:
            self.db.store_record(record)

        return True

    def process_response(self, domain, scheme, response):
        """
        Processes a HTTPS response for HSTS

        Performs the same checks as :meth:`.process_header`.

        :param domain: See :meth:`.process_header`
        :param scheme: See :meth:`.process_header`

        :param response: The response received.
        :type response: :class:`httplib.HTTPResponse` or
                        :class:`urllib3.response.HTTPResponse`

        :returns: See :meth:`.process_header`.
        """
        sts = response.getheader('strict-transport-security')

        if not sts:
            return False

        return self.process_header(domain, scheme, sts)


def translate_port(port):
    if port == 80:
        return 443
    return port


def split_header_word(header):
    return split_header_words([header])[0]


def parse_hsts_header(header, domain):
    max_age = None
    include_subdomains = False

    seen_directives = set()

    for k, v in split_header_word(header):
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

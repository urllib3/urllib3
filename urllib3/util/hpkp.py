# -*- coding: utf-8 -*-
import base64
import collections
import hashlib
import logging
import time

from ..exceptions import HPKPError

from OpenSSL import crypto


log = logging.getLogger(__name__)


class HPKPDatabase(object):
    """
    An ABC defining the interface required to be a HPKP Database. Databases
    with custom functionality *must* implement all of this interface, as
    urllib3 requires it. They *may* optionally implement other features.

    This interface is a simple storage interface, it does not implement any
    security-critical HPKP logic. That logic is entirely implemented in the
    :class:`HPKPManager <urllib3.util.hpkp.HPKPManager>` object. Thus, this
    object is not required to perform any validation of the objects passed to
    it.
    """
    def store_host(self, known_host):
        """
        Store a single known pinned host. Any host passed to this function is
        guaranteed to be valid for at least some time in the future, and so
        may be safely stored.

        :param known_host: A single ``KnownPinnedHost`` object.
        """
        raise NotImplementedError("Must be overridden.")

    def invalidate_host(self, domain):
        """
        Invalidate a single ``KnownPinnedHost`` object, for the given domain.
        This object should be removed from whatever storage medium is being
        used.
        """
        raise NotImplementedError("Must be overridden.")

    def iter_hosts(self):
        """
        Return an iterable of ``KnownPinnedHost`` objects.
        """
        raise NotImplementedError("Must be overridden.")

    def get_hosts_by_domain(self, domain):
        """
        Return any stored ``KnownPinnedHost`` object for which ``domain`` is
        a subdomain.

        A default implementation exists for anything that implements
        ``iter_hosts``.

        :returns: A list of ``KnownPinnedHost`` objects, sorted by the length
            of their domain, from longest to shortest.
        """
        hosts = []
        split_domain = list(reversed(domain.split('.')))
        split_domain_part_count = len(split_domain)

        for host in self.iter_hosts():
            if host.domain == domain:
                hosts.append(host)
                continue

            # Check if this KnownPinnedHost is a parent domain of domain. For
            # that to be true, the KnownPinnedHost domain must be made of
            # fewer parts than the domain, and the higher order parts must
            # be equal.
            split_host = list(reversed(host.domain.split('.')))
            part_count = len(split_host)

            if part_count >= split_domain_part_count:
                # Too many parts, cannot be a parent domain.
                continue

            if split_host == split_domain[:part_count]:
                # Parent domain!
                hosts.append(host)

        # Sort by domain length, longest first.
        hosts.sort(key=lambda h: len(h.domain), reverse=True)

        return hosts


class MemoryHPKPDatabase(HPKPDatabase):
    """
    The default, in-memory HPKP database. This provides ephemeral HPKP storage,
    in-memory. It is not recommended for high-security production use, but it
    is better than nothing.
    """
    def __init__(self):
        self.hosts = {}

    def store_host(self, known_host):
        log.debug("Storing host %s", known_host)
        self.hosts[known_host.domain] = known_host

    def invalidate_host(self, domain):
        log.debug("Invalidating host %s", domain)
        del self.hosts[domain]

    def iter_hosts(self):
        return self.hosts.values()


class HPKPManager(object):
    """
    An object that manages HPKP for urllib3.

    This object is responsible for validating HPKP for HTTPS connections. It
    employs a :class:`HPKPDatabase <urllib3.util.hpkp.HPKPDatabase>` object to
    manage the actual storage, but the logic is contained in this class.
    """
    def __init__(self, database):
        self.db = database

    def validate_connection(self, domain, socket):
        """
        For a given connection, confirm that it passes HPKP validation.

        This checks whether there are any ``KnownPinnedHost``s for the given
        connection. If they are, validates that the presented certificate
        actually matches the pin.
        """
        log.debug("Validating connection to %s" % domain)
        hosts = self.db.get_hosts_by_domain(domain)
        if not hosts:
            # This connection has not previously done any key pinning, so
            # there's no validation to do.
            log.debug("No trust information for this host")
            return

        host = self._find_valid_pinned_host(domain, hosts)
        if host is None:
            # Again, no previous pinning was done on this connection, so
            # there's no validation to do.
            log.debug("No previous pinning done for this host.")
            return

        # If we got this far, we have a KnownPinnedHost in hand that applies to
        # this connection. Get the certificate and check it matches one of the
        # pins. If it doesn't we'll blow up here.
        valid = _validate_pin(socket, host)
        if valid:
            log.debug(
                "Successfully validated connection to %s using HPKP", domain
            )
        return _validate_pin(socket, host)

    def process_response(self, domain, response):
        """
        Processes a HTTPS response for HPKP.

        This method checks whether the PKP header is present on the request,
        and if it is updates its store of key pins. It also validates the
        connection against the HPKP header, confirming that it does pass at
        this stage.
        """
        log.debug("Searching for PKP header on HTTPS response")

        # TODO: Handle ip address domains.
        # If no PKP header is provided, then no action is required.
        pkp = response.getheader('public-key-pins')
        if not pkp:
            log.info("No PKP header on connection.")
            return

        # Try to get the pins out. If this fails for any reason, abort the
        # pinning process.
        try:
            pin = parse_public_key_pins(pkp, domain)
        except HPKPError:
            log.warning("Unable to parse key pins from PKP header %s", pkp)
            return

        # Having found pins, we should check whether the pin is valid for this
        # connection. If it isn't, we simply don't trust the header: it's not a
        # full blown security violation.
        try:
            valid = _validate_pin(response.fp._sock, pin)
        except HPKPError:
            log.warning("Error encountered validating pin for %s", domain)
            return
        else:
            if not valid:
                log.warning("Pin header %s not valid for %s", pkp, domain)
                return

        # Quick check: if the max-age is 0, or the expiry date is after now,
        # we should invalidate any pin we already have for this domain and
        # exit.
        if not pin.max_age or (pin.max_age + pin.start_date <= time.time()):
            log.debug("Invalidate pin for domain %s", domain)
            self.db.invalidate_host(domain)
            return

        # Otherwise, we can store off this pin. Hooray, we're done!
        self.db.store_host(pin)

    def _find_valid_pinned_host(self, domain, hosts):
        """
        Locates the most specific valid ``KnownPinnedHost`` for a given domain.

        If none of the owned hosts are valid for this domain, returns ``None``.

        :param domain: The domain being validated.
        :param hosts: A list of ``KnownPinnedHost`` objects whose domains are
            either the same as ``domain``, or are parent domains of ``domain``.
        """
        for host in hosts:
            # First, check whether this host is still valid. If it's not, throw
            # it away and move on.
            if (host.start_date + host.max_age) < time.time():
                log.debug("Found old pin for %s", host.domain)
                self.db.invalidate_host(host.domain)
                continue

            # Now, check whether this KnownPinnedHost applies to this
            # connection. It does if the domain either exactly matches the KPH
            # domain, or if the KPH has include_subdomains set to True.
            if domain == host.domain or host.include_subdomains:
                log.debug("Found relevant pin for %s", host.domain)
                return host

# An object that holds information about a KnownPinnedHost. This object
# basically just stores string data, so there's no real need to do anything
# clever here.
KnownPinnedHost = collections.namedtuple(
    'KnownPinnedHost',
    ['domain', 'pins', 'max_age', 'include_subdomains', 'report_uri', 'start_date']
)


def parse_public_key_pins(header, domain):
    """
    Parses a Public-Key-Pins header, returning a KnownPinnedHost. Invalid
    headers cause exceptions to be thrown.

    :param header: The PKP header value.
    :param domain: The domain name used in the request. Must not be an IP
        address.
    """
    # TODO: This method is super complicated, refactor.
    # Parse the directives. Split any OWS, and then split the directives.
    directives = header.split(';')

    pin_directives = []
    max_age = None
    include_subdomains = False
    report_uri = None

    for directive in directives:
        # Strip any OWS, then split into name and value. All directives have
        # names, but frustratingly they don't all have values.
        directive = directive.strip().split('=', 1)
        name = directive[0].lower()
        try:
            value = directive[1]
        except IndexError:
            value = None

        if name == 'pin-sha256':
            value = unquote_string(value)
            pin_directives.append(value)
        elif name == 'max-age':
            # There may only be one max-age directive. Be careful about
            # policing this, we don't want to accidentally allow more than one.
            if max_age:
                raise HPKPError("Multiple max-age directives in PKP header")

            max_age = int(unquote_string(value))
            if max_age < 0:
                raise HPKPError("max-age must be positive")
        elif name == 'includesubdomains':
            include_subdomains = True
        elif name == 'report-uri':
            if report_uri:
                raise HPKPError("Multiple report-uri directives in PKP header")

            report_uri = unquote_string(value)

    if not pin_directives:
        raise HPKPError("No pin directives in PKP header")

    # LUKASA: Is the use of time.time() safe here? Probably not.
    return KnownPinnedHost(
        domain, pin_directives, max_age, include_subdomains, report_uri, time.time()
    )


def _validate_pin(connection, host, shortcut=True):
    """
    Validates that a TLS connection matches a specific pin.

    If shortcut is ``True``, returns as soon as a matching cert is found: do
    not use the return value in this case.

    Returns True if the pin contains at least one key *not* used in this
    certificate chain. Returns False if the pin only contains certificates in
    the chain.
    """
    match = False
    non_match = False

    # We ideally want to grab the whole cert chain here.
    certificates = connection.connection.certs

    for binary_certificate in certificates:
        # For each cert in the chain, get a base64-encoded form of the
        # SHA256 of the public key and check whether it's in the pin list.
        if _certificate_in_pins(binary_certificate, host):
            if shortcut:
                return True

            match = True
        else:
            non_match = True

    if not match:
        log.error("Failed to validate trust chain with HPKP!")
        raise HPKPError("Failed to validate trust chain with HPKP!")

    valid_chain = match and non_match
    if not valid_chain:
        log.warning("Invalid HPKP chain provided")

    return valid_chain

def _certificate_in_pins(cert, host):
    """
    For a single DER certificate, check whether the KnownPinnedHost has
    pinned it.
    """
    key = cert.get_pubkey()
    public_key_raw = crypto.dump_publickey(crypto.FILETYPE_ASN1, key)
    public_key_sha256 = hashlib.sha256(public_key_raw).digest()
    public_key_sha256_base64 = base64.b64encode(public_key_sha256)

    return public_key_sha256_base64 in host.pins


def unquote_string(string):
    """
    Strips the quoting from a quoted-string literal, as per RFC 7230.
    """
    return string.strip('"')

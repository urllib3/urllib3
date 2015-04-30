# -*- coding: utf-8 -*-
import collections
import time

from urllib3.exceptions import HPKPError


# An object that holds information about a KnownPinnedHost. This object
# basically just stores string data, so there's no real need to do anything
# clever here.
KnownPinnedHost = collections.namedtuple(
    'KnownPinnedHost',
    ['pins', 'max_age', 'include_subdomains', 'report_uri', 'start_date']
)


def parse_public_key_pins(header):
    """
    Parses a Public-Key-Pins header, returning a KnownPinnedHost. Invalid
    headers cause exceptions to be thrown.
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
        name = directive[0]
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
        elif name == 'includeSubDomains':
            include_subdomains = True
        elif name == 'report-uri':
            if report_uri:
                raise HPKPError("Multiple report-uri directives in PKP header")

            report_uri = unquote_string(value)

    if not pin_directives:
        raise HPKPError("No pin directives in PKP header")

    # LUKASA: Is the use of time.time() safe here? Probably not.
    return KnownPinnedHost(
        pin_directives, max_age, include_subdomains, report_uri, time.time()
    )


def unquote_string(string):
    """
    Strips the quoting from a quoted-string literal, as per RFC 7230.
    """
    return string.strip('"')

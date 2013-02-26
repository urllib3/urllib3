from __future__ import unicode_literals

import os
from ssl import PROTOCOL_TLSv1, CERT_REQUIRED
import sys
import urllib3
from urllib3.util import HAS_SNI

CA_BUNDLE = '/etc/ssl/certs/ca-certificates.crt'

hosts = ['alice', 'bob', 'carol', 'dave', 'mallory', 'www']


def test_sni_really_well():
    if not HAS_SNI:
        from nose.plugins.skip import SkipTest
        raise SkipTest('SNI not supported')

    if not 'URLLIB3_EXTERNAL_TESTS' in os.environ:
        from nose.plugins.skip import SkipTest
        raise SkipTest('External tests not wanted')

    yield assert_for_host, 'sni.velox.ch'
    for host in hosts:
        hostname = host + '.sni.velox.ch'
        yield assert_for_host, hostname


def assert_for_host(hostname):
    ### FIXME - test this without connecting to the big, bad Internet.
    pool = urllib3.HTTPSConnectionPool(hostname,
                                       strict=True,
                                       cert_reqs=CERT_REQUIRED,
                                       ca_certs=CA_BUNDLE,
                                       ssl_version=PROTOCOL_TLSv1)

    r = pool.request('GET', '/')
    content = r.data.decode('utf-8', 'replace')
    assert 'Great!' in content, \
        'Did not get "Great!" from https://%s/: %s' % (hostname, content)
    assert hostname in content

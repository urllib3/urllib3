.. _security:

Security: Verified HTTPS with SSL/TLS
=====================================

Very important fact: **By default, urllib3 does not verify HTTPS requests.**

The historic reason for this is that we rely on ``httplib`` for some of the
HTTP protocol implementation, and ``httplib`` does not verify requests out of
the box. This is not a good reason, but here we are.

Luckily, it's not too hard to enable verified HTTPS requests and there are a
few ways to do it.


Python with SSL enabled
-----------------------

First we need to make sure your Python installation has SSL enabled. Easiest
way to check is to simply open a Python shell and type `import ssl`::

    >>> import ssl
    Traceback (most recent call last):
      ...
    ImportError: No module named _ssl

If you got an ``ImportError``, then your Python is not compiled with SSL support
and you'll need to re-install it. Read
`this StackOverflow thread <https://stackoverflow.com/questions/5128845/importerror-no-module-named-ssl>`_
for details.

Otherwise, if ``ssl`` imported cleanly, then we're ready to setup our certificates:
:ref:`certifi-with-urllib3`.


Enabling SSL on Google AppEngine
++++++++++++++++++++++++++++++++

If you're using Google App Engine, you'll need to add ``ssl`` as a library
dependency to your yaml file, like this::

    libraries:
    - name: ssl
      version: latest

If it's still not working, you may need to enable billing on your account
to `enable using sockets
<https://developers.google.com/appengine/docs/python/sockets/>`_.


.. _certifi-with-urllib3:

Using Certifi with urllib3
--------------------------

`Certifi <http://certifi.io/>`_ is a package which ships with Mozilla's root
certificates for easy programmatic access.

1. Install the Python ``certifi`` package::

    $ pip install certifi

2. Setup your pool to require a certificate and provide the certifi bundle::

    import urllib3
    import certifi

    http = urllib3.PoolManager(
        cert_reqs='CERT_REQUIRED', # Force certificate check.
        ca_certs=certifi.where(),  # Path to the Certifi bundle.
    )

    # You're ready to make verified HTTPS requests.
    try:
        r = http.request('GET', 'https://example.com/')
    except urllib3.exceptions.SSLError as e:
        # Handle incorrect certificate error.
        ...

Make sure to update your ``certifi`` package regularly to get the latest root
certificates.


Using your system's root certificates
-------------------------------------

Your system's root certificates may be more up-to-date than maintaining your
own, but the trick is finding where they live. Different operating systems have
them in different places.

For example, on most Linux distributions they're at
``/etc/ssl/certs/ca-certificates.crt``. On Windows and OS X? `It's not so simple
<https://stackoverflow.com/questions/10095676/openssl-reasonable-default-for-trusted-ca-certificates>`_.

Once you find your root certificate file::

    import urllib3

    ca_certs = "/etc/ssl/certs/ca-certificates.crt"  # Or wherever it lives.

    http = urllib3.PoolManager(
        cert_reqs='CERT_REQUIRED', # Force certificate check.
        ca_certs=ca_certs,         # Path to your certificate bundle.
    )

    # You're ready to make verified HTTPS requests.
    try:
        r = http.request('GET', 'https://example.com/')
    except urllib3.exceptions.SSLError as e:
        # Handle incorrect certificate error.
        ...


OpenSSL / PyOpenSSL
-------------------

By default, we use the standard library's ``ssl`` module. Unfortunately, there
are several limitations which are addressed by PyOpenSSL:

- (Python 2.x) SNI support.
- (Python 2.x-3.2) Disabling compression to mitigate `CRIME attack
  <https://en.wikipedia.org/wiki/CRIME_(security_exploit)>`_.

To use the Python OpenSSL bindings instead, you'll need to install the required
packages::

    $ pip install pyopenssl ndg-httpsclient pyasn1

Once the packages are installed, you can tell urllib3 to switch the ssl backend
to PyOpenSSL with :func:`~urllib3.contrib.pyopenssl.inject_into_urllib3`::

    import urllib3.contrib.pyopenssl
    urllib3.contrib.pyopenssl.inject_into_urllib3()

Now you can continue using urllib3 as you normally would.

For more details, check the :mod:`~urllib3.contrib.pyopenssl` module.


InsecureRequestWarning
----------------------

.. versionadded:: 1.9

Unverified HTTPS requests will trigger a warning::

    urllib3/connectionpool.py:736: InsecureRequestWarning: Unverified HTTPS
    request is being made. Adding certificate verification is strongly advised.
    See: https://urllib3.readthedocs.org/en/latest/security.html

This would be a great time to enable HTTPS verification:
:ref:`certifi-with-urllib3`.

If you know what you're doing and would like to disable this and other warnings,
you can use :func:`~urllib3.disable_warnings`::

    import urllib3
    urllib3.disable_warnings()

Making unverified HTTPS requests is strongly discouraged. ˙ ͜ʟ˙

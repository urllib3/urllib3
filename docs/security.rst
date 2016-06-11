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
way to check is to simply open a Python shell and type ``import ssl``::

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


.. _pyopenssl:

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

If ``cryptography`` fails to install as a dependency, make sure you have `libffi
<http://sourceware.org/libffi/>`_ available on your system and run
``pip install cryptography``.

Once the packages are installed, you can tell urllib3 to switch the ssl backend
to PyOpenSSL with :func:`~urllib3.contrib.pyopenssl.inject_into_urllib3`::

    import urllib3.contrib.pyopenssl
    urllib3.contrib.pyopenssl.inject_into_urllib3()

Now you can continue using urllib3 as you normally would.

For more details, check the :mod:`~urllib3.contrib.pyopenssl` module.

Installing urllib3 with SNI support and certificates
----------------------------------------------------

By default, if you need to use SNI on Python 2.6 or Python 2.7.0-2.7.8, you
have to install PyOpenSSL, ndghttpsclient, and pyasn1 separately. Further, to
use certifi you have to install it separately. If you know that you want these
dependencies when you install urllib3, you can now do::

    pip install urllib3[secure]

This will install the SNI dependencies on Python 2.6 and 2.7 (we cannot yet
restrict the microversion for 2.7) and certifi on all versions of Python.

.. note::

    If you do this on linux, e.g., Ubuntu 14.04, you will need extra system
    dependencies for PyOpenSSL. Specifically, PyOpenSSL requires cryptography
    which will require you to install:

    - build-essential
    - python-dev
    - libffi-dev
    - libssl-dev

    The package names may vary depending on the distribution of linux you are
    using.

.. _insecurerequestwarning:

InsecureRequestWarning
----------------------

.. versionadded:: 1.9

Unverified HTTPS requests will trigger a warning via Python's ``warnings`` module::

    urllib3/connectionpool.py:736: InsecureRequestWarning: Unverified HTTPS
    request is being made. Adding certificate verification is strongly advised.
    See: https://urllib3.readthedocs.io/en/latest/security.html

This would be a great time to enable HTTPS verification:
:ref:`certifi-with-urllib3`.

For info about disabling warnings, see `Disabling Warnings`_.


InsecurePlatformWarning
-----------------------

.. versionadded:: 1.11

Certain Python platforms (specifically, versions of Python earlier than 2.7.9)
have restrictions in their ``ssl`` module that limit the configuration that
``urllib3`` can apply. In particular, this can cause HTTPS requests that would
succeed on more featureful platforms to fail, and can cause certain security
features to be unavailable.

If you encounter this warning, it is strongly recommended you:

- upgrade to a newer Python version
- upgrade ``ndg-httpsclient`` with ``pip install --upgrade ndg-httpsclient``
- use pyOpenSSL as described in the :ref:`pyopenssl` section

For info about disabling warnings, see `Disabling Warnings`_.


SNIMissingWarning
-----------------

.. versionadded:: 1.13

Certain Python distributions (specifically, versions of Python earlier than
2.7.9) and older OpenSSLs have restrictions that prevent them from using the
SNI (Server Name Indication) extension. This can cause unexpected behaviour
when making some HTTPS requests, usually causing the server to present the a
TLS certificate that is not valid for the website you're trying to access.

If you encounter this warning, it is strongly recommended that you upgrade
to a newer Python version, or that you use pyOpenSSL as described in the
:ref:`pyopenssl` section.

For info about disabling warnings, see `Disabling Warnings`_.


Disabling Warnings
------------------

Making unverified HTTPS requests is strongly discouraged. ˙ ͜ʟ˙

But if you understand the ramifications and still want to do it...

Within the code
+++++++++++++++

If you know what you're doing and would like to disable all ``urllib3`` warnings,
you can use :func:`~urllib3.disable_warnings`::

    import urllib3
    urllib3.disable_warnings()

Alternatively, if you are using Python's ``logging`` module, you can capture the
warnings to your own log::

	logging.captureWarnings(True)

Capturing the warnings to your own log is much preferred over simply disabling
the warnings.

Without modifying code
++++++++++++++++++++++

If you are using a program that uses ``urllib3`` and don't want to change the
code, you can suppress warnings by setting the ``PYTHONWARNINGS`` environment
variable in Python 2.7+ or by using the ``-W`` flag with the Python
interpreter (see `docs
<https://docs.python.org/2/using/cmdline.html#cmdoption-W>`_), such as::

    PYTHONWARNINGS="ignore:Unverified HTTPS request" ./do-insecure-request.py

v2.0 Migration Guide
====================

**urllib3 v2.0 is now available!** Read below for how to get started and what is contained in the new major release.

**🚀 Migrating from 1.x to 2.0**
--------------------------------

We're maintaining **functional API compatibility for most users** to make the
migration an easy choice for almost everyone. Most changes are either to default
configurations, supported Python versions, or internal implementation details.
So unless you're in a specific situation you should notice no changes! 🎉

.. note::

  If you have difficulty migrating to v2.0 or following this guide
  you can `open an issue on GitHub <https://github.com/urllib3/urllib3/issues>`_
  or reach out in `our community Discord channel <https://discord.gg/urllib3>`_.


Timeline for deprecations and breaking changes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The 2.x initial release schedule will look like this:

* urllib3 ``v2.0.0-alpha1`` will be released in November 2022. This release
  contains **minor breaking changes and deprecation warnings for other breaking changes**.
  There may be other pre-releases to address fixes before v2.0.0 is released.
* urllib3 ``v2.0.0`` will be released in early 2023 after some initial integration testing
  against dependent packages and fixing of bug reports.
* urllib3 ``v2.1.0`` will be released in the summer of 2023 with **all breaking changes
  being warned about in v2.0.0**.

.. warning::

  Please take the ``DeprecationWarnings`` you receive when migrating from v1.x to v2.0 seriously
  as they will become errors after 2.1.0 is released.


What are the important changes?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Here's a short summary of which changes in urllib3 v2.0 are most important:

- Python version must be **3.7 or later** (previously supported Python 2.7, 3.5, and 3.6).
- Removed support for non-OpenSSL TLS libraries (like LibreSSL and wolfSSL).
- Removed support for OpenSSL versions older than 1.1.1.
- Removed support for Python implementations that aren't CPython or PyPy3 (previously supported Google App Engine, Jython).
- Removed the ``urllib3.contrib.ntlmpool`` module.
- Deprecated the ``urllib3.contrib.pyopenssl``, ``urllib3.contrib.securetransport`` modules, will be removed in v2.1.0.
- Deprecated the ``urllib3[secure]`` extra, will be removed in v2.1.0.
- Deprecated the ``HTTPResponse.getheaders()`` method in favor of ``HTTPResponse.headers``, will be removed in v2.1.0.
- Deprecated the ``HTTPResponse.getheader(name, default)`` method in favor of ``HTTPResponse.headers.get(name, default)``, will be removed in v2.1.0.
- Deprecated URLs without a scheme (ie 'https://') and will be raising an error in a future version of urllib3.
- Changed the default minimum TLS version to TLS 1.2 (previously was TLS 1.0).
- Removed support for verifying certificate hostnames via ``commonName``, now only ``subjectAltName`` is used.
- Removed the default set of TLS ciphers, instead now urllib3 uses the list of ciphers configured by the system.

For a full list of changes you can look at `the changelog <https://github.com/urllib3/urllib3/blob/main/CHANGES.rst>`_.


Migrating as a package maintainer?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you're a maintainer of a package that uses urllib3 under the hood then this section is for you.
You may have already seen an issue opened from someone on our team about the upcoming release.

The primary goal for migrating to urllib3 v2.x should be to ensure your package supports **both urllib3 v1.26.x and v2.0 for some time**.
This is to reduce the chance that diamond dependencies are introduced into your users' dependencies which will then cause issues
with them upgrading to the latest version of **your package**.

The first step to supporting urllib3 v2.0 is to make sure the version v2.x not being excluded by ``install_requires``. You should
ensure your package allows for both urllib3 1.26.x and 2.0 to be used:

.. code-block:: python

  # setup.py (setuptools)
  setup(
    ...
    install_requires=["urllib3>=1.26,<3"]
  )

  # pyproject.toml (hatch)
  [project]
  dependencies = [
    "urllib3>=1.26,<3"
  ]

Next you should try installing urllib3 v2.0 locally and run your test suite.

.. code-block:: bash

  $ python -m pip install -U --pre 'urllib3>=2.0.0a1'


Because there are many ``DeprecationWarnings`` you should ensure that you're
able to see those warnings when running your test suite. To do so you can add
the following to your test setup to ensure even ``DeprecationWarnings`` are
output to the terminal:

.. code-block:: bash

  # Set PYTHONWARNING=default to show all warnings.
  $ export PYTHONWARNINGS="default"

  # Run your test suite and look for failures.
  # Pytest automatically prints all warnings.
  $ pytest tests/

or you can opt-in within your Python code:

.. code-block:: python

  # You can change warning filters according to the filter rules:
  # https://docs.python.org/3/library/warnings.html#warning-filter
  import warnings
  warnings.filterwarnings("default", category=DeprecationWarning)

Any failures or deprecation warnings you receive should be fixed as urllib3 v2.1.0 will remove all
deprecated features. Many deprecation warnings will make suggestions about what to do to avoid the deprecated feature.

Warnings will look something like this:

.. code-block:: bash

  DeprecationWarning: 'ssl_version' option is deprecated and will be removed
  in urllib3 v2.1.0. Instead use 'ssl_minimum_version'

Continue removing deprecation warnings until there are no more. After this you can publish a new release of your package
that supports both urllib3 v1.26.x and v2.x.

.. note::

  If you're not able to support both 1.26.x and v2.0 of urllib3 at the same time with your package please
  `open an issue on GitHub <https://github.com/urllib3/urllib3/issues>`_ or reach out in
  `our community Discord channel <https://discord.gg/urllib3>`_.


Migrating as an application developer?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you're someone who writes Python but doesn't ship as a package (things like web services, data science, tools, and more) this section is for you.

Python environments only allow for one version of a dependency to be installed per environment which means
that **all of your dependencies using urllib3 need to support v2.0 for you to upgrade**.

The best way to visualize relationships between your dependencies is using `pipdeptree <https://pypi.org/project/pipdeptree>`_ and ``$ pipdeptree --reverse``:

.. code-block:: bash

  # From inside your Python environment:
  $ python -m pip install pipdeptree
  # We only care about packages requiring urllib3
  $ pipdeptree --reverse | grep "requires: urllib3"

  - botocore==1.29.8 [requires: urllib3>=1.25.4,<2]
  - requests==2.28.1 [requires: urllib3>=1.21.1,<2]

Reading the output from above, there are two packages which depend on urllib3: ``botocore`` and ``requests``.
The versions of these two packages both require urllib3 that is less than v2.0 (ie ``<2``).

Because both of these packages require urllib3 before v2.0 the new version of urllib3 can't be installed
by default. There are ways to force installing the newer version of urllib3 v2.0 (ie pinning to ``urllib3==2.0.0``)
which you can do to test your application.

It's important to know that even if you don't upgrade all of your services to 2.x
immediately you will `receive security fixes on the 1.26.x release stream <#security-fixes-for-urllib3-v1-26-x>` for some time.


Security fixes for urllib3 v1.26.x
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Thanks to support from `Tidelift <https://tidelift.com/subscription/pkg/pypi-urllib3>`_
we're able to continue supporting the v1.26.x release stream with
security fixes for the foreseeable future 💖

However, upgrading is still recommended as **no new feature developments or non-critical
bug fixes will be shipped to the 1.26.x release stream**.

If your organization relies on urllib3 and is interested in continuing support you can learn
more about the `Tidelift Subscription for Enterprise <https://tidelift.com/subscription/pkg/pypi-urllib3?utm_source=pypi-urllib3&utm_medium=referral&utm_campaign=docs>`_.

**🤔 Common upgrading issues**
-------------------------------

ssl module is compiled with OpenSSL 1.0.2.k-fips
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

  ImportError: urllib3 v2.0 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'OpenSSL 1.0.2k-fips  26 Jan 2017'.
  See: https://github.com/urllib3/urllib3/issues/2168

Remediation depends on your system:

- **AWS Lambda**: Upgrade to the Python3.10 runtime as it uses OpenSSL 1.1.1. Alternatively, you can
  use a `custom Docker image
  <https://aws.amazon.com/blogs/aws/new-for-aws-lambda-container-image-support/>`_ and ensure you
  use a Python build that uses OpenSSL 1.1.1 or later.
- **Amazon Linux 2**: Upgrade to `Amazon Linux 2023
  <https://aws.amazon.com/linux/amazon-linux-2023/>`_. Alternatively, you can install OpenSSL 1.1.1
  on Amazon Linux 2 using ``yum install openssl11 openssl11-devel`` and then install Python with a
  tool like pyenv.
- **Red Hat Enterpritse Linux 7 (RHEL 7)**: Upgrade to RHEL 8 or RHEL 9.
- **Read the Docs**: Upgrade your `configuration file to use Ubuntu 22.04
  <https://docs.readthedocs.io/en/stable/config-file/v2.html>`_ by using ``os: ubuntu-22.04`` in the
  ``build`` section. Feel free to use the `urllib3 configuration
  <https://github.com/urllib3/urllib3/blob/2.0.0/.readthedocs.yml>`_ as an inspiration.

docker.errors.dockerexception: error while fetching server api version: request() got an unexpected keyword argument 'chunked'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Upgrade to ``docker==6.1.0`` that is compatible with urllib3 2.0.

ImportError: cannot import name 'gaecontrib' from 'requests_toolbelt._compat'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To be compatible with urllib3 2.0, Requests Toolbelt released version 1.0.0 without Google App
Engine Standard Python 2.7 support. Most users that reported this issue were using the `Pyrebase
<https://github.com/thisbejim/Pyrebase>`_ library that provides an API for the Firebase API. This
library is unmaintained, but `replacements exist
<https://github.com/thisbejim/Pyrebase/issues/435>`_.

``ImportError: cannot import name 'DEFAULT_CIPHERS' from 'urllib3.util.ssl_'``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This likely happens because you're using botocore which `does not support urllib3 2.0 yet
<https://github.com/boto/botocore/issues/2921>`_. The good news is that botocore explicitly declares
in its dependencies that it only supports ``urllib3<2``. Make sure to use a recent pip. That way, pip
will install urllib3 1.26.x until botocore starts supporting urllib3 2.0.

If you're deploying to an AWS environment such as Lambda or a host using Amazon Linux 2,
you'll need to explicitly pin to ``urllib3<2`` in your project to ensure urllib3 2.0 isn't
brought into your environment. Otherwise, this may result in unintended side effects with
the default boto3 installation.

AttributeError: module 'urllib3.connectionpool' has no attribute 'VerifiedHTTPSConnection'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``VerifiedHTTPSConnection`` class has always been documented to be in the
:mod:`~urllib3.connection` module. It used to be possible to import it from
:mod:`~urllib3.connectionpool` but that was acccidental and is no longer possible due to a
refactoring in urllib3 2.0.

Note that the new name of this class is :class:`~urllib3.connection.HTTPSConnection`. It can be used
starting from urllib3 1.25.9.

AttributeError: 'HTTPResponse' object has no attribute 'strict'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``strict`` parameter is unneeded with Python 3 and should be removed.

Pinning urllib3<2
~~~~~~~~~~~~~~~~~

If the advice from the above sections did not help, you can pin urllib3 to 1.26.x by installing
``urllib3<2``. Please do **not** specify ``urllib3==1.26.15`` to make sure you continue getting
1.26.x updates!

While urllib3 1.26.x is still supported, it won't get new features or bug fixes, just security
updates. Consider opening a tracking issue to unpin urllib3 in the future to not stay on 1.26.x
indefinitely.  For more details on the recommended way to handle your dependencies in general, see
`Semantic Versioning Will Not Save You <https://hynek.me/articles/semver-will-not-save-you/>`_. The
second half even uses urllib3 2.0 as an example!


**💪 User-friendly features**
-----------------------------

urllib3 has always billed itself as a **user-friendly HTTP client library**.
In the spirit of being even more user-friendly we've added two features
which should make using urllib3 for tinkering sessions, throw-away scripts,
and smaller projects a breeze!

urllib3.request()
~~~~~~~~~~~~~~~~~

Previously the highest-level API available for urllib3 was a ``PoolManager``,
but for many cases configuring a poolmanager is extra steps for no benefit.
To make using urllib3 as simple as possible we've added a top-level function
for sending requests from a global poolmanager instance:

.. code-block:: python

  >>> import urllib3
  >>> resp = urllib3.request("GET", "https://example.com")
  >>> resp.status
  200

JSON support for requests and responses
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

JSON is everywhere – and now it's in urllib3, too!

If you'd like to send JSON in a request body or deserialize a response body
from JSON into Python objects you can now use the new ``json=`` parameter
for requests and ``HTTPResponse.json()`` method on responses:

.. code-block:: python

  import urllib3

  # Send a request with a JSON body.
  # This adds 'Content-Type: application/json' by default.
  resp = urllib3.request(
      "POST", "https://example.api.com",
      json={"key": "value"}
  )

  # Receive a JSON body in the response.
  resp = urllib3.request("GET", "https://xkcd.com/2347/info.0.json")

  # There's always an XKCD...
  resp.json()
  {
    "num": 2347,
    "img": "https://imgs.xkcd.com/comics/dependency.png",
    "title": "Dependency",
    ...
  }


**✨ Optimized for Python 3.7+**
--------------------------------

In v2.0 we'll be specifically targeting
CPython 3.7+ and PyPy 7.0+ (compatible with CPython 3.7)
and dropping support for Python versions 2.7, 3.5, and 3.6.

By dropping end-of-life Python versions we're able to optimize
the codebase for Python 3.7+ by using new features to improve
performance and reduce the amount of code that needs to be executed
in order to support legacy versions.


**📜 Type-hinted APIs**
-----------------------

You're finally able to run Mypy or other type-checkers
on code using urllib3. This also means that for IDEs
that support type hints you'll receive better suggestions
from auto-complete. No more confusion with ``**kwargs``!

We've also added API interfaces like ``BaseHTTPResponse``
and ``BaseHTTPConnection`` to ensure that when you're sub-classing
an interface you're only using supported public APIs to ensure
compatibility and minimize breakages down the road.

.. note::

  If you're one of the rare few who is subclassing connections
  or responses you should take a closer look at detailed changes
  in `the changelog <https://github.com/urllib3/urllib3/blob/main/CHANGES.rst>`_.


**🔐 Modern security by default**
---------------------------------

HTTPS requires TLS 1.2+
~~~~~~~~~~~~~~~~~~~~~~~

Greater than 95% of websites support TLS 1.2 or above.
At this point we're comfortable switching the default
minimum TLS version to be 1.2 to ensure high security
for users without breaking services.

Dropping TLS 1.0 and 1.1 by default means you
won't be vulnerable to TLS downgrade attacks
if a vulnerability in TLS 1.0 or 1.1 were discovered in
the future. Extra security for free! By dropping TLS 1.0
and TLS 1.1 we also tighten the list of ciphers we need
to support to ensure high security for data traveling
over the wire.

If you still need to use TLS 1.0 or 1.1 in your application
you can still upgrade to v2.0, you'll only need to set
``ssl_minimum_version`` to the proper value to continue using
legacy TLS versions.


Stop verifying commonName in certificates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Dropping support the long deprecated ``commonName``
field on certificates in favor of only verifying
``subjectAltName`` to put us in line with browsers and
other HTTP client libraries and to improve security for our users.


Certificate verification via SSLContext
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default certificate verification is handled by urllib3
to support legacy Python versions, but now we can
rely on Python's certificate verification instead! This
should result in a speedup for verifying certificates
and means that any improvements made to certificate
verification in Python or OpenSSL will be immediately
available.

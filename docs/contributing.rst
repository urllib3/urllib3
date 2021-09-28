Contributing
============

urllib3 is a community-maintained project and we happily accept contributions.

If you wish to add a new feature or fix a bug:

#. `Check for open issues <https://github.com/urllib3/urllib3/issues>`_ or open
   a fresh issue to start a discussion around a feature idea or a bug. There is
   a *Contributor Friendly* tag for issues that should be ideal for people who
   are not very familiar with the codebase yet.
#. Fork the `urllib3 repository on Github <https://github.com/urllib3/urllib3>`_
   to start making your changes.
#. Write a test which shows that the bug was fixed or that the feature works
   as expected.
#. Format your changes with black using command `$ nox -rs format` and lint your
   changes using command `nox -rs lint`.
#. Add a `changelog entry
   <https://github.com/urllib3/urllib3/blob/main/changelog/README.rst>`__.
#. Send a pull request and bug the maintainer until it gets merged and published.


Setting up your development environment
---------------------------------------

In order to setup the development environment all that you need is
`nox <https://nox.thea.codes/en/stable/index.html>`_ installed in your machine::

  $ python -m pip install --user --upgrade nox


Running the tests
-----------------

We use some external dependencies, multiple interpreters and code coverage
analysis while running test suite. Our ``noxfile.py`` handles much of this for
you::

  $ nox --reuse-existing-virtualenvs --sessions test-3.7 test-3.9
  [ Nox will create virtualenv if needed, install the specified dependencies, and run the commands in order.]
  nox > Running session test-3.7
  .......
  .......
  nox > Session test-3.7 was successful.
  .......
  .......
  nox > Running session test-3.9
  .......
  .......
  nox > Session test-3.9 was successful.

There is also a nox command for running all of our tests and multiple python
versions.::

  $ nox --reuse-existing-virtualenvs --sessions test

Note that code coverage less than 100% is regarded as a failing run. Some
platform-specific tests are skipped unless run in that platform.  To make sure
the code works in all of urllib3's supported platforms, you can run our ``nox``
suite::

  $ nox --reuse-existing-virtualenvs --sessions test
  [ Nox will create virtualenv if needed, install the specified dependencies, and run the commands in order.]
  .......
  .......
  nox > Session test-3.7 was successful.
  nox > Session test-3.8 was successful.
  nox > Session test-3.9 was successful.
  nox > Session test-3.10 was successful.
  nox > Session test-pypy was successful.

Our test suite `runs continuously on Travis CI
<https://travis-ci.org/urllib3/urllib3>`_ with every pull request.

To run specific tests or quickly re-run without nox recreating the env, do the following::

  $ nox --reuse-existing-virtualenvs --sessions test-3.8 -- pyTestArgument1 pyTestArgument2 pyTestArgumentN
  [ Nox will create virtualenv, install the specified dependencies, and run the commands in order.]
  nox > Running session test-3.8
  nox > Re-using existing virtual environment at .nox/test-3-8.
  .......
  .......
  nox > Session test-3.8 was successful.

After the ``--`` indicator, any arguments will be passed to pytest.
To specify an exact test case the following syntax also works:
``test/dir/module_name.py::TestClassName::test_method_name``
(eg.: ``test/with_dummyserver/test_https.py::TestHTTPS::test_simple``).
The following argument is another valid example to pass to pytest: ``-k test_methode_name``.
These are useful when developing new test cases and there is no point
re-running the entire test suite every iteration. It is also possible to
further parameterize pytest for local testing.

For all valid arguments, check `the pytest documentation
<https://docs.pytest.org/en/stable/usage.html#stopping-after-the-first-or-n-failures>`_.

Running local proxies
---------------------

If the feature you are developing involves a proxy, you can rely on scripts we have developed to run a proxy locally.

Run an HTTP proxy locally:

.. code-block:: bash

   $ python -m dummyserver.proxy

Run an HTTPS proxy locally:

.. code-block:: bash

   $ python -m dummyserver.https_proxy

Contributing to documentation
-----------------------------

You can build the docs locally using ``nox``:

.. code-block:: bash

  $ nox -rs docs

While writing documentation you should follow these guidelines:

- Use the top-level ``urllib3.request()`` function for smaller code examples. For more involved examples use PoolManager, etc.
- Use double quotes for all strings. (Output, Declaration etc.)
- Use keyword arguments everywhere except for method and url. (ie ``http.request("GET", "https://example.com", headers={...})`` )
- Use HTTPS in URLs everywhere unless HTTP is needed.
- Rules for code examples and naming variables:

  - ``PoolManager`` instances should be named ``http``. (ie ``http = urllib3.PoolManager(...)``)
  - ``ProxyManager`` instances should be named ``proxy``.
  - ``ConnectionPool`` instances should be named ``pool``.
  - ``Connection`` instances should be named ``conn``.
  - ``HTTPResponse`` instances should be named ``resp``.
  -  Only use ``example.com`` or ``httpbin.org`` for example URLs

- Comments within snippets should be useful, if what's being done is apparent
  (such as parsing JSON, making a request) then it can be skipped for that section.
- Comments should always go above a code section rather than below with the exception of print
  statements where the comment containing the result goes below.
- Imports should be their own section separated from the rest of the example with a line of whitespace.
- Imports should minimized if possible. Use import urllib3 instead of from urllib3 import X. 
- Sort imports similarly to isort, standard library first and third-party (like urllib3) come after.
- No whitespace is required between the sections as normally would be in case of isort.
- Add print statements along with a comment below them showing the output, potentially compressed.
- This helps users using the copy-paste button immediately see the results from a script.

Releases
--------

A release candidate can be created by any contributor.

- Announce intent to release on Discord, see if anyone wants to include last minute
  changes.
- Run ``towncrier build`` to update ``CHANGES.rst`` with the release notes, adjust as
  necessary.
- Update ``urllib3/__init__.py`` with the proper version number
- Commit the changes to a ``release-X.Y.Z`` branch.
- Create a pull request and append ``&expand=1&template=release.md`` to the URL before
  submitting in order to include our release checklist in the pull request description.
- Follow the checklist!

Contributing
============

urllib3 is a community-maintained project and we happily accept contributions.

If you wish to add a new feature or fix a bug:

#. `Check for open issues <https://github.com/shazow/urllib3/issues>`_ or open
   a fresh issue to start a discussion around a feature idea or a bug. There is
   a *Contributor Friendly* tag for issues that should be ideal for people who
   are not very familiar with the codebase yet.
#. Fork the `urllib3 repository on Github <https://github.com/shazow/urllib3>`_
   to start making your changes.
#. Write a test which shows that the bug was fixed or that the feature works
   as expected.
#. Send a pull request and bug the maintainer until it gets merged and published.
   :) Make sure to add yourself to ``CONTRIBUTORS.txt``.


Running the tests
-----------------

We use some external dependencies, multiple interpreters and code coverage
analysis while running test suite. Our ``Makefile`` handles much of this for
you as long as you're running it `inside of a virtualenv
<http://docs.python-guide.org/en/latest/dev/virtualenvs/>`_::

  $ make test
  [... magically installs dependencies and runs tests on your virtualenv]
  Ran 182 tests in 1.633s

  OK (SKIP=6)

Note that code coverage less than 100% is regarded as a failing run. Some
platform-specific tests are skipped unless run in that platform.  To make sure
the code works in all of urllib3's supported platforms, you can run our ``tox``
suite::

  $ make test-all
  [... tox creates a virtualenv for every platform and runs tests inside of each]
  py26: commands succeeded
  py27: commands succeeded
  py32: commands succeeded
  py33: commands succeeded
  py34: commands succeeded

Our test suite `runs continuously on Travis CI
<https://travis-ci.org/shazow/urllib3>`_ with every pull request.


Sponsorship
-----------

Please consider sponsoring urllib3 development, especially if your company
benefits from this library.

We welcome your patronage on `Bountysource <https://www.bountysource.com/teams/urllib3>`_:

* `Contribute a recurring amount to the team <https://salt.bountysource.com/checkout/amount?team=urllib3>`_
* `Place a bounty on a specific feature <https://www.bountysource.com/teams/urllib3>`_

Your contribution will go towards adding new features to urllib3 and making
sure all functionality continues to meet our high quality standards.


Project Grant
-------------

A grant for contiguous full-time development has the biggest impact for
progress. Periods of 3 to 10 days allow a contributor to tackle substantial
complex issues which are otherwise left to linger until somebody can't afford
to not fix them.

Contact `@shazow <https://github.com/shazow>`_ to arrange a grant for a core
contributor.

Huge thanks to all the companies and individuals who financially contributed to
the development of urllib3. Please send a PR if you've donated and would like
to be listed.

* `Stripe <https://stripe.com/>`_ (June 23, 2014)

.. * [Company] ([date])

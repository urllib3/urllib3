#!/usr/bin/env python

from distutils.core import setup

import os
import re
import sys

try:
    import setuptools
except ImportError:
    pass # No 'develop' command, oh well.

base_path = os.path.dirname(__file__)

# Get the version (borrowed from SQLAlchemy)
fp = open(os.path.join(base_path, 'urllib3', '__init__.py'))
VERSION = re.compile(r".*__version__ = '(.*?)'",
                     re.S).match(fp.read()).group(1)
fp.close()


version = VERSION

requirements = []
tests_requirements = requirements + open('test-requirements.txt').readlines()

extras_require = dict(
    ssl=[],
    modern_ssl=[],
)

try:
    import ssl
except ImportError:
    extras_require.update(
        ssl=['pyOpenSSL'],
        modern_ssl=['pyOpenSSL'],
    )
else:
    if sys.version_info[0] < (3,4):
        extras_require.update(
            modern_ssl=['pyOpenSSL'],
        )

setup(name='urllib3',
      version=version,
      description="HTTP library with thread-safe connection pooling, file post, and more.",
      long_description=open('README.rst').read() + '\n\n' + open('CHANGES.rst').read(),
      classifiers=[
          'Environment :: Web Environment',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: MIT License',
          'Operating System :: OS Independent',
          'Programming Language :: Python',
          'Programming Language :: Python :: 2',
          'Programming Language :: Python :: 3',
          'Topic :: Internet :: WWW/HTTP',
          'Topic :: Software Development :: Libraries',
      ],
      keywords='urllib httplib threadsafe filepost http https ssl pooling',
      author='Andrey Petrov',
      author_email='andrey.petrov@shazow.net',
      url='http://urllib3.readthedocs.org/',
      license='MIT',
      packages=['urllib3', 'urllib3.packages', 'urllib3.contrib'],
      requires=requirements,
      tests_require=tests_requirements,
      test_suite='test',
      extras_require=extras_require,
      )

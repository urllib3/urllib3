#!/usr/bin/env python

from setuptools import setup

import os
import re
import codecs

base_path = os.path.dirname(__file__)

# Get the version (borrowed from SQLAlchemy)
with open(os.path.join(base_path, 'urllib3', '__init__.py')) as fp:
    VERSION = re.compile(r".*__version__ = '(.*?)'",
                         re.S).match(fp.read()).group(1)

with codecs.open('README.rst', encoding='utf-8') as fp:
    readme = fp.read()
with codecs.open('CHANGES.rst', encoding='utf-8') as fp:
    changes = fp.read()
version = VERSION

setup(name='urllib3',
      version=version,
      description="HTTP library with thread-safe connection pooling, file post, and more.",
      long_description=u'\n\n'.join([readme, changes]),
      classifiers=[
          'Environment :: Web Environment',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: MIT License',
          'Operating System :: OS Independent',
          'Programming Language :: Python',
          'Programming Language :: Python :: 2',
          'Programming Language :: Python :: 2.6',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.3',
          'Programming Language :: Python :: 3.4',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: Implementation :: CPython',
          'Programming Language :: Python :: Implementation :: PyPy',
          'Topic :: Internet :: WWW/HTTP',
          'Topic :: Software Development :: Libraries',
      ],
      keywords='urllib httplib threadsafe filepost http https ssl pooling',
      author='Andrey Petrov',
      author_email='andrey.petrov@shazow.net',
      url='https://urllib3.readthedocs.io/',
      license='MIT',
      packages=['urllib3',
                'urllib3.packages', 'urllib3.packages.ssl_match_hostname',
                'urllib3.packages.backports', 'urllib3.contrib',
                'urllib3.contrib._securetransport', 'urllib3.util',
                ],
      requires=[],
      tests_require=[
          # These are a less-specific subset of dev-requirements.txt, for the
          # convenience of distro package maintainers.
          'pytest',
          'nose',
          'mock',
          'tornado',
      ],
      test_suite='test',
      extras_require={
          'secure': [
              'pyOpenSSL>=0.14',
              'cryptography>=1.3.4',
              'idna>=2.0.0',
              'certifi',
              "ipaddress",
          ],
          'socks': [
              'PySocks>=1.5.6,<2.0,!=1.5.7',
          ]
      },
      )

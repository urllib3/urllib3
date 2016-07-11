#!/usr/bin/env python

from setuptools import setup

import os
import re
import codecs

base_path = os.path.dirname(__file__)

# Get the version (borrowed from SQLAlchemy)
fp = open(os.path.join(base_path, 'urllib3', '__init__.py'))
VERSION = re.compile(r".*__version__ = '(.*?)'",
                     re.S).match(fp.read()).group(1)
fp.close()

readme = codecs.open('README.rst', encoding='utf-8').read()
changes = codecs.open('CHANGES.rst', encoding='utf-8').read()
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
          'Programming Language :: Python :: 3',
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
                'urllib3.util',
                ],
      requires=[],
      tests_require=[
          # These are a less-specific subset of dev-requirements.txt, for the
          # convenience of distro package maintainers.
          'nose',
          'mock',
          'tornado',
      ],
      test_suite='test',
      extras_require={
          'secure': [
              'pyOpenSSL>=0.13',
              'ndg-httpsclient',
              'pyasn1',
              'certifi',
          ],
          'socks': [
              'PySocks>=1.5.6,<2.0',
          ]
      },
      )

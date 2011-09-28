#!/usr/bin/env python

from distutils.core import setup
import sys


try:
        import setuptools
except ImportError, _:
        pass # No 'develop' command, oh well.


version = '0.5'
long_description = open('README.txt').read()

requirements = []
tests_requirements = requirements + [
    'nose',
    'eventlet'
]

setup(name='urllib3',
      version=version,
      description="HTTP library with thread-safe connection pooling and file post support",
      long_description=long_description,
      classifiers=[
          'Environment :: Web Environment',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: MIT License',
          'Operating System :: OS Independent',
          'Programming Language :: Python',
          'Topic :: Internet :: WWW/HTTP',
          'Topic :: Software Development :: Libraries',
      ],
      keywords='urllib httplib threadsafe filepost http',
      author='Andrey Petrov',
      author_email='andrey.petrov@shazow.net',
      url='http://code.google.com/p/urllib3/',
      download_url='http://urllib3.googlecode.com/files/urllib3-0.5.tar.gz',
      license='MIT',
      packages=['urllib3'],
      requires=requirements,
      tests_require=tests_requirements,
      )

#!/usr/bin/env python

from distutils.core import setup
import os
import re


try:
    import setuptools
except ImportError, _:
    pass # No 'develop' command, oh well.


# Get the version (borrowed from SQLAlchemy)
fp = open(os.path.join(os.path.dirname(__file__), 'urllib3', '__init__.py'))
VERSION = re.compile(r".*__version__ = '(.*?)'",
                     re.S).match(fp.read()).group(1)
fp.close()


version = VERSION
long_description = open('README.rst').read()
long_description += '\n\n' + open('CHANGES.rst').read()

requirements = []
tests_requirements = requirements + [
    'nose',
    'eventlet'
]

setup(name='urllib3',
      version=version,
      description="HTTP library with thread-safe connection pooling, file post, and more.",
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
      keywords='urllib httplib threadsafe filepost http https ssl pooling',
      author='Andrey Petrov',
      author_email='andrey.petrov@shazow.net',
      url='https://github.com/shazow/urllib3',
      license='MIT',
      packages=['urllib3'],
      requires=requirements,
      tests_require=tests_requirements,
      )

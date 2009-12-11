from setuptools import setup, find_packages
import sys, os

version = '0.3'

long_description = open('README.txt').read()

setup(name='urllib3',
      version=version,
      description="HTTP library with thread-safe connection pooling and file post support",
      long_description=long_description,
      classifiers=[], # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
      keywords='urllib httplib threadsafe filepost http',
      author='Andrey Petrov',
      author_email='andrey.petrov@shazow.net',
      url='http://code.google.com/p/urllib3/',
      license='MIT',
      packages=find_packages(exclude=['ez_setup', 'tests']),
      include_package_data=True,
      zip_safe=False,
      install_requires=[
          # -*- Extra requirements: -*-
      ],
      entry_points="""
      # -*- Entry points: -*-
      """,
      )

from setuptools import setup, find_packages

version = '0.4.0'

long_description = open('README.txt').read()

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
      download_url='http://urllib3.googlecode.com/files/urllib3-0.4.0.tar.gz',
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

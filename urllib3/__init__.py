"""
urllib3 - Thread-safe connection pooling and re-using.
"""

__author__ = "Andrey Petrov (andrey.petrov@shazow.net)"
__license__ = "MIT"
__version__ = "$Rev$"

from connectionpool import HTTPConnectionPool, HTTPSConnectionPool, get_host, connection_from_url
from filepost import encode_multipart_formdata

# Possible exceptions
from connectionpool import HTTPError, MaxRetryError, TimeoutError

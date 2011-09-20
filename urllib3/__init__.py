"""
urllib3 - Thread-safe connection pooling and re-using.
"""

from .connectionpool import (
    HTTPConnectionPool,
    HTTPSConnectionPool,
    connection_from_url,
    get_host,
    make_headers)


from .exceptions import (
    HTTPError,
    MaxRetryError,
    SSLError,
    TimeoutError)


from .response import HTTPResponse
from .filepost import encode_multipart_formdata


__author__ = "Andrey Petrov (andrey.petrov@shazow.net)"
__license__ = "MIT"
__version__ = "$Rev$"

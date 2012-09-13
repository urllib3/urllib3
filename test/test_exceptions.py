import unittest
import pickle

from urllib3.exceptions import HTTPError, MaxRetryError, LocationParseError
from urllib3.connectionpool import HTTPConnectionPool



class TestPickle(unittest.TestCase):

    def test_all_exceptions(self):
        assert pickle.dumps(HTTPError())
        assert pickle.dumps(MaxRetryError(HTTPConnectionPool('localhost'), '/'))
        assert pickle.dumps(LocationParseError('fake location'))

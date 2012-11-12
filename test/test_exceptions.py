import unittest
import pickle

from urllib3.exceptions import HTTPError, MaxRetryError, LocationParseError
from urllib3.connectionpool import HTTPConnectionPool



class TestPickle(unittest.TestCase):

    def test_exceptions(self):
        assert pickle.dumps(HTTPError(None))
        assert pickle.dumps(MaxRetryError(None, None, None))
        assert pickle.dumps(LocationParseError(None))

    def test_exceptions_with_objects(self):
        assert pickle.dumps(HTTPError('foo'))
        assert pickle.dumps(MaxRetryError(HTTPConnectionPool('localhost'), '/', None))
        assert pickle.dumps(LocationParseError('fake location'))

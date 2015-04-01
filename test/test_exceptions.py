import unittest
import pickle

from urllib4.exceptions import (HTTPError, MaxRetryError, LocationParseError,
                                ClosedPoolError, EmptyPoolError,
                                HostChangedError, ReadTimeoutError,
                                ConnectTimeoutError)
from urllib4.connectionpool import HTTPConnectionPool



class TestPickle(unittest.TestCase):

    def verify_pickling(self, item):
        return pickle.loads(pickle.dumps(item))

    def test_exceptions(self):
        assert self.verify_pickling(HTTPError(None))
        assert self.verify_pickling(MaxRetryError(None, None, None))
        assert self.verify_pickling(LocationParseError(None))
        assert self.verify_pickling(ConnectTimeoutError(None))

    def test_exceptions_with_objects(self):
        assert self.verify_pickling(
            HTTPError('foo'))

        assert self.verify_pickling(
            HTTPError('foo', IOError('foo')))

        assert self.verify_pickling(
            MaxRetryError(HTTPConnectionPool('localhost'), '/', None))

        assert self.verify_pickling(
            LocationParseError('fake location'))

        assert self.verify_pickling(
            ClosedPoolError(HTTPConnectionPool('localhost'), None))

        assert self.verify_pickling(
            EmptyPoolError(HTTPConnectionPool('localhost'), None))

        assert self.verify_pickling(
            HostChangedError(HTTPConnectionPool('localhost'), '/', None))

        assert self.verify_pickling(
            ReadTimeoutError(HTTPConnectionPool('localhost'), '/', None))

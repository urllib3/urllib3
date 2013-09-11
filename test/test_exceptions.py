import unittest
import pickle

from urllib3.exceptions import (HTTPError, MaxRetryError, LocationParseError,
                                ClosedPoolError, EmptyPoolError,
                                HostChangedError, ReadTimeoutError,
                                ConnectTimeoutError)
from urllib3.connectionpool import HTTPConnectionPool



class TestPickle(unittest.TestCase):

    def cycle(self, item):
        return pickle.loads(pickle.dumps(item))

    def test_exceptions(self):
        assert self.cycle(HTTPError(None))
        assert self.cycle(MaxRetryError(None, None, None))
        assert self.cycle(LocationParseError(None))
        assert self.cycle(ConnectTimeoutError(None))

    def test_exceptions_with_objects(self):
        assert self.cycle(HTTPError('foo'))
        assert self.cycle(MaxRetryError(HTTPConnectionPool('localhost'),
                                        '/', None))
        assert self.cycle(LocationParseError('fake location'))
        assert self.cycle(ClosedPoolError(HTTPConnectionPool('localhost'),
                                          None))
        assert self.cycle(EmptyPoolError(HTTPConnectionPool('localhost'),
                                         None))
        assert self.cycle(HostChangedError(HTTPConnectionPool('localhost'),
                                           '/', None))
        assert self.cycle(ReadTimeoutError(HTTPConnectionPool('localhost'),
                                              '/', None))

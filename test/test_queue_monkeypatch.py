from __future__ import absolute_import

import unittest

import urllib3
from urllib3.exceptions import EmptyPoolError
import Queue

class BadError(Exception):
    """
    This should not be raised.
    """
    pass

Queue.Empty = BadError


class TestConnectionPool(unittest.TestCase):
    """
    """
    def test_queue_monkeypatching(self):
        http = urllib3.HTTPConnectionPool(host="localhost", block=True)
        first_conn = http._get_conn(timeout=1)
        with self.assertRaises(EmptyPoolError):
            second_conn = http._get_conn(timeout=1)


if __name__ == '__main__':
    unittest.main()

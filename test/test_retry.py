import unittest

from urllib3.response import HTTPResponse
from urllib3.packages.six.moves import xrange
from urllib3.util.retry import Retry
from urllib3.exceptions import (
    ConnectTimeoutError,
    MaxRetryError,
    ReadTimeoutError,
    ResponseError,
)


class RetryTest(unittest.TestCase):

    def test_string(self):
        """ Retry string representation looks the way we expect """
        retry = Retry()
        self.assertEqual(str(retry), 'Retry(total=10, connect=None, read=None, redirect=None)')
        for _ in range(3):
            retry = retry.increment()
        self.assertEqual(str(retry), 'Retry(total=7, connect=None, read=None, redirect=None)')

    def test_retry_both_specified(self):
        """Total can win if it's lower than the connect value"""
        error = ConnectTimeoutError()
        retry = Retry(connect=3, total=2)
        retry = retry.increment(error=error)
        retry = retry.increment(error=error)
        try:
            retry.increment(error=error)
            self.fail("Failed to raise error.")
        except MaxRetryError as e:
            self.assertEqual(e.reason, error)

    def test_retry_higher_total_loses(self):
        """ A lower connect timeout than the total is honored """
        error = ConnectTimeoutError()
        retry = Retry(connect=2, total=3)
        retry = retry.increment(error=error)
        retry = retry.increment(error=error)
        self.assertRaises(MaxRetryError, retry.increment, error=error)

    def test_retry_higher_total_loses_vs_read(self):
        """ A lower read timeout than the total is honored """
        error = ReadTimeoutError(None, "/", "read timed out")
        retry = Retry(read=2, total=3)
        retry = retry.increment(error=error)
        retry = retry.increment(error=error)
        self.assertRaises(MaxRetryError, retry.increment, error=error)

    def test_retry_total_none(self):
        """ if Total is none, connect error should take precedence """
        error = ConnectTimeoutError()
        retry = Retry(connect=2, total=None)
        retry = retry.increment(error=error)
        retry = retry.increment(error=error)
        try:
            retry.increment(error=error)
            self.fail("Failed to raise error.")
        except MaxRetryError as e:
            self.assertEqual(e.reason, error)

        error = ReadTimeoutError(None, "/", "read timed out")
        retry = Retry(connect=2, total=None)
        retry = retry.increment(error=error)
        retry = retry.increment(error=error)
        retry = retry.increment(error=error)
        self.assertFalse(retry.is_exhausted())

    def test_retry_default(self):
        """ If no value is specified, should retry connects 3 times """
        retry = Retry()
        self.assertEqual(retry.total, 10)
        self.assertEqual(retry.connect, None)
        self.assertEqual(retry.read, None)
        self.assertEqual(retry.redirect, None)

        error = ConnectTimeoutError()
        retry = Retry(connect=1)
        retry = retry.increment(error=error)
        self.assertRaises(MaxRetryError, retry.increment, error=error)

        retry = Retry(connect=1)
        retry = retry.increment(error=error)
        self.assertFalse(retry.is_exhausted())

        self.assertTrue(Retry(0).raise_on_redirect)
        self.assertFalse(Retry(False).raise_on_redirect)

    def test_retry_read_zero(self):
        """ No second chances on read timeouts, by default """
        error = ReadTimeoutError(None, "/", "read timed out")
        retry = Retry(read=0)
        try:
            retry.increment(error=error)
            self.fail("Failed to raise error.")
        except MaxRetryError as e:
            self.assertEqual(e.reason, error)

    def test_backoff(self):
        """ Backoff is computed correctly """
        max_backoff = Retry.BACKOFF_MAX

        retry = Retry(total=100, backoff_factor=0.2)
        self.assertEqual(retry.get_backoff_time(), 0) # First request

        retry = retry.increment()
        self.assertEqual(retry.get_backoff_time(), 0) # First retry

        retry = retry.increment()
        self.assertEqual(retry.backoff_factor, 0.2)
        self.assertEqual(retry.total, 98)
        self.assertEqual(retry.get_backoff_time(), 0.4) # Start backoff

        retry = retry.increment()
        self.assertEqual(retry.get_backoff_time(), 0.8)

        retry = retry.increment()
        self.assertEqual(retry.get_backoff_time(), 1.6)

        for i in xrange(10):
            retry = retry.increment()

        self.assertEqual(retry.get_backoff_time(), max_backoff)

    def test_zero_backoff(self):
        retry = Retry()
        self.assertEqual(retry.get_backoff_time(), 0)
        retry = retry.increment()
        retry = retry.increment()
        self.assertEqual(retry.get_backoff_time(), 0)

    def test_sleep(self):
        # sleep a very small amount of time so our code coverage is happy
        retry = Retry(backoff_factor=0.0001)
        retry = retry.increment()
        retry = retry.increment()
        retry.sleep()

    def test_status_forcelist(self):
        retry = Retry(status_forcelist=xrange(500,600))
        self.assertFalse(retry.is_forced_retry('GET', status_code=200))
        self.assertFalse(retry.is_forced_retry('GET', status_code=400))
        self.assertTrue(retry.is_forced_retry('GET', status_code=500))

        retry = Retry(total=1, status_forcelist=[418])
        self.assertFalse(retry.is_forced_retry('GET', status_code=400))
        self.assertTrue(retry.is_forced_retry('GET', status_code=418))

        # String status codes are not matched.
        retry = Retry(total=1, status_forcelist=['418'])
        self.assertFalse(retry.is_forced_retry('GET', status_code=418))

    def test_method_whitelist_with_status_forcelist(self):
        # Falsey method_whitelist means to retry on any method.
        retry = Retry(status_forcelist=[500], method_whitelist=None)
        self.assertTrue(retry.is_forced_retry('GET', status_code=500))
        self.assertTrue(retry.is_forced_retry('POST', status_code=500))

        # Criteria of method_whitelist and status_forcelist are ANDed.
        retry = Retry(status_forcelist=[500], method_whitelist=['POST'])
        self.assertFalse(retry.is_forced_retry('GET', status_code=500))
        self.assertTrue(retry.is_forced_retry('POST', status_code=500))

    def test_exhausted(self):
        self.assertFalse(Retry(0).is_exhausted())
        self.assertTrue(Retry(-1).is_exhausted())
        self.assertEqual(Retry(1).increment().total, 0)

    def test_disabled(self):
        self.assertRaises(MaxRetryError, Retry(-1).increment)
        self.assertRaises(MaxRetryError, Retry(0).increment)

    def test_error_message(self):
        retry = Retry(total=0)
        try:
            retry = retry.increment(error=ReadTimeoutError(None, "/", "read timed out"))
            raise AssertionError("Should have raised a MaxRetryError")
        except MaxRetryError as e:
            assert 'Caused by redirect' not in str(e)
            self.assertEqual(str(e.reason), 'None: read timed out')

        retry = Retry(total=1)
        try:
            retry = retry.increment('POST', '/')
            retry = retry.increment('POST', '/')
            raise AssertionError("Should have raised a MaxRetryError")
        except MaxRetryError as e:
            assert 'Caused by redirect' not in str(e)
            self.assertTrue(isinstance(e.reason, ResponseError),
                            "%s should be a ResponseError" % e.reason)
            self.assertEqual(str(e.reason), ResponseError.GENERIC_ERROR)

        retry = Retry(total=1)
        try:
            response = HTTPResponse(status=500)
            retry = retry.increment('POST', '/', response=response)
            retry = retry.increment('POST', '/', response=response)
            raise AssertionError("Should have raised a MaxRetryError")
        except MaxRetryError as e:
            assert 'Caused by redirect' not in str(e)
            msg = ResponseError.SPECIFIC_ERROR.format(status_code=500)
            self.assertEqual(str(e.reason), msg)

        retry = Retry(connect=1)
        try:
            retry = retry.increment(error=ConnectTimeoutError('conntimeout'))
            retry = retry.increment(error=ConnectTimeoutError('conntimeout'))
            raise AssertionError("Should have raised a MaxRetryError")
        except MaxRetryError as e:
            assert 'Caused by redirect' not in str(e)
            self.assertEqual(str(e.reason), 'conntimeout')

import unittest

from urllib3.exceptions import ConnectTimeoutError, ReadTimeoutError
from urllib3.util.retry import Retry


class RetryTest(unittest.TestCase):

    def test_string(self):
        """ Retry string representation looks the way we expect """
        retry = Retry()
        self.assertEqual(str(retry), 'Retry (count=0)')
        for _ in range(3):
            retry = retry.increment()
        self.assertEqual(str(retry), 'Retry (count=3)')

    def test_retry_both_specified(self):
        """Total can win if it's lower than the connect value"""
        retry = Retry(connect=5, total=3)
        for _ in range(4):
            retry = retry.increment(error=ConnectTimeoutError())
        self.assertTrue(retry.is_exhausted())

    def test_retry_higher_total_loses(self):
        """ A lower connect timeout than the total is honored """
        retry = Retry(connect=3, total=5)
        for _ in range(4):
            retry = retry.increment(error=ConnectTimeoutError())
        self.assertTrue(retry.is_exhausted())

    def test_retry_higher_total_loses_vs_read(self):
        """ A lower read timeout than the total is honored """
        err = ReadTimeoutError(None, "/", "read timed out")
        retry = Retry(read=3, total=5)
        for _ in range(4):
            retry = retry.increment(error=err)
        self.assertTrue(retry.is_exhausted())

    def test_retry_lower_amount_should_not_exhaust_counter(self):
        """ Retries should not be exhausted if there are fewer requests """
        err = ReadTimeoutError(None, "/", "read timed out")
        retry = Retry(read=3, total=5)
        for _ in range(2):
            retry = retry.increment(error=err)
        self.assertFalse(retry.is_exhausted())

    def test_retry_total_none(self):
        """ if Total is none, connect error should take precedence """
        retry = Retry(connect=3, total=None)
        for _ in range(4):
            retry = retry.increment(error=ConnectTimeoutError())
        self.assertTrue(retry.is_exhausted())

    def test_retry_default_exhausted(self):
        """ If no value is specified, should retry connects 3 times """
        err = ConnectTimeoutError()
        retry = Retry()
        for _ in range(4):
            retry = retry.increment(error=err)
        self.assertTrue(retry.is_exhausted())

        retry = Retry()
        for _ in range(3):
            retry = retry.increment(error=err)
        self.assertFalse(retry.is_exhausted())

    def test_retry_read_zero(self):
        """ No second chances on read timeouts, by default """
        err = ReadTimeoutError(None, "/", "read timed out")
        retry = Retry()
        retry = retry.increment(error=err)
        self.assertTrue(retry.is_exhausted())

    def test_backoff(self):
        """ Backoff is computed correctly """
        retry = Retry(backoff_factor=3)
        self.assertEqual(retry._compute_backoff(), 3)
        retry = retry.increment()
        self.assertEqual(retry._compute_backoff(), 3)
        retry = retry.increment()
        self.assertEqual(retry._compute_backoff(), 6)
        retry = retry.increment()
        self.assertEqual(retry._compute_backoff(), 12)

    def test_zero_backoff(self):
        retry = Retry()
        self.assertEqual(retry._compute_backoff(), 0)
        retry = retry.increment()
        retry = retry.increment()
        self.assertEqual(retry._compute_backoff(), 0)

    def test_sleep(self):
        # sleep a very small amount of time so our code coverage is happy
        retry = Retry(backoff_factor=0.0001)
        retry.sleep()

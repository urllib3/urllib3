from __future__ import annotations

import pickle
from unittest import mock

import pytest

from urllib3 import exceptions
from urllib3.response import HTTPResponse
from urllib3.util.retry import Retry


@pytest.mark.parametrize("header", ["61", " 61 ", "Thu, 01 Jan 1970 00:02:01 GMT"])
def test_excessive_delay_preserves_requested_interval(header: str) -> None:
    retry = Retry(retry_after_max=60, raise_on_retry_after_max=True)
    with mock.patch("time.time", return_value=60), mock.patch("time.sleep") as sleep:
        with pytest.raises(exceptions.RetryAfterMaxExceededError) as caught:
            retry.sleep(HTTPResponse(headers={"Retry-After": header}))
    assert caught.value.retry_after == 61
    assert caught.value.max_wait == 60
    sleep.assert_not_called()


@pytest.mark.parametrize("seconds", [0, 59, 60])
def test_limit_is_inclusive(seconds: int) -> None:
    retry = Retry(retry_after_max=60, raise_on_retry_after_max=True)
    assert retry.parse_retry_after(str(seconds)) == seconds


def test_default_still_caps_delay() -> None:
    assert Retry(retry_after_max=60).parse_retry_after("3600") == 60


def test_limit_policy_survives_retry_cloning() -> None:
    retry = Retry(total=2, retry_after_max=60, raise_on_retry_after_max=True)
    assert retry.increment().raise_on_retry_after_max is True
    assert retry.new(raise_on_retry_after_max=False).raise_on_retry_after_max is False


def test_ignored_header_does_not_raise_or_sleep() -> None:
    retry = Retry(
        retry_after_max=60,
        raise_on_retry_after_max=True,
        respect_retry_after_header=False,
    )
    with mock.patch("time.sleep") as sleep:
        retry.sleep(HTTPResponse(headers={"Retry-After": "3600"}))
    sleep.assert_not_called()


def test_exception_pickle_round_trip() -> None:
    error = exceptions.RetryAfterMaxExceededError(3600, 60)
    restored = pickle.loads(pickle.dumps(error))
    assert type(restored) is type(error)
    assert restored.retry_after == 3600
    assert restored.max_wait == 60
    assert str(restored) == str(error)

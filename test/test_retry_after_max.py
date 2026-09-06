from __future__ import annotations

import datetime
from unittest import mock

import pytest

from urllib3.exceptions import RetryAfterMaxExceededError
from urllib3.response import HTTPResponse
from urllib3.util.retry import Retry


def test_default_retry_after_max_still_caps() -> None:
    retry = Retry(retry_after_max=60)
    assert retry.parse_retry_after("3600") == 60


def test_raise_on_retry_after_max() -> None:
    retry = Retry(retry_after_max=60, raise_on_retry_after_max=True)

    with pytest.raises(RetryAfterMaxExceededError) as exc_info:
        retry.parse_retry_after("3600")

    assert exc_info.value.retry_after == 3600
    assert exc_info.value.max_wait == 60


def test_raise_on_retry_after_max_boundary() -> None:
    retry = Retry(retry_after_max=60, raise_on_retry_after_max=True)
    assert retry.parse_retry_after("60") == 60


def test_raise_on_retry_after_max_http_date() -> None:
    retry = Retry(retry_after_max=60, raise_on_retry_after_max=True)
    now = datetime.datetime(2019, 6, 3, 11, tzinfo=datetime.timezone.utc).timestamp()

    with mock.patch("time.time", return_value=now):
        with pytest.raises(RetryAfterMaxExceededError) as exc_info:
            retry.parse_retry_after("Mon, 3 Jun 2019 12:00:00 UTC")

    assert exc_info.value.retry_after == 3600
    assert exc_info.value.max_wait == 60


def test_raise_on_retry_after_max_propagated() -> None:
    retry = Retry(retry_after_max=60, raise_on_retry_after_max=True)
    new_retry = retry.new()

    assert new_retry.retry_after_max == 60
    assert new_retry.raise_on_retry_after_max is True

    with pytest.raises(RetryAfterMaxExceededError):
        new_retry.parse_retry_after("61")


def test_raise_on_retry_after_max_sleep() -> None:
    retry = Retry(retry_after_max=60, raise_on_retry_after_max=True)
    response = HTTPResponse(status=503, headers={"Retry-After": "3600"})

    with mock.patch("time.sleep") as sleep_mock:
        with pytest.raises(RetryAfterMaxExceededError):
            retry.sleep_for_retry(response)

    sleep_mock.assert_not_called()

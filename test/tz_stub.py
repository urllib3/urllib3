import datetime
import os
import time
from contextlib import contextmanager
from typing import Generator, Optional

import pytest
from dateutil import tz


@contextmanager
def stub_timezone_ctx(tzname: Optional[str]) -> Generator[None, None, None]:
    """
    Switch to a locally-known timezone specified by `tzname`.
    On exit, restore the previous timezone.
    If `tzname` is `None`, do nothing.
    """
    if tzname is None:
        yield
        return

    # Only supported on Unix
    if not hasattr(time, "tzset"):
        pytest.skip("Timezone patching is not supported")

    # Make sure the new timezone exists, at least in dateutil
    new_tz = tz.gettz(tzname)
    if new_tz is None:
        raise ValueError(f"Invalid timezone specified: {tzname!r}")

    # Get the current timezone
    local_tz = tz.tzlocal()
    if local_tz is None:
        raise OSError("Cannot determine current timezone")
    old_tzname = datetime.datetime.now(local_tz).tzname()
    assert old_tzname is not None

    os.environ["TZ"] = tzname
    time.tzset()
    yield
    os.environ["TZ"] = old_tzname
    time.tzset()

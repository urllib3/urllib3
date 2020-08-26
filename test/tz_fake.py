import pytz
from contextlib import contextmanager
import time
import os
import pytest
import tzlocal


@contextmanager
def fake_timezone_ctx(tz):
    """
    Switch to a locally-known timezone specified by `tz`.
    On exit, restore the previous timezone.
    If `tz` is `None`, do nothing.
    """
    if tz is None:
        yield
        return

    if not hasattr(time, "tzset"):
        pytest.skip("Timezone patching is not supported")

    # Make sure the new timezone exists, at least in pytz
    if tz not in pytz.all_timezones:
        raise ValueError("Invalid timezone specified: %r" % (tz,))

    # Get the current timezone
    try:
        old_tz = tzlocal.get_localzone().zone
    except ValueError:
        pytest.skip("Cannot determine current timezone")

    os.environ["TZ"] = tz
    time.tzset()
    yield
    os.environ["TZ"] = old_tz
    time.tzset()

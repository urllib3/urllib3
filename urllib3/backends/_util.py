from ..util import selectors

__all__ = ["DEFAULT_SELECTOR", "is_readable"]

# We only ever select on 1 fd at a time, so there's no point in messing around
# with epoll/kqueue. But we do want to use PollSelector on platforms that have
# it (= everything except Windows), since it has no limit on the numerical
# value of the fds it accepts. On Windows, we use SelectSelector, but that's
# OK, because on Windows select also has no limit on the numerical value of
# the handles it accepts.
try:
    selectors.PollSelector().select(timeout=0)
except (OSError, AttributeError):
    DEFAULT_SELECTOR = selectors.SelectSelector
else:
    DEFAULT_SELECTOR = selectors.PollSelector

def is_readable(sock):
    s = DEFAULT_SELECTOR()
    s.register(sock, selectors.EVENT_READ)
    events = s.select(timeout=0)
    return bool(events)

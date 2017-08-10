import errno
import os
import psutil
import select
import signal
import sys
import time
import threading

# Python 2.6 doesn't have addCleanup in unittest
if sys.version_info < (2, 7):
    import unittest2 as unittest
else:
    import unittest

try:  # Python 2.x doesn't define time.perf_counter.
    from time import perf_counter as get_time
except ImportError:
    from time import time as get_time

try:  # Python 2.6 doesn't have the resource module.
    import resource
except ImportError:
    resource = None

try:  # Windows doesn't support socketpair on Python 3.5<
    from socket import socketpair
except ImportError:
    from .socketpair_helper import socketpair

import pytest  # noqa: E402

from urllib3.util import (
    selectors,
    wait
)  # noqa: E402

HAS_ALARM = hasattr(signal, "alarm")

LONG_SELECT = 0.2
SHORT_SELECT = 0.01

# Tolerance values for timer/speed fluctuations.
TOLERANCE = 0.75

# Detect whether we're running on Travis or AppVeyor.  This
# is used to skip some verification points inside of tests to
# not randomly fail our CI due to wild timer/speed differences.
TRAVIS_CI = "TRAVIS" in os.environ
APPVEYOR = "APPVEYOR" in os.environ


skipUnlessHasSelector = pytest.mark.skipif(
    not selectors.HAS_SELECT,
    reason="Platform doesn't have a selector"
)
skipUnlessHasENOSYS = pytest.mark.skipif(
    not hasattr(errno, 'ENOSYS'),
    reason="Platform doesn't have errno.ENOSYS"
)
skipUnlessHasAlarm = pytest.mark.skipif(
    not hasattr(signal, 'alarm'),
    reason="Platform doesn't have signal.alarm()"
)


def patch_select_module(testcase, *keep, **replace):
    """ Helper function that removes all selectors from the select module
    except those listed in *keep and **replace. Those in keep will be kept
    if they exist in the select module and those in replace will be patched
    with the value that is given regardless if they exist or not. Cleanup
    will restore previous state. This helper also resets the selectors module
    so that a call to DefaultSelector() will do feature detection again. """
    selectors._DEFAULT_SELECTOR = None
    for s in ['select', 'poll', 'epoll', 'kqueue']:
        if s in replace:
            if hasattr(select, s):
                old_selector = getattr(select, s)
                testcase.addCleanup(setattr, select, s, old_selector)
            else:
                testcase.addCleanup(delattr, select, s)
            setattr(select, s, replace[s])
        elif s not in keep and hasattr(select, s):
            old_selector = getattr(select, s)
            testcase.addCleanup(setattr, select, s, old_selector)
            delattr(select, s)


class AlarmThread(threading.Thread):
    def __init__(self, timeout):
        super(AlarmThread, self).__init__(group=None)
        self.setDaemon(True)
        self.timeout = timeout
        self.canceled = False

    def cancel(self):
        self.canceled = True

    def run(self):
        time.sleep(self.timeout)
        if not self.canceled:
            os.kill(os.getpid(), signal.SIGALRM)


class AlarmMixin(object):
    alarm_thread = None

    def _begin_alarm_thread(self, timeout):
        self.addCleanup(self._cancel_alarm_thread)
        self.alarm_thread = AlarmThread(timeout)
        self.alarm_thread.start()

    def _cancel_alarm_thread(self):
        if self.alarm_thread is not None:
            self.alarm_thread.cancel()
            self.alarm_thread.join(0.0)
        self.alarm_thread = None

    def set_alarm(self, duration, handler):
        sigalrm_handler = signal.signal(signal.SIGALRM, handler)
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)
        self._begin_alarm_thread(duration)


class TimerContext(object):
    def __init__(self, lower=None, upper=None):
        self.lower = lower
        self.upper = upper
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = get_time()

    def __exit__(self, *args, **kwargs):
        self.end_time = get_time()
        total_time = self.end_time - self.start_time

        # Skip timing on CI due to flakiness.
        if TRAVIS_CI or APPVEYOR:
            return

        if self.lower is not None:
            assert total_time >= self.lower * (1.0 - TOLERANCE)
        if self.upper is not None:
            assert total_time <= self.upper * (1.0 + TOLERANCE)


@skipUnlessHasSelector
class BaseSelectorTestCase(unittest.TestCase, AlarmMixin):
    """ Implements the tests that each type of selector must pass. """

    def make_socketpair(self):
        rd, wr = socketpair()

        # Make non-blocking so we get errors if the
        # sockets are interacted with but not ready.
        rd.settimeout(0.0)
        wr.settimeout(0.0)

        self.addCleanup(rd.close)
        self.addCleanup(wr.close)
        return rd, wr

    def make_selector(self):
        s = selectors.DefaultSelector()
        self.addCleanup(s.close)
        return s

    def standard_setup(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        s.register(wr, selectors.EVENT_WRITE)
        return s, rd, wr

    def test_get_key(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        key = s.register(rd, selectors.EVENT_READ, "data")
        assert key == s.get_key(rd)

        # Unknown fileobj
        with pytest.raises(KeyError):
            s.get_key(999999)

    def test_get_map(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        keys = s.get_map()
        assert not keys
        assert len(keys) == 0
        assert list(keys) == []
        key = s.register(rd, selectors.EVENT_READ, "data")
        assert rd in keys
        assert key == keys[rd]
        assert len(keys) == 1
        assert list(keys) == [rd.fileno()]
        assert list(keys.values()) == [key]

        # Unknown fileobj
        with pytest.raises(KeyError):
            keys[999999]

        # Read-only mapping
        with pytest.raises(TypeError):
            del keys[rd]

        # Doesn't define __setitem__
        with pytest.raises(TypeError):
            keys[rd] = key

    def test_register(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        # Ensure that the file is not yet added.
        assert 0 == len(s.get_map())
        with pytest.raises(KeyError):
            s.get_map()[rd.fileno()]
        with pytest.raises(KeyError):
            s.get_key(rd)
        assert None is s._key_from_fd(rd.fileno())

        data = object()
        key = s.register(rd, selectors.EVENT_READ, data)
        assert isinstance(key, selectors.SelectorKey)
        assert key.fileobj == rd
        assert key.fd == rd.fileno()
        assert key.events == selectors.EVENT_READ
        assert key.data is data
        assert 1 == len(s.get_map())
        for fd in s.get_map():
            assert fd == rd.fileno()

    def test_register_bad_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        with pytest.raises(ValueError):
            s.register(rd, 99999)

    def test_register_negative_fd(self):
        s = self.make_selector()
        with pytest.raises(ValueError):
            s.register(-1, selectors.EVENT_READ)

    def test_register_invalid_fileobj(self):
        s = self.make_selector()
        with pytest.raises(KeyError):
            s.register("string", selectors.EVENT_READ)

    def test_reregister_fd_same_fileobj(self):
        s, rd, wr = self.standard_setup()
        with pytest.raises(KeyError):
            s.register(rd, selectors.EVENT_READ)

    def test_reregister_fd_different_fileobj(self):
        s, rd, wr = self.standard_setup()
        with pytest.raises(KeyError):
            s.register(rd.fileno(), selectors.EVENT_READ)

    def test_context_manager(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        with s as sel:
            rd_key = sel.register(rd, selectors.EVENT_READ)
            wr_key = sel.register(wr, selectors.EVENT_WRITE)
            assert rd_key == sel.get_key(rd)
            assert wr_key == sel.get_key(wr)

        with pytest.raises(RuntimeError):
            s.get_key(rd)
        with pytest.raises(RuntimeError):
            s.get_key(wr)

    def test_unregister(self):
        s, rd, wr = self.standard_setup()
        s.unregister(rd)

        with pytest.raises(KeyError):
            s.unregister(99999)

    def test_reunregister(self):
        s, rd, wr = self.standard_setup()
        s.unregister(rd)

        with pytest.raises(KeyError):
            s.unregister(rd)

    def test_unregister_after_fd_close(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        rdfd = rd.fileno()
        wrfd = wr.fileno()
        s.register(rdfd, selectors.EVENT_READ)
        s.register(wrfd, selectors.EVENT_WRITE)

        rd.close()
        wr.close()

        s.unregister(rdfd)
        s.unregister(wrfd)

        assert 0 == len(s.get_map())

    def test_unregister_after_fileobj_close(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        s.register(wr, selectors.EVENT_WRITE)

        rd.close()
        wr.close()

        s.unregister(rd)
        s.unregister(wr)

        assert 0 == len(s.get_map())

    @pytest.mark.skipif(
        os.name != "posix",
        reason="Platform doesn't support os.dup2"
    )
    def test_unregister_after_reuse_fd(self):
        s, rd, wr = self.standard_setup()
        rdfd = rd.fileno()
        wrfd = wr.fileno()

        rd2, wr2 = self.make_socketpair()
        rd.close()
        wr.close()
        os.dup2(rd2.fileno(), rdfd)
        os.dup2(wr2.fileno(), wrfd)

        s.unregister(rdfd)
        s.unregister(wrfd)

        assert 0 == len(s.get_map())

    def test_modify(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        key = s.register(rd, selectors.EVENT_READ)

        # Modify events
        key2 = s.modify(rd, selectors.EVENT_WRITE)
        assert key.events != key2.events
        assert key2 == s.get_key(rd)

        s.unregister(rd)

        # Modify data
        d1 = object()
        d2 = object()

        key = s.register(rd, selectors.EVENT_READ, d1)
        key2 = s.modify(rd, selectors.EVENT_READ, d2)
        assert key.events == key2.events
        assert key.data is not key2.data
        assert key2 == s.get_key(rd)
        assert key2.data is d2

        # Modify invalid fileobj
        with pytest.raises(KeyError):
            s.modify(999999, selectors.EVENT_READ)

    def test_empty_select(self):
        s = self.make_selector()
        assert [] == s.select(timeout=SHORT_SELECT)

    def test_select_multiple_event_types(self):
        s = self.make_selector()

        rd, wr = self.make_socketpair()
        key = s.register(rd, selectors.EVENT_READ | selectors.EVENT_WRITE)

        assert [(key, selectors.EVENT_WRITE)] == s.select(0.001)

        wr.send(b'x')
        time.sleep(0.01)  # Wait for the write to flush.

        assert [(key, selectors.EVENT_READ | selectors.EVENT_WRITE)] == s.select(0.001)

    def test_select_multiple_selectors(self):
        s1 = self.make_selector()
        s2 = self.make_selector()
        rd, wr = self.make_socketpair()
        key1 = s1.register(rd, selectors.EVENT_READ)
        key2 = s2.register(rd, selectors.EVENT_READ)

        wr.send(b'x')
        time.sleep(0.01)  # Wait for the write to flush.

        assert [(key1, selectors.EVENT_READ)] == s1.select(timeout=0.001)
        assert [(key2, selectors.EVENT_READ)] == s2.select(timeout=0.001)

    def test_select_no_event_types(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        with pytest.raises(ValueError):
            s.register(rd, 0)

    def test_select_many_events(self):
        s = self.make_selector()
        readers = []
        writers = []
        for _ in range(32):
            rd, wr = self.make_socketpair()
            readers.append(rd)
            writers.append(wr)
            s.register(rd, selectors.EVENT_READ)

        assert 0 == len(s.select(0.001))

        # Write a byte to each end.
        for wr in writers:
            wr.send(b'x')

        # Give time to flush the writes.
        time.sleep(0.01)

        ready = s.select(0.001)
        assert 32 == len(ready)
        for key, events in ready:
            assert selectors.EVENT_READ == events
            assert key.fileobj in readers

        # Now read the byte from each endpoint.
        for rd in readers:
            data = rd.recv(1)
            assert b'x' == data

        assert 0 == len(s.select(0.001))

    def test_select_timeout_none(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(wr, selectors.EVENT_WRITE)

        with TimerContext(upper=SHORT_SELECT):
            assert 1 == len(s.select(timeout=None))

    def test_select_timeout_ready(self):
        s, rd, wr = self.standard_setup()

        with TimerContext(upper=SHORT_SELECT):
            assert 1 == len(s.select(timeout=0))
            assert 1 == len(s.select(timeout=-1))
            assert 1 == len(s.select(timeout=0.001))

    def test_select_timeout_not_ready(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        with TimerContext(upper=SHORT_SELECT):
            assert 0 == len(s.select(timeout=0))

        with TimerContext(lower=SHORT_SELECT, upper=SHORT_SELECT):
            assert 0 == len(s.select(timeout=SHORT_SELECT))

    @skipUnlessHasAlarm
    def test_select_timing(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        key = s.register(rd, selectors.EVENT_READ)

        self.set_alarm(SHORT_SELECT, lambda *args: wr.send(b'x'))

        with TimerContext(upper=SHORT_SELECT):
            ready = s.select(LONG_SELECT)
        assert [(key, selectors.EVENT_READ)] == ready

    @skipUnlessHasAlarm
    def test_select_interrupt_no_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        self.set_alarm(SHORT_SELECT, lambda *args: None)

        with TimerContext(lower=LONG_SELECT, upper=LONG_SELECT):
            assert [] == s.select(LONG_SELECT)

    @skipUnlessHasAlarm
    def test_select_interrupt_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        key = s.get_key(rd)

        self.set_alarm(SHORT_SELECT, lambda *args: wr.send(b'x'))

        with TimerContext(lower=SHORT_SELECT, upper=SHORT_SELECT):
            assert [(key, selectors.EVENT_READ)] == s.select(LONG_SELECT)
        assert rd.recv(1) == b'x'

    @skipUnlessHasAlarm
    def test_select_multiple_interrupts_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        key = s.get_key(rd)

        def second_alarm(*args):
            wr.send(b'x')

        def first_alarm(*args):
            self._begin_alarm_thread(SHORT_SELECT)
            signal.signal(signal.SIGALRM, second_alarm)

        self.set_alarm(SHORT_SELECT, first_alarm)

        with TimerContext(lower=SHORT_SELECT * 2, upper=SHORT_SELECT * 2):
            assert [(key, selectors.EVENT_READ)] == s.select(LONG_SELECT)
        assert rd.recv(1) == b'x'

    @skipUnlessHasAlarm
    def test_selector_error(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        def alarm_exception(*args):
            err = OSError()
            err.errno = errno.EACCES
            raise err

        self.set_alarm(SHORT_SELECT, alarm_exception)

        with pytest.raises(selectors.SelectorError) as e:
            s.select(LONG_SELECT)
        assert e.errno == errno.EACCES

    # Test ensures that _syscall_wrapper properly raises the
    # exception that is raised from an interrupt handler.
    @skipUnlessHasAlarm
    def test_select_interrupt_exception(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        class AlarmInterrupt(Exception):
            pass

        def alarm_exception(*args):
            raise AlarmInterrupt()

        self.set_alarm(SHORT_SELECT, alarm_exception)

        with TimerContext(lower=SHORT_SELECT, upper=SHORT_SELECT):
            with pytest.raises(AlarmInterrupt):
                s.select(LONG_SELECT)

    def test_fileno(self):
        s = self.make_selector()
        if hasattr(s, "fileno"):
            fd = s.fileno()
            assert isinstance(fd, int)
            assert fd >= 0
        else:
            pytest.skip("Selector doesn't implement fileno()")

    # According to the psutil docs, open_files() has strange behavior
    # on Windows including giving back incorrect results so to
    # stop random failures from occurring we're skipping on Windows.
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="psutil.Process.open_files() is unstable on Windows."
    )
    def test_leaking_fds(self):
        proc = psutil.Process()
        before_fds = len(proc.open_files())
        s = self.make_selector()
        s.close()
        after_fds = len(proc.open_files())
        assert before_fds == after_fds

    def test_selector_error_exception(self):
        err = selectors.SelectorError(1)
        assert err.__repr__() == "<SelectorError errno=1>"
        assert err.__str__() == "<SelectorError errno=1>"


class BaseWaitForTestCase(unittest.TestCase, AlarmMixin):
    def make_socketpair(self):
        rd, wr = socketpair()

        # Make non-blocking so we get errors if the
        # sockets are interacted with but not ready.
        rd.settimeout(0.0)
        wr.settimeout(0.0)

        self.addCleanup(rd.close)
        self.addCleanup(wr.close)
        return rd, wr

    def test_wait_for_read_single_socket(self):
        rd, wr = self.make_socketpair()
        assert [] == wait.wait_for_read(rd, timeout=SHORT_SELECT)

    def test_wait_for_read_multiple_socket(self):
        rd, rd2 = self.make_socketpair()
        assert [] == wait.wait_for_read([rd, rd2], timeout=SHORT_SELECT)

    def test_wait_for_read_empty(self):
        assert [] == wait.wait_for_read([], timeout=SHORT_SELECT)

    def test_wait_for_write_single_socket(self):
        wr, wr2 = self.make_socketpair()
        assert [wr] == wait.wait_for_write(wr, timeout=SHORT_SELECT)

    def test_wait_for_write_multiple_socket(self):
        wr, wr2 = self.make_socketpair()
        result = wait.wait_for_write([wr, wr2], timeout=SHORT_SELECT)
        assert (result == [wr, wr2]) or (result == [wr2, wr])

    def test_wait_for_write_empty(self):
        assert [] == wait.wait_for_write([], timeout=SHORT_SELECT)

    def test_wait_for_non_list_iterable(self):
        rd, wr = self.make_socketpair()
        iterable = {'rd': rd}.values()
        assert [] == wait.wait_for_read(iterable, timeout=SHORT_SELECT)

    def test_wait_timeout(self):
        rd, wr = self.make_socketpair()
        with TimerContext(lower=SHORT_SELECT, upper=SHORT_SELECT):
            wait.wait_for_read([rd], timeout=SHORT_SELECT)

    def test_wait_io_close_is_called(self):
        selector = selectors.DefaultSelector()
        self.addCleanup(selector.close)

        def fake_constructor():
            return selector

        old_selector = wait.DefaultSelector
        wait.DefaultSelector = fake_constructor
        self.addCleanup(setattr, wait, "DefaultSelector", old_selector)

        rd, wr = self.make_socketpair()
        wait.wait_for_write([rd, wr], 0.001)
        assert selector._map is None

    @skipUnlessHasAlarm
    def test_interrupt_wait_for_read_no_event(self):
        rd, wr = self.make_socketpair()

        self.set_alarm(SHORT_SELECT, lambda *args: None)
        with TimerContext(lower=LONG_SELECT, upper=LONG_SELECT):
            assert [] == wait.wait_for_read(rd, timeout=LONG_SELECT)

    @skipUnlessHasAlarm
    def test_interrupt_wait_for_read_with_event(self):
        rd, wr = self.make_socketpair()

        self.set_alarm(SHORT_SELECT, lambda *args: wr.send(b'x'))
        with TimerContext(lower=SHORT_SELECT, upper=SHORT_SELECT):
            assert [rd] == wait.wait_for_read(rd, timeout=LONG_SELECT)
        assert rd.recv(1) == b'x'


class ScalableSelectorMixin(object):
    """ Mixin to test selectors that allow more fds than FD_SETSIZE """
    @pytest.mark.skipif(
        not resource,
        reason="Could not import the resource module"
    )
    def test_above_fd_setsize(self):
        # A scalable implementation should have no problem with more than
        # FD_SETSIZE file descriptors. Since we don't know the value, we just
        # try to set the soft RLIMIT_NOFILE to the hard RLIMIT_NOFILE ceiling.
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard == resource.RLIM_INFINITY:
            pytest.skip("RLIMIT_NOFILE is infinite")

        try:  # If we're on a *BSD system, the limit tag is different.
            _, bsd_hard = resource.getrlimit(resource.RLIMIT_OFILE)
            if bsd_hard == resource.RLIM_INFINITY:
                pytest.skip("RLIMIT_OFILE is infinite")
            if bsd_hard < hard:
                hard = bsd_hard

        # NOTE: AttributeError resource.RLIMIT_OFILE is not defined on Mac OS.
        except (OSError, resource.error, AttributeError):
            pass

        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
            self.addCleanup(resource.setrlimit, resource.RLIMIT_NOFILE,
                            (soft, hard))
            limit_nofile = min(hard, 2 ** 16)
        except (OSError, ValueError):
            limit_nofile = soft

        # Guard against already allocated FDs
        limit_nofile -= 256
        limit_nofile = max(0, limit_nofile)

        s = self.make_selector()

        for _ in range(limit_nofile // 2):
            rd, wr = self.make_socketpair()
            s.register(rd, selectors.EVENT_READ)
            s.register(wr, selectors.EVENT_WRITE)

        assert limit_nofile // 2 == len(s.select())


@skipUnlessHasSelector
class TestUniqueSelectScenarios(BaseSelectorTestCase):
    def test_select_module_patched_after_import(self):
        # This test is to make sure that after import time
        # calling DefaultSelector() will still give a good
        # return value. This issue is caused by gevent, eventlet.

        # Now remove all selectors except `select.select`.
        patch_select_module(self, 'select')

        # Make sure that the selector returned only uses the selector available.
        selector = self.make_selector()
        assert isinstance(selector, selectors.SelectSelector)

    @skipUnlessHasENOSYS
    def test_select_module_defines_does_not_implement_poll(self):
        # This test is to make sure that if a platform defines
        # a selector as being available but does not actually
        # implement it (kennethreitz/requests#3906) then
        # DefaultSelector() does not fail.

        # Reset the _DEFAULT_SELECTOR value as if using for the first time.
        selectors._DEFAULT_SELECTOR = None

        # Now we're going to patch in a bad `poll`.
        class BadPoll(object):
            def poll(self, timeout):
                raise OSError(errno.ENOSYS)

        # Remove all selectors except `select.select` and replace `select.poll`.
        patch_select_module(self, 'select', poll=BadPoll)

        selector = self.make_selector()
        assert isinstance(selector, selectors.SelectSelector)

    @skipUnlessHasENOSYS
    def test_select_module_defines_does_not_implement_epoll(self):
        # Same as above test except with `select.epoll`.

        # Reset the _DEFAULT_SELECTOR value as if using for the first time.
        selectors._DEFAULT_SELECTOR = None

        # Now we're going to patch in a bad `epoll`.
        def bad_epoll(*args, **kwargs):
            raise OSError(errno.ENOSYS)

        # Remove all selectors except `select.select` and replace `select.epoll`.
        patch_select_module(self, 'select', epoll=bad_epoll)

        selector = self.make_selector()
        assert isinstance(selector, selectors.SelectSelector)


@pytest.mark.skipif(
    not hasattr(selectors, "SelectSelector"),
    reason="Platform doesn't have a SelectSelector"
)
class SelectSelectorTestCase(BaseSelectorTestCase):
    def setUp(self):
        patch_select_module(self, 'select')


@pytest.mark.skipif(
    not hasattr(selectors, "PollSelector"),
    reason="Platform doesn't have a PollSelector"
)
class PollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    def setUp(self):
        patch_select_module(self, 'poll')


@pytest.mark.skipif(
    not hasattr(selectors, "EpollSelector"),
    reason="Platform doesn't have an EpollSelector"
)
class EpollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    def setUp(self):
        patch_select_module(self, 'epoll')


@pytest.mark.skipif(
    not hasattr(selectors, "KqueueSelector"),
    reason="Platform doesn't have a KqueueSelector"
)
class KqueueSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    def setUp(self):
        patch_select_module(self, 'kqueue')


@pytest.mark.skipif(
    not hasattr(selectors, "SelectSelector"),
    reason="Platform doesn't have a SelectSelector"
)
class SelectWaitForTestCase(BaseWaitForTestCase):
    def setUp(self):
        patch_select_module(self, 'select')


@pytest.mark.skipif(
    not hasattr(selectors, "PollSelector"),
    reason="Platform doesn't have a PollSelector"
)
class PollWaitForTestCase(BaseWaitForTestCase):
    def setUp(self):
        patch_select_module(self, 'poll')


@pytest.mark.skipif(
    not hasattr(selectors, "EpollSelector"),
    reason="Platform doesn't have an EpollSelector"
)
class EpollWaitForTestCase(BaseWaitForTestCase):
    def setUp(self):
        patch_select_module(self, 'epoll')


@pytest.mark.skipif(
    not hasattr(selectors, "KqueueSelector"),
    reason="Platform doesn't have a KqueueSelector"
)
class KqueueWaitForTestCase(BaseWaitForTestCase):
    def setUp(self):
        patch_select_module(self, 'kqueue')

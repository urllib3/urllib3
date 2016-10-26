from __future__ import with_statement
import os
import psutil
import signal
import socket
import sys
import time
import threading

try:  # Python 2.6 unittest module doesn't have skip decorators.
    from unittest import skip, skipIf, skipUnless
    import unittest
except ImportError:
    from unittest2 import skip, skipIf, skipUnless
    import unittest2 as unittest

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

from urllib3.util import selectors

LONG_SELECT = 0.2
SHORT_SELECT = 0.01

# Tolerance values for CI timer/speed fluctuations.
LOWER_TOLERANCE = 0.05
UPPER_TOLERANCE = 0.05

# Travis CI detection, sometimes Travis is extremely slow.
if "CI" in os.environ:
    UPPER_TOLERANCE = 0.55


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
    def set_alarm(self, timeout):
        if not hasattr(signal, "SIGALRM"):
            self.skipTest("Platform doesn't have signal.SIGALRM")
        if not hasattr(self, "alarm_thread"):
            self.alarm_thread = None
        if self.alarm_thread is None:
            self.addCleanup(self.cancel_alarm)

        self.alarm_thread = AlarmThread(timeout)
        self.alarm_thread.start()

    def cancel_alarm(self):
        if getattr(self, "alarm_thread", None) is not None:
            self.alarm_thread.cancel()
            self.alarm_thread.join(0.0)
        self.alarm_thread = None

    def make_alarm(self, handler, duration):
        sigalrm_handler = signal.signal(signal.SIGALRM, handler)
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)
        self.set_alarm(duration)


class TimerContext(object):
    def __init__(self, testcase, lower=None, upper=None ):
        self.testcase = testcase
        self.lower = lower
        self.upper = upper
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = get_time()

    def __exit__(self, *args):
        self.end_time = get_time()
        total_time = self.end_time - self.start_time
        if self.lower is not None:
            self.testcase.assertGreaterEqual(total_time, self.lower * (1.0 - LOWER_TOLERANCE))
        if self.upper is not None:
            self.testcase.assertLessEqual(total_time, self.upper * (1.0 + UPPER_TOLERANCE))


class TimerMixin(object):
    def assertTakesTime(self, lower=None, upper=None):
        return TimerContext(self, lower=lower, upper=upper)


@skipUnless(selectors.HAS_SELECT, "Platform doesn't have a selector")
class WaitForIOTest(unittest.TestCase, AlarmMixin, TimerMixin):
    """ Tests for the higher level wait_for_* functions. """
    TOLERANCE = 0.05

    def make_socketpair(self):
        rd, wr = socketpair()

        rd.settimeout(0.0)
        wr.settimeout(0.0)

        self.addCleanup(rd.close)
        self.addCleanup(wr.close)
        return rd, wr

    def test_selector_error(self):
        err = selectors.SelectorError(1)
        self.assertEqual(err.__repr__(), "<SelectorError errno=1>")
        self.assertEqual(err.__str__(), "<SelectorError errno=1>")

    def test_wait_for_read_single_socket(self):
        rd, wr = self.make_socketpair()
        self.assertEqual([], selectors.wait_for_read(rd, timeout=0.001))

    def test_wait_for_read_multiple_socket(self):
        rd, rd2 = self.make_socketpair()
        self.assertEqual([], selectors.wait_for_read([rd, rd2], timeout=0.001))

    def test_wait_for_read_empty(self):
        self.assertEqual([], selectors.wait_for_read([], timeout=0.001))

    def test_wait_for_write_single_socket(self):
        wr, wr2 = self.make_socketpair()
        self.assertEqual([wr], selectors.wait_for_write(wr, timeout=0.001))

    def test_wait_for_write_multiple_socket(self):
        wr, wr2 = self.make_socketpair()
        result = selectors.wait_for_write([wr, wr2], timeout=0.001)
        # assertItemsEqual renamed in Python 3.x
        if hasattr(self, "assertItemsEqual"):
            self.assertItemsEqual([wr, wr2], result)
        else:
            self.assertCountEqual([wr, wr2], result)

    def test_wait_for_write_empty(self):
        self.assertEqual([], selectors.wait_for_write([], timeout=0.001))

    def test_wait_for_non_list_iterable(self):
        rd, wr = self.make_socketpair()
        iterable = {'rd': rd}.values()
        self.assertEqual([], selectors.wait_for_read(iterable, timeout=0.001))

    def test_wait_timeout(self):
        rd, wr = self.make_socketpair()
        with self.assertTakesTime(lower=0.0, upper=0.1):
            selectors.wait_for_read([rd], timeout=0.01)

    @skipUnless(hasattr(signal, "alarm"), "Platform doesn't have signal.alarm()")
    def test_interrupt_wait_for_read_no_event(self):
        rd, wr = self.make_socketpair()

        self.make_alarm(lambda *args: None, SHORT_SELECT)

        with self.assertTakesTime(lower=LONG_SELECT, upper=LONG_SELECT):
            self.assertEqual([], selectors.wait_for_read(rd, timeout=LONG_SELECT))

    @skipUnless(hasattr(signal, "alarm"), "Platform doesn't have signal.alarm()")
    def test_interrupt_wait_for_read_with_event(self):
        rd, wr = self.make_socketpair()

        self.make_alarm(lambda *args: wr.send(b'x'), SHORT_SELECT)

        with self.assertTakesTime(lower=SHORT_SELECT, upper=LONG_SELECT):
            self.assertEqual([rd], selectors.wait_for_read(rd, timeout=LONG_SELECT))
        self.assertEqual(rd.recv(1), b'x')


@skipUnless(selectors.HAS_SELECT, "Platform doesn't have a selector")
class BaseSelectorTestCase(unittest.TestCase, AlarmMixin, TimerMixin):
    """ Implements the tests that each type of selector must pass. """
    SELECTOR = selectors.DefaultSelector
    TOLERANCE = 0.05

    def make_socketpair(self):
        rd, wr = socket.socketpair()

        # Make non-blocking so we get errors if the
        # sockets are interacted with but not ready.
        rd.settimeout(0.0)
        wr.settimeout(0.0)

        self.addCleanup(rd.close)
        self.addCleanup(wr.close)
        return rd, wr

    def make_selector(self):
        s = self.SELECTOR()
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
        self.assertEqual(key, s.get_key(rd))

        # Unknown fileobj
        self.assertRaises(KeyError, s.get_key, 999999)

    def test_get_map(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        keys = s.get_map()
        self.assertFalse(keys)
        self.assertEqual(len(keys), 0)
        self.assertEqual(list(keys), [])
        key = s.register(rd, selectors.EVENT_READ, "data")
        self.assertIn(rd, keys)
        self.assertEqual(key, keys[rd])
        self.assertEqual(len(keys), 1)
        self.assertEqual(list(keys), [rd.fileno()])
        self.assertEqual(list(keys.values()), [key])

        # Unknown fileobj
        self.assertRaises(KeyError, keys.__getitem__, 999999)

        # Read-only mapping
        with self.assertRaises(TypeError):
            del keys[rd]

    def test_register(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        # Ensure that the file is not yet added.
        self.assertEqual(0, len(s.get_map()))
        self.assertRaises(KeyError, lambda: s.get_map()[rd.fileno()])
        self.assertRaises(KeyError, s.get_key, rd)
        self.assertEqual(None, s._key_from_fd(rd.fileno()))

        data = object()
        key = s.register(rd, selectors.EVENT_READ, data)
        self.assertIsInstance(key, selectors.SelectorKey)
        self.assertEqual(key.fileobj, rd)
        self.assertEqual(key.fd, rd.fileno())
        self.assertEqual(key.events, selectors.EVENT_READ)
        self.assertIs(key.data, data)
        self.assertEqual(1, len(s.get_map()))
        for fd in s.get_map():
            self.assertEqual(fd, rd.fileno())

    def test_register_bad_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        self.assertRaises(ValueError, s.register, rd, 99999)

    def test_register_negative_fd(self):
        s = self.make_selector()
        self.assertRaises(ValueError, s.register, -1, selectors.EVENT_READ)

    def test_register_invalid_fileobj(self):
        s = self.make_selector()
        self.assertRaises(ValueError, s.register, "string", selectors.EVENT_READ)

    def test_reregister_fd_same_fileobj(self):
        s, rd, wr = self.standard_setup()
        self.assertRaises(KeyError, s.register, rd, selectors.EVENT_READ)

    def test_reregister_fd_different_fileobj(self):
        s, rd, wr = self.standard_setup()
        self.assertRaises(KeyError, s.register, rd.fileno(), selectors.EVENT_READ)

    def test_context_manager(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        with s as sel:
            rd_key = sel.register(rd, selectors.EVENT_READ)
            wr_key = sel.register(wr, selectors.EVENT_WRITE)
            self.assertEqual(rd_key, sel.get_key(rd))
            self.assertEqual(wr_key, sel.get_key(wr))

        self.assertRaises(RuntimeError, s.get_key, rd)
        self.assertRaises(RuntimeError, s.get_key, wr)

    def test_unregister(self):
        s, rd, wr = self.standard_setup()
        s.unregister(rd)

        self.assertRaises(KeyError, s.unregister, 99999)

    def test_reunregister(self):
        s, rd, wr = self.standard_setup()
        s.unregister(rd)

        self.assertRaises(KeyError, s.unregister, rd)

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

        self.assertEqual(0, len(s.get_map()))

    def test_unregister_after_fileobj_close(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        s.register(wr, selectors.EVENT_WRITE)

        rd.close()
        wr.close()

        s.unregister(rd)
        s.unregister(wr)

        self.assertEqual(0, len(s.get_map()))

    @skipUnless(os.name == "posix", "Platform doesn't support os.dup2")
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

        self.assertEqual(0, len(s.get_map()))

    def test_modify(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        key = s.register(rd, selectors.EVENT_READ)

        # Modify events
        key2 = s.modify(rd, selectors.EVENT_WRITE)
        self.assertNotEqual(key.events, key2.events)
        self.assertEqual(key2, s.get_key(rd))

        s.unregister(rd)

        # Modify data
        d1 = object()
        d2 = object()

        key = s.register(rd, selectors.EVENT_READ, d1)
        key2 = s.modify(rd, selectors.EVENT_READ, d2)
        self.assertEqual(key.events, key2.events)
        self.assertIsNot(key.data, key2.data)
        self.assertEqual(key2, s.get_key(rd))
        self.assertIs(key2.data, d2)

        # Modify invalid fileobj
        self.assertRaises(KeyError, s.modify, 999999, selectors.EVENT_READ)

    def test_empty_select(self):
        s = self.make_selector()
        self.assertEqual([], s.select(timeout=SHORT_SELECT))

    def test_select_multiple_event_types(self):
        s = self.make_selector()

        rd, wr = self.make_socketpair()
        key = s.register(rd, selectors.EVENT_READ | selectors.EVENT_WRITE)

        self.assertEqual([(key, selectors.EVENT_WRITE)], s.select(0.001))

        wr.send(b'x')
        time.sleep(0.01)  # Wait for the write to flush.

        self.assertEqual([(key, selectors.EVENT_READ | selectors.EVENT_WRITE)], s.select(0.001))

    def test_select_multiple_selectors(self):
        s1 = self.make_selector()
        s2 = self.make_selector()
        rd, wr = self.make_socketpair()
        key1 = s1.register(rd, selectors.EVENT_READ)
        key2 = s2.register(rd, selectors.EVENT_READ)

        wr.send(b'x')
        time.sleep(0.01)  # Wait for the write to flush.

        self.assertEqual([(key1, selectors.EVENT_READ)], s1.select(timeout=0.001))
        self.assertEqual([(key2, selectors.EVENT_READ)], s2.select(timeout=0.001))

    def test_select_no_event_types(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        self.assertRaises(ValueError, s.register, rd, 0)

    def test_select_many_events(self):
        s = self.make_selector()
        readers = []
        writers = []
        for i in range(32):
            rd, wr = self.make_socketpair()
            readers.append(rd)
            writers.append(wr)
            s.register(rd, selectors.EVENT_READ)

        self.assertEqual(0, len(s.select(0.001)))

        # Write a byte to each end.
        for wr in writers:
            wr.send(b'x')

        # Give time to flush the writes.
        time.sleep(0.01)

        ready = s.select(0.001)
        self.assertEqual(32, len(ready))
        for key, events in ready:
            self.assertEqual(selectors.EVENT_READ, events)
            self.assertIn(key.fileobj, readers)

        # Now read the byte from each endpoint.
        for rd in readers:
            data = rd.recv(1)
            self.assertEqual(b'x', data)

        self.assertEqual(0, len(s.select(0.001)))

    def test_select_timeout_none(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(wr, selectors.EVENT_WRITE)

        with self.assertTakesTime(upper=SHORT_SELECT):
            self.assertEqual(1, len(s.select(timeout=None)))
            self.assertEqual(1, len(s.select(timeout=None)))
            self.assertEqual(1, len(s.select(timeout=None)))

    def test_select_timeout_ready(self):
        s, rd, wr = self.standard_setup()

        with self.assertTakesTime(upper=SHORT_SELECT):
            self.assertEqual(1, len(s.select(timeout=0)))
            self.assertEqual(1, len(s.select(timeout=-1)))
            self.assertEqual(1, len(s.select(timeout=0.001)))

    def test_select_timeout_not_ready(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        with self.assertTakesTime(upper=SHORT_SELECT):
            self.assertEqual(0, len(s.select(timeout=0)))

        with self.assertTakesTime(lower=SHORT_SELECT):
            self.assertEqual(0, len(s.select(timeout=SHORT_SELECT)))

    @skipUnless(hasattr(signal, "alarm"), "Platform doesn't have signal.alarm()")
    def test_select_timing(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        key = s.register(rd, selectors.EVENT_READ)

        sigalrm_handler = signal.signal(signal.SIGALRM, lambda *args: wr.send(b'x'))
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)

        # Start the timer for the interrupt.
        self.set_alarm(SHORT_SELECT)

        with self.assertTakesTime(upper=LONG_SELECT):
            ready = s.select(LONG_SELECT)
        self.assertEqual([(key, selectors.EVENT_READ)], ready)

    @skipUnless(hasattr(signal, "alarm"), "Platform doesn't have signal.alarm()")
    def test_select_interrupt_no_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        self.make_alarm(lambda *args: None, SHORT_SELECT)

        # The x1.1 is because SelectSelector is really slow on CI.
        with self.assertTakesTime(lower=LONG_SELECT, upper=LONG_SELECT * 1.1):
            self.assertEqual([], s.select(LONG_SELECT))

    @skipUnless(hasattr(signal, "alarm"), "Platform doesn't have signal.alarm()")
    def test_select_interrupt_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        key = s.get_key(rd)

        self.make_alarm(lambda *args: wr.send(b'x'), SHORT_SELECT)

        with self.assertTakesTime(lower=SHORT_SELECT, upper=SHORT_SELECT):
            self.assertEqual([(key, selectors.EVENT_READ)], s.select(LONG_SELECT))
        self.assertEqual(rd.recv(1), b'x')

    @skipUnless(hasattr(signal, "alarm"), "Platform doesn't have signal.alarm()")
    def test_select_multiple_interrupts_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        key = s.get_key(rd)

        def second_alarm(*args):
            wr.send(b'x')

        def first_alarm(*args):
            self.set_alarm(SHORT_SELECT)
            signal.signal(signal.SIGALRM, second_alarm)

        self.make_alarm(first_alarm, SHORT_SELECT)

        with self.assertTakesTime(lower=SHORT_SELECT * 2, upper=SHORT_SELECT * 4):
            self.assertEqual([(key, selectors.EVENT_READ)], s.select(LONG_SELECT))
        self.assertEqual(rd.recv(1), b'x')

    @skipUnless(hasattr(signal, "alarm"), "Platform doesn't have signal.alarm()")
    def test_selector_error(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        def alarm_exception(*args):
            err = OSError()
            err.errno = 100
            raise err

        self.make_alarm(alarm_exception, SHORT_SELECT)

        try:
            s.select(LONG_SELECT)
            self.fail("select() didn't raise SelectorError")
        except selectors.SelectorError as e:
            self.assertEqual(e.errno, 100)
        except Exception as e:
            self.fail("Raised incorrect exception: " + str(e))

    # Test ensures that _syscall_wrapper properly raises the
    # exception that is raised from an interrupt handler.
    @skipUnless(hasattr(signal, "alarm"), "Platform doesn't have signal.alarm()")
    def test_select_interrupt_exception(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        class AlarmInterrupt(Exception):
            pass

        def alarm_exception(*args):
            raise AlarmInterrupt()

        self.make_alarm(alarm_exception, SHORT_SELECT)

        with self.assertTakesTime(lower=SHORT_SELECT, upper=SHORT_SELECT):
            self.assertRaises(AlarmInterrupt, s.select, LONG_SELECT)

    def test_fileno(self):
        s = self.make_selector()
        if hasattr(s, "fileno"):
            fd = s.fileno()
            self.assertTrue(isinstance(fd, int))
            self.assertGreaterEqual(fd, 0)
        else:
            self.skipTest("Selector doesn't implement fileno()")

    # According to the psutil docs, open_files() has strange behavior
    # on Windows including giving back incorrect results so to
    # stop random failures from occurring we're skipping on Windows.
    @skipIf(sys.platform == "win32", "psutil.Process.open_files() is unstable on Windows.")
    def test_leaking_fds(self):
        proc = psutil.Process()
        before_fds = len(proc.open_files())
        s = self.make_selector()
        s.close()
        after_fds = len(proc.open_files())
        self.assertEqual(before_fds, after_fds)


class ScalableSelectorMixin(object):
    """ Mixin to test selectors that allow more fds than FD_SETSIZE """
    @skipUnless(resource, "Could not import the resource module")
    def test_above_fd_setsize(self):
        # A scalable implementation should have no problem with more than
        # FD_SETSIZE file descriptors. Since we don't know the value, we just
        # try to set the soft RLIMIT_NOFILE to the hard RLIMIT_NOFILE ceiling.
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard == resource.RLIM_INFINITY:
            self.skipTest("RLIMIT_NOFILE is infinite")

        try:  # If we're on a *BSD system, the limit tag is different.
            _, bsd_hard = resource.getrlimit(resource.RLIMIT_OFILE)
            if bsd_hard == resource.RLIM_INFINITY:
                self.skipTest("RLIMIT_OFILE is infinite")
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

        for i in range(limit_nofile // 2):
            rd, wr = self.make_socketpair()
            s.register(rd, selectors.EVENT_READ)
            s.register(wr, selectors.EVENT_WRITE)

        self.assertEqual(limit_nofile // 2, len(s.select()))


@skipUnless(hasattr(selectors, "SelectSelector"), "Platform doesn't have a SelectSelector")
class SelectSelectorTestCase(BaseSelectorTestCase):
    SELECTOR = getattr(selectors, "SelectSelector", None)


@skipUnless(hasattr(selectors, "PollSelector"), "Platform doesn't have a PollSelector")
class PollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "PollSelector", None)


@skipUnless(hasattr(selectors, "EpollSelector"), "Platform doesn't have an EpollSelector")
class EpollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "EpollSelector", None)


@skipUnless(hasattr(selectors, "KqueueSelector"), "Platform doesn't have a KqueueSelector")
class KqueueSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "KqueueSelector", None)

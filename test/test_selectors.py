from __future__ import with_statement
import errno
import os
import signal
import socket
import sys

try:  # Python 2.6 unittest module doesn't have skip decorators.
    from unittest import skip, skipIf, skipUnless
    import unittest
except ImportError:
    from unittest2 import skip, skipIf, skipUnless
    import unittest2 as unittest

try:  # Python 2.x doesn't define time.monotonic. time.time will have to do.
    from time import monotonic
except ImportError:
    from time import time as monotonic

try:  # Python 2.6 doesn't have the resource module.
    import resource
except ImportError:
    resource = None

from urllib3.util import selectors


@skipUnless(selectors.HAS_SELECT and hasattr(socket, "socketpair"),
                     "Platform doesn't have a selector and socketpair")
class WaitForIOTest(unittest.TestCase):
    """ Tests for the higher level wait_for_* functions. """
    def make_socketpair(self):
        rd, wr = socket.socketpair()
        self.addCleanup(rd.close)
        self.addCleanup(wr.close)
        return rd, wr

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
        self.assertEqual(2, len(result))
        self.assertTrue(wr in result)
        self.assertTrue(wr2 in result)

    def test_wait_for_write_empty(self):
        self.assertEqual([], selectors.wait_for_write([], timeout=0.001))

    def test_wait_timeout(self):
        rd, wr = self.make_socketpair()
        t = monotonic()
        selectors.wait_for_read([rd], timeout=1.0)
        self.assertTrue(0.8 < monotonic() - t < 1.2)

    @skipUnless(hasattr(signal, "alarm"),
                         "Platform doesn't have signal.alarm()")
    def test_interrupt_wait_for_read_no_event(self):
        rd, wr = self.make_socketpair()

        sigalrm_handler = signal.signal(signal.SIGALRM, lambda *args: None)
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)
        self.addCleanup(signal.alarm, 0)

        # Start the timer for the interrupt.
        signal.alarm(1)

        t = monotonic()
        self.assertEqual([], selectors.wait_for_read(rd, timeout=2.0))
        self.assertLess(monotonic() - t, 2.2)

    @skipUnless(hasattr(signal, "alarm"),
                         "Platform doesn't have signal.alarm()")
    def test_interrupt_wait_for_read_with_event(self):
        rd, wr = self.make_socketpair()

        sigalrm_handler = signal.signal(signal.SIGALRM, lambda *args: wr.send(b'x'))
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)
        self.addCleanup(signal.alarm, 0)

        # Start the timer for the interrupt.
        signal.alarm(1)

        t = monotonic()
        self.assertEqual([rd], selectors.wait_for_read(rd, timeout=2.0))
        self.assertLess(monotonic() - t, 2.2)
        self.assertEqual(rd.recv(1), b'x')


@skipUnless(selectors.HAS_SELECT and hasattr(socket, "socketpair"),
                     "Platform doesn't have a selector and socketpair")
class BaseSelectorTestCase(unittest.TestCase):
    """ Implements the tests that each type of selector must pass. """
    SELECTOR = selectors.DefaultSelector

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
        s.register(rd, selectors.EVENT_READ, "data_rd")
        s.register(wr, selectors.EVENT_WRITE, "data_wr")
        return s, rd, wr

    def test_register(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        # Ensure that the file is not yet added.
        self.assertEqual(0, len(s.get_map()))
        self.assertRaises(KeyError, lambda: s.get_map()[rd.fileno()])
        self.assertRaises(KeyError, s.get_key, rd)
        self.assertEqual(None, s._key_from_fd(rd.fileno()))

        key = s.register(rd, selectors.EVENT_READ, "data")
        self.assertIsInstance(key, selectors.SelectorKey)
        self.assertEqual(key.fileobj, rd)
        self.assertEqual(key.fd, rd.fileno())
        self.assertEqual(key.events, selectors.EVENT_READ)
        self.assertEqual(key.data, "data")
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
            sel.register(rd, selectors.EVENT_READ)
            sel.register(wr, selectors.EVENT_WRITE)

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

    def test_unregister_after_fileobj_close(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        s.register(wr, selectors.EVENT_WRITE)

        rd.close()
        wr.close()

        s.unregister(rd)
        s.unregister(wr)

    @skipUnless(os.name == "posix",
                         "Platform doesn't support os.dup2")
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
        self.assertNotEqual(key.data, key2.data)
        self.assertEqual(key2, s.get_key(rd))
        self.assertEqual(key2.data, d2)

        # Modify invalid fileobj
        self.assertRaises(KeyError, s.modify, 999999, selectors.EVENT_READ)

    def test_empty_select(self):
        s = self.make_selector()
        self.assertEqual([], s.select(timeout=0.001))

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

        self.assertEqual(32, len(s.select(0.001)))

        # Now read the byte from each endpoint.
        for rd in readers:
            data = rd.recv(1)
            self.assertEqual(b'x', data)

        self.assertEqual(0, len(s.select(0.001)))

    def test_select_timeout_none(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(wr, selectors.EVENT_WRITE)

        t = monotonic()
        self.assertEqual(1, len(s.select(timeout=None)))
        self.assertEqual(1, len(s.select(timeout=None)))
        self.assertEqual(1, len(s.select(timeout=None)))
        self.assertLess(monotonic() - t, 0.1)

    def test_select_timeout_ready(self):
        s, rd, wr = self.standard_setup()

        t = monotonic()
        self.assertEqual(1, len(s.select(timeout=0)))
        self.assertEqual(1, len(s.select(timeout=-1)))
        self.assertEqual(1, len(s.select(timeout=0.001)))
        self.assertLess(monotonic() - t, 0.1)

    def test_select_timeout_not_ready(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        t = monotonic()
        self.assertEqual(0, len(s.select(timeout=0)))
        self.assertLess(monotonic() - t, 0.1)

        t = monotonic()
        self.assertEqual(0, len(s.select(timeout=1)))
        self.assertTrue(0.8 <= monotonic() - t <= 1.2)

    @skipUnless(hasattr(signal, "alarm"),
                         "Platform doesn't have signal.alarm()")
    def test_select_interrupt_no_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        sigalrm_handler = signal.signal(signal.SIGALRM, lambda *args: None)
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)
        self.addCleanup(signal.alarm, 0)

        # Start the timer for the interrupt.
        signal.alarm(1)

        t = monotonic()
        self.assertEqual([], s.select(2))
        self.assertLess(monotonic() - t, 2.2)

    @skipUnless(hasattr(signal, "alarm"),
                         "Platform doesn't have signal.alarm()")
    def test_select_interrupt_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        key = s.get_key(rd)

        sigalrm_handler = signal.signal(signal.SIGALRM, lambda *args: wr.send(b'x'))
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)
        self.addCleanup(signal.alarm, 0)

        # Start the timer for the interrupt.
        signal.alarm(1)

        t = monotonic()
        self.assertEqual([(key, selectors.EVENT_READ)], s.select(2))
        self.assertLess(monotonic() - t, 2.2)
        self.assertEqual(rd.recv(1), b'x')

    @skipUnless(hasattr(signal, "alarm"),
                "Platform doesn't have signal.alarm()")
    def test_select_multiple_interrupts_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        key = s.get_key(rd)

        def second_alarm(*args):
            wr.send(b'x')

        def first_alarm(*args):
            signal.alarm(0)
            signal.alarm(1)
            signal.signal(signal.SIGALRM, second_alarm)

        sigalrm_handler = signal.signal(signal.SIGALRM, first_alarm)
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)
        self.addCleanup(signal.alarm, 0)

        # Start the timer for the interrupt.
        signal.alarm(1)

        t = monotonic()
        self.assertEqual([(key, selectors.EVENT_READ)], s.select(3))
        self.assertLess(monotonic() - t, 3.2)
        self.assertEqual(rd.recv(1), b'x')

    def test_fileno(self):
        s = self.make_selector()
        if hasattr(s, "fileno"):
            fd = s.fileno()
            self.assertTrue(isinstance(fd, int))
            self.assertGreaterEqual(fd, 0)


class ScalableSelectorMixin:
    """ Mixin to test selectors that allow more fds than FD_SETSIZE """
    @skipUnless(resource, "Could not import the resource module")
    @skipUnless(sys.platform != "darwin", "Can't run on Mac OS due to RINFINITE hard limit.")
    def test_above_fd_setsize(self):
        # A scalable implementation should have no problem with more than
        # FD_SETSIZE file descriptors. Since we don't know the value, we just
        # try to set the soft RLIMIT_NOFILE to the hard RLIMIT_NOFILE ceiling.
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)

        try:  # If we're on a *BSD system, the limit tag is different.
            _, bsd_hard = resource.getrlimit(resource.RLIMIT_OFILE)
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
            try:
                rd, wr = self.make_socketpair()
            except (OSError, socket.error) as e:
                # Too many FDs should skip. *BSD and Solaris fail on
                # connecting or binding rather than on create.
                if e.errno == errno.EMFILE or e.errno == errno.EADDRNOTAVAIL:
                    self.skipTest("RLIMIT_NOFILE limit reached.")
                    break
                raise
            try:
                s.register(rd, selectors.EVENT_READ)
                s.register(wr, selectors.EVENT_WRITE)
            except (OSError, IOError) as e:
                if e.errno == errno.ENOSPC:
                    # This can be raised by epoll if we go
                    # over fs.epoll.max_user_watches sysctl
                    self.skipTest("MAX_USER_WATCHES reached.")
                    break
                raise

        self.assertEqual(limit_nofile // 2, len(s.select()))


@skipUnless(hasattr(selectors, "SelectSelector"),
                     "Platform doesn't have a SelectSelector")
class SelectSelectorTestCase(BaseSelectorTestCase):
    SELECTOR = getattr(selectors, "SelectSelector", None)


@skipUnless(hasattr(selectors, "PollSelector"),
                     "Platform doesn't have a PollSelector")
class PollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "PollSelector", None)


@skipUnless(hasattr(selectors, "EpollSelector"),
                         "Platform doesn't have an EpollSelector")
class EpollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "EpollSelector", None)


@skipUnless(hasattr(selectors, "KqueueSelector"),
                         "Platform doesn't have a KqueueSelector")
class KqueueSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "KqueueSelector", None)

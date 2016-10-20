from __future__ import with_statement
import os
import signal
import socket
import unittest

try:
    from time import monotonic
except (AttributeError, ImportError):
    from time import time as monotonic

from urllib3.util import selectors
from nose.plugins.skip import SkipTest

try:
    from unittest import skipUnless
except (AttributeError, ImportError):
    def skipUnless(condition, reason):
        """
        Skip a test unless the condition is true.
        """
        if not condition:
            return lambda x: x
        else:
            raise SkipTest(reason)


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

    def test_fileno(self):
        s = self.make_selector()
        if hasattr(s, "fileno"):
            fd = s.fileno()
            self.assertTrue(isinstance(fd, int))
            self.assertGreaterEqual(fd, 0)


@skipUnless(hasattr(selectors, "SelectSelector"),
                     "Platform doesn't have a SelectSelector")
class SelectSelectorTestCase(BaseSelectorTestCase):
    SELECTOR = getattr(selectors, "SelectSelector", None)


@skipUnless(hasattr(selectors, "PollSelector"),
                     "Platform doesn't have a PollSelector")
class PollSelectorTestCase(BaseSelectorTestCase):
    SELECTOR = getattr(selectors, "PollSelector", None)


@skipUnless(hasattr(selectors, "EpollSelector"),
                         "Platform doesn't have an EpollSelector")
class EpollSelectorTestCase(BaseSelectorTestCase):
    SELECTOR = getattr(selectors, "EpollSelector", None)


@skipUnless(hasattr(selectors, "KqueueSelector"),
                         "Platform doesn't have a KqueueSelector")
class KqueueSelectorTestCase(BaseSelectorTestCase):
    SELECTOR = getattr(selectors, "KqueueSelector", None)

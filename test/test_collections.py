import unittest

from urllib3._collections import RecentlyUsedContainer as Container
from urllib3.packages import six
xrange = six.moves.xrange

class TestLRUContainer(unittest.TestCase):
    def test_maxsize(self):
        d = Container(5)

        for i in xrange(5):
            d[i] = str(i)

        self.assertEqual(len(d), 5)

        for i in xrange(5):
            self.assertEqual(d[i], str(i))

        d[i+1] = str(i+1)

        self.assertEqual(len(d), 5)
        self.assertFalse(0 in d)
        self.assertTrue(i+1 in d)

    def test_expire(self):
        d = Container(5)

        for i in xrange(5):
            d[i] = str(i)

        for i in xrange(5):
            d.get(0)

        # Add one more entry
        d[5] = '5'

        # Check state
        self.assertEqual(list(d.keys()), [0, 2, 3, 4, 5])

    def test_pruning(self):
        d = Container(5)

        for i in xrange(5):
            d[i] = str(i)

        # Contend 2 entries for the most-used slot to balloon the heap
        for i in xrange(100):
            d.get(i % 2)

        self.assertTrue(len(d.access_log) <= d.CLEANUP_FACTOR * d._maxsize)

    def test_same_key(self):
        d = Container(5)

        for i in xrange(10):
            d['foo'] = i

        self.assertEqual(list(d.keys()), ['foo'])

        d._prune_invalidated_entries()

        self.assertEqual(len(d.access_log), 1)

    def test_access_ordering(self):
        d = Container(5)

        for i in xrange(10):
            d[i] = True

        self.assertEqual(d._get_ordered_access_keys(), [9,8,7,6,5])

        new_order = [7,8,6,9,5]
        for k in reversed(new_order):
            d[k]

        self.assertEqual(d._get_ordered_access_keys(), new_order)

    def test_delete(self):
        d = Container(5)

        for i in xrange(5):
            d[i] = True

        del d[0]
        self.assertFalse(0 in d)

        d.pop(1)
        self.assertFalse(1 in d)

        d.pop(1, None)

    def test_get(self):
        d = Container(5)

        for i in xrange(5):
            d[i] = True

        r = d.get(4)
        self.assertEqual(r, True)

        r = d.get(5)
        self.assertEqual(r, None)

        r = d.get(5, 42)
        self.assertEqual(r, 42)

        self.assertRaises(KeyError, lambda: d[5])


if __name__ == '__main__':
    unittest.main()

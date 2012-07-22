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
        self.assertEqual(list(d.keys()), [2, 3, 4, 0, 5])

    def test_same_key(self):
        d = Container(5)

        for i in xrange(10):
            d['foo'] = i

        self.assertEqual(list(d.keys()), ['foo'])
        self.assertEqual(len(d), 1)

    def test_access_ordering(self):
        d = Container(5)

        for i in xrange(10):
            d[i] = True

        # Keys should be ordered by access time
        self.assertEqual(list(d.keys()), [5, 6, 7, 8, 9])

        new_order = [7,8,6,9,5]
        for k in new_order:
            d[k]

        self.assertEqual(list(d.keys()), new_order)

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

    def test_disposal(self):
        evicted_items = []

        def dispose_func(arg):
            # Save the evicted datum for inspection
            evicted_items.append(arg)

        d = Container(5, dispose_func=dispose_func)
        for i in xrange(5):
            d[i] = i
        self.assertEqual(list(d.keys()), list(xrange(5)))
        self.assertEqual(evicted_items, []) # Nothing disposed

        d[5] = 5
        self.assertEqual(list(d.keys()), list(xrange(1, 6)))
        self.assertEqual(evicted_items, [0])

        del d[1]
        self.assertEqual(evicted_items, [0, 1])

        d.clear()
        self.assertEqual(evicted_items, [0, 1, 2, 3, 4, 5])

    def test_iter(self):
        d = Container()

        with self.assertRaises(NotImplementedError):
            for i in d:
                self.fail("Iteration shouldn't be implemented.")

if __name__ == '__main__':
    unittest.main()

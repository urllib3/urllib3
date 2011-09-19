import sys
import unittest

sys.path.append('../')

from urllib3.poolmanager import RecentlyUsedContainer as Container


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
            # Push 0 to the top 5 times, create invalid priority entries, create invalid priority entries, create invalid priority entries, create invalid priority entries
            d.get(0)

        # Add one more entry
        d[5] = '5'

        # Check state
        self.assertEqual(d.keys(), [0, 2, 3, 4, 5])


class TestPoolManager(unittest.TestCase):
    pass



if __name__ == '__main__':
    unittest.main()

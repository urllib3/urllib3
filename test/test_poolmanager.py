import sys
import unittest

sys.path.append('../')

from urllib3.poolmanager import RecentlyUsedContainer as Container, PoolManager

from urllib3 import connection_from_url


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

    def test_pruning(self):
        d = Container(5)

        for i in xrange(5):
            d[i] = str(i)

        # Contend 2 entries for the most-used slot to balloon the heap
        for i in xrange(100):
            d.get(i % 2)

        self.assertTrue(len(d.priority_heap) <= d.CLEANUP_FACTOR * d.maxsize)


class TestPoolManager(unittest.TestCase):
    def test_same_url(self):
        # Convince ourselves that normally we don't get the same object
        conn1 = connection_from_url('http://localhost:8081/foo')
        conn2 = connection_from_url('http://localhost:8081/bar')

        self.assertNotEqual(conn1, conn2)

        # Now try again using the PoolManager
        p = PoolManager(1)

        conn1 = p.connection_from_url('http://localhost:8081/foo')
        conn2 = p.connection_from_url('http://localhost:8081/bar')

        self.assertEqual(conn1, conn2)

    def test_many_urls(self):
        urls = [
            "http://localhost:8081/foo",
            "http://www.google.com/mail",
            "http://localhost:8081/bar",
            "https://www.google.com/",
            "https://www.google.com/mail",
            "http://yahoo.com",
            "http://bing.com",
            "http://yahoo.com/",
        ]

        connections = set()

        p = PoolManager(10)

        for url in urls:
            conn = p.connection_from_url(url)
            connections.add(conn)

        self.assertEqual(len(connections), 5)



if __name__ == '__main__':
    unittest.main()

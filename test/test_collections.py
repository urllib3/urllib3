import unittest

from urllib3._collections import (
    HTTPHeaderDict,
    RecentlyUsedContainer as Container
)
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

        self.assertRaises(NotImplementedError, d.__iter__)


class TestHTTPHeaderDict(unittest.TestCase):
    def setUp(self):
        self.d = HTTPHeaderDict(A='foo')
        self.d.add('a', 'bar')

    def test_overwriting_with_setitem_replaces(self):
        d = HTTPHeaderDict()

        d['A'] = 'foo'
        self.assertEqual(d['a'], 'foo')

        d['a'] = 'bar'
        self.assertEqual(d['A'], 'bar')

    def test_copy(self):
        h = self.d.copy()
        self.assertTrue(self.d is not h)
        self.assertEqual(self.d, h)

    def test_add(self):
        d = HTTPHeaderDict()

        d['A'] = 'foo'
        d.add('a', 'bar')

        self.assertEqual(d['a'], 'foo, bar')
        self.assertEqual(d['A'], 'foo, bar')

        d.add('a', 'asdf')
        self.assertEqual(d['a'], 'foo, bar, asdf')
        
    def test_update_add(self):
        self.d.update_add([('c', '100'), ('c', '200'), ('c', '300')], c='400')
        self.assertEqual(self.d['c'], '100, 200, 300, 400')

        self.d.update_add(dict(a='asdf'))
        self.assertEqual(self.d['a'], 'foo, bar, asdf')
        
        class NonMappingHeaderContainer(object):
            def __init__(self, **kwargs):
                self._data = {}
                self._data.update(kwargs)

            def keys(self):
                return self._data.keys()
            
            def __getitem__(self, key):
                return self._data[key]

        header_object = NonMappingHeaderContainer(e='foofoo')
        self.d.update_add(header_object)
        self.assertEqual(self.d['e'], 'foofoo')

    def test_getlist(self):
        self.assertEqual(self.d.getlist('a'), ['foo', 'bar'])
        self.assertEqual(self.d.getlist('A'), ['foo', 'bar'])
        self.assertEqual(self.d.getlist('b'), [])
        self.d.add('b', 'asdf')
        self.assertEqual(self.d.getlist('b'), ['asdf'])

    def test_update(self):
        d = HTTPHeaderDict()
        d.update(self.d)
        d.add('a', 'with, comma')
        self.assertEqual(d.getlist('a'), ['foo', 'bar', 'with, comma'])

    def test_delitem(self):
        del self.d['a']
        self.assertFalse('a' in self.d)
        self.assertFalse('A' in self.d)

    def test_equal(self):
        b = HTTPHeaderDict({'a': 'foo, bar'})
        self.assertEqual(self.d, b)
        c = [('a', 'foo, bar')]
        self.assertNotEqual(self.d, c)
        
        # For some reason, the test above doesn't run into the __eq__ function,
        # lacking test coverage for line 165, so comparing directly here
        self.assertFalse(self.d == 2)

    def test_len(self):
        self.assertEqual(len(self.d), 1)

    def test_repr(self):
        rep = "HTTPHeaderDict({'A': 'foo, bar'})"
        self.assertEqual(repr(self.d), rep)

if __name__ == '__main__':
    unittest.main()

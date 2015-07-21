import unittest

from urllib3._collections import (
    HTTPHeaderDict,
    RecentlyUsedContainer as Container
)
from urllib3.packages import six
xrange = six.moves.xrange

from nose.plugins.skip import SkipTest


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


class NonMappingHeaderContainer(object):
    def __init__(self, **kwargs):
        self._data = {}
        self._data.update(kwargs)

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key):
        return self._data[key]


class TestHTTPHeaderDict(unittest.TestCase):
    def setUp(self):
        self.d = HTTPHeaderDict(Cookie='foo')
        self.d.add('cookie', 'bar')

    def test_create_from_kwargs(self):
        h = HTTPHeaderDict(ab=1, cd=2, ef=3, gh=4)
        self.assertEqual(len(h), 4)
        self.assertTrue('ab' in h)
    
    def test_create_from_dict(self):
        h = HTTPHeaderDict(dict(ab=1, cd=2, ef=3, gh=4))
        self.assertEqual(len(h), 4)
        self.assertTrue('ab' in h)
    
    def test_create_from_iterator(self):
        teststr = 'urllib3ontherocks'
        h = HTTPHeaderDict((c, c*5) for c in teststr)
        self.assertEqual(len(h), len(set(teststr)))
        
    def test_create_from_list(self):
        h = HTTPHeaderDict([('ab', 'A'), ('cd', 'B'), ('cookie', 'C'), ('cookie', 'D'), ('cookie', 'E')])
        self.assertEqual(len(h), 3)
        self.assertTrue('ab' in h)
        clist = h.getlist('cookie')
        self.assertEqual(len(clist), 3)
        self.assertEqual(clist[0], 'C')
        self.assertEqual(clist[-1], 'E')

    def test_create_from_headerdict(self):
        org = HTTPHeaderDict([('ab', 'A'), ('cd', 'B'), ('cookie', 'C'), ('cookie', 'D'), ('cookie', 'E')])
        h = HTTPHeaderDict(org)
        self.assertEqual(len(h), 3)
        self.assertTrue('ab' in h)
        clist = h.getlist('cookie')
        self.assertEqual(len(clist), 3)
        self.assertEqual(clist[0], 'C')
        self.assertEqual(clist[-1], 'E')
        self.assertFalse(h is org)
        self.assertEqual(h, org)

    def test_setitem(self):
        self.d['Cookie'] = 'foo'
        self.assertEqual(self.d['cookie'], 'foo')
        self.d['cookie'] = 'with, comma'
        self.assertEqual(self.d.getlist('cookie'), ['with, comma'])

    def test_update(self):
        self.d.update(dict(Cookie='foo'))
        self.assertEqual(self.d['cookie'], 'foo')
        self.d.update(dict(cookie='with, comma'))
        self.assertEqual(self.d.getlist('cookie'), ['with, comma'])

    def test_delitem(self):
        del self.d['cookie']
        self.assertFalse('cookie' in self.d)
        self.assertFalse('COOKIE' in self.d)

    def test_add_well_known_multiheader(self):
        self.d.add('COOKIE', 'asdf')
        self.assertEqual(self.d.getlist('cookie'), ['foo', 'bar', 'asdf'])
        self.assertEqual(self.d['cookie'], 'foo, bar, asdf')

    def test_add_comma_separated_multiheader(self):
        self.d.add('bar', 'foo')
        self.d.add('BAR', 'bar')
        self.d.add('Bar', 'asdf')
        self.assertEqual(self.d.getlist('bar'), ['foo', 'bar', 'asdf'])
        self.assertEqual(self.d['bar'], 'foo, bar, asdf')

    def test_extend_from_list(self):
        self.d.extend([('set-cookie', '100'), ('set-cookie', '200'), ('set-cookie', '300')])
        self.assertEqual(self.d['set-cookie'], '100, 200, 300')

    def test_extend_from_dict(self):
        self.d.extend(dict(cookie='asdf'), b='100')
        self.assertEqual(self.d['cookie'], 'foo, bar, asdf')
        self.assertEqual(self.d['b'], '100')
        self.d.add('cookie', 'with, comma')
        self.assertEqual(self.d.getlist('cookie'), ['foo', 'bar', 'asdf', 'with, comma'])
        
    def test_extend_from_container(self):
        h = NonMappingHeaderContainer(Cookie='foo', e='foofoo')
        self.d.extend(h)
        self.assertEqual(self.d['cookie'], 'foo, bar, foo')
        self.assertEqual(self.d['e'], 'foofoo')
        self.assertEqual(len(self.d), 2)

    def test_extend_from_headerdict(self):
        h = HTTPHeaderDict(Cookie='foo', e='foofoo')
        self.d.extend(h)
        self.assertEqual(self.d['cookie'], 'foo, bar, foo')
        self.assertEqual(self.d['e'], 'foofoo')
        self.assertEqual(len(self.d), 2)

    def test_copy(self):
        h = self.d.copy()
        self.assertTrue(self.d is not h)
        self.assertEqual(self.d, h)

    def test_getlist(self):
        self.assertEqual(self.d.getlist('cookie'), ['foo', 'bar'])
        self.assertEqual(self.d.getlist('Cookie'), ['foo', 'bar'])
        self.assertEqual(self.d.getlist('b'), [])
        self.d.add('b', 'asdf')
        self.assertEqual(self.d.getlist('b'), ['asdf'])

    def test_getlist_after_copy(self):
        self.assertEqual(self.d.getlist('cookie'), HTTPHeaderDict(self.d).getlist('cookie'))

    def test_equal(self):
        b = HTTPHeaderDict(cookie='foo, bar')
        c = NonMappingHeaderContainer(cookie='foo, bar')
        self.assertEqual(self.d, b)
        self.assertEqual(self.d, c)
        self.assertNotEqual(self.d, 2)

    def test_not_equal(self):
        b = HTTPHeaderDict(cookie='foo, bar')
        c = NonMappingHeaderContainer(cookie='foo, bar')
        self.assertFalse(self.d != b)
        self.assertFalse(self.d != c)
        self.assertNotEqual(self.d, 2)

    def test_pop(self):
        key = 'Cookie'
        a = self.d[key]
        b = self.d.pop(key)
        self.assertEqual(a, b)
        self.assertFalse(key in self.d)
        self.assertRaises(KeyError, self.d.pop, key)
        dummy = object()
        self.assertTrue(dummy is self.d.pop(key, dummy))

    def test_discard(self):
        self.d.discard('cookie')
        self.assertFalse('cookie' in self.d)
        self.d.discard('cookie')

    def test_len(self):
        self.assertEqual(len(self.d), 1)
        self.d.add('cookie', 'bla')
        self.d.add('asdf', 'foo')
        # len determined by unique fieldnames
        self.assertEqual(len(self.d), 2)

    def test_repr(self):
        rep = "HTTPHeaderDict({'Cookie': 'foo, bar'})"
        self.assertEqual(repr(self.d), rep)

    def test_items(self):
        items = self.d.items()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][0], 'Cookie')
        self.assertEqual(items[0][1], 'foo')
        self.assertEqual(items[1][0], 'Cookie')
        self.assertEqual(items[1][1], 'bar')

    def test_dict_conversion(self):
        # Also tested in connectionpool, needs to preserve case
        hdict = {'Content-Length': '0', 'Content-type': 'text/plain', 'Server': 'TornadoServer/1.2.3'}
        h = dict(HTTPHeaderDict(hdict).items())
        self.assertEqual(hdict, h)
        self.assertEqual(hdict, dict(HTTPHeaderDict(hdict)))

    def test_string_enforcement(self):
        # This currently throws AttributeError on key.lower(), should probably be something nicer
        self.assertRaises(Exception, self.d.__setitem__, 3, 5)
        self.assertRaises(Exception, self.d.add, 3, 4)
        self.assertRaises(Exception, self.d.__delitem__, 3)
        self.assertRaises(Exception, HTTPHeaderDict, {3: 3})

    def test_from_httplib_py2(self):
        if six.PY3:
            raise SkipTest("python3 has a different internal header implementation")
        msg = """
Server: nginx
Content-Type: text/html; charset=windows-1251
Connection: keep-alive
X-Some-Multiline: asdf
 asdf
 asdf
Set-Cookie: bb_lastvisit=1348253375; expires=Sat, 21-Sep-2013 18:49:35 GMT; path=/
Set-Cookie: bb_lastactivity=0; expires=Sat, 21-Sep-2013 18:49:35 GMT; path=/
www-authenticate: asdf
www-authenticate: bla

"""
        buffer = six.moves.StringIO(msg.lstrip().replace('\n', '\r\n'))
        msg = six.moves.http_client.HTTPMessage(buffer)
        d = HTTPHeaderDict.from_httplib(msg)
        self.assertEqual(d['server'], 'nginx')
        cookies = d.getlist('set-cookie')
        self.assertEqual(len(cookies), 2)
        self.assertTrue(cookies[0].startswith("bb_lastvisit"))
        self.assertTrue(cookies[1].startswith("bb_lastactivity"))
        self.assertEqual(d['x-some-multiline'].split(), ['asdf', 'asdf', 'asdf'])
        self.assertEqual(d['www-authenticate'], 'asdf, bla')
        self.assertEqual(d.getlist('www-authenticate'), ['asdf', 'bla'])

if __name__ == '__main__':
    unittest.main()

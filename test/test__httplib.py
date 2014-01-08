import unittest
from nose.plugins.skip import SkipTest

from urllib3.packages import six

if six.PY3:
    raise SkipTest('_httplib is not used or tested on PY3')

from StringIO import StringIO
from urllib3._httplib import HTTPMessage
from urllib3.collections_ import HTTPHeaderDict

class TestHTTPMessage(unittest.TestCase):
    def setUp(self):
        lines = 'Server: FooServer\r\nKey: ValueA\r\n\r\n'
        self.msg = HTTPMessage(StringIO(lines))

    def test_no_header_in_line(self):
        line = 'There is no header\r\n'
        self.assertFalse(self.msg.isheader(line))

    def test_isheader(self):
        line = 'Server: FooServer\r\n'
        self.assertEqual(self.msg.isheader(line), 'Server')

    def test_islast(self):
        self.assertTrue(self.msg.islast('\r\n'))
        self.assertTrue(self.msg.islast('\n'))
        self.assertFalse(self.msg.islast('foo'))

    def test_add_continue(self):
        key, addval = 'Key', 'ValueB'
        self.msg.addcontinue(key, addval)
        header = self.msg.getheader('key')
        self.assertEqual(header, 'ValueA\n ValueB')

    def test_add_header(self):
        self.msg.addheader('Foo', 'Bar')
        self.assertEqual(self.msg.headers.get('foo'), 'Bar')

    def test_items(self):
        values = [('Key', 'ValueA'), ('Server', 'FooServer')]
        self.assertEqual(self.msg.items(), values)

    def test_simple(self):
        lines = 'Server: FooServer\r\nKey: Value\r\n\r\n'
        msg = HTTPMessage(StringIO(lines))
        headers = HTTPHeaderDict({'Server': 'FooServer', 'Key': 'Value'})
        self.assertEqual(msg.headers, headers)

    def test_with_continue(self):
        lines = 'Server: FooServer\r\nKey: ValueA\r\n\tValueB\r\n\r\n'
        msg = HTTPMessage(StringIO(lines))
        headers = HTTPHeaderDict({'Server': 'FooServer',
                                  'Key': 'ValueA\n ValueB'})
        self.assertEqual(msg.headers, headers)

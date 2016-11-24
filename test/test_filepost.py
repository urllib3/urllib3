import psutil
import io
import sys

if sys.version_info >= (2, 7):
    import unittest
else:
    import unittest2 as unittest

from urllib3.filepost import (
    encode_multipart_formdata,
    iter_fields,
    MultipartEncoderGenerator
)
from urllib3.fields import RequestField
from urllib3.packages.six import b, u


BOUNDARY = '!! test boundary !!'


class TestMultipartEncoderGenerator(unittest.TestCase):
    def test_len(self):
        fieldsets = [
            [('k', 'v'), ('k2', 'v2')],
            [('k', b'v'), (u('k2'), b'v2')],
            [('k', b'v'), (u('k2'), 'v2')],
            [('foo', b'a'), ('foo', b'b')],
        ]

        for fields in fieldsets:
            encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
            encoded = b''.join(encoded)
            self.assertEqual(len(encoded), len(MultipartEncoderGenerator(fields, boundary=BOUNDARY)))

    def test_memory_usage(self):
        MEGABYTE = 1024 * 1024
        data = b'x' * MEGABYTE  # 1 MB of data
        start_memory = psutil.Process().memory_info().rss

        encoded, _ = encode_multipart_formdata([('k', data)], boundary=BOUNDARY)
        end_memory = psutil.Process().memory_info().rss
        self.assertTrue(end_memory <= start_memory + MEGABYTE)


class TestIterfields(unittest.TestCase):
    def test_dict(self):
        for fieldname, value in iter_fields(dict(a='b')):
            self.assertEqual((fieldname, value), ('a', 'b'))

        self.assertEqual(
            list(sorted(iter_fields(dict(a='b', c='d')))),
            [('a', 'b'), ('c', 'd')])

    def test_tuple_list(self):
        for fieldname, value in iter_fields([('a', 'b')]):
            self.assertEqual((fieldname, value), ('a', 'b'))

        self.assertEqual(
            list(iter_fields([('a', 'b'), ('c', 'd')])),
            [('a', 'b'), ('c', 'd')])


class TestMultipartEncoding(unittest.TestCase):

    def test_input_datastructures(self):
        fieldsets = [
            dict(k='v', k2='v2'),
            [('k', 'v'), ('k2', 'v2')],
        ]

        for fields in fieldsets:
            encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
            encoded = b''.join(encoded)
            self.assertEqual(encoded.count(b(BOUNDARY)), 3)

    def test_field_encoding(self):
        fieldsets = [
            [('k', 'v'), ('k2', 'v2')],
            [('k', b'v'), (u('k2'), b'v2')],
            [('k', b'v'), (u('k2'), 'v2')],
        ]

        for fields in fieldsets:
            encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
            encoded = b''.join(encoded)

            self.assertEqual(encoded,
                b'--' + b(BOUNDARY) + b'\r\n'
                b'Content-Disposition: form-data; name="k"\r\n'
                b'\r\n'
                b'v\r\n'
                b'--' + b(BOUNDARY) + b'\r\n'
                b'Content-Disposition: form-data; name="k2"\r\n'
                b'\r\n'
                b'v2\r\n'
                b'--' + b(BOUNDARY) + b'--\r\n'
                , fields)

            self.assertEqual(content_type,
                'multipart/form-data; boundary=' + str(BOUNDARY))

    def test_filename(self):
        fields = [('k', ('somename', b'v'))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
        encoded = b''.join(encoded)

        self.assertEqual(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data; name="k"; filename="somename"\r\n'
            b'Content-Type: application/octet-stream\r\n'
            b'\r\n'
            b'v\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

        self.assertEqual(content_type,
            'multipart/form-data; boundary=' + str(BOUNDARY))


    def test_textplain(self):
        fields = [('k', ('somefile.txt', b'v'))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
        encoded = b''.join(encoded)

        self.assertEqual(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
            b'Content-Type: text/plain\r\n'
            b'\r\n'
            b'v\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

        self.assertEqual(content_type,
            'multipart/form-data; boundary=' + str(BOUNDARY))

    def test_explicit(self):
        fields = [('k', ('somefile.txt', b'v', 'image/jpeg'))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
        encoded = b''.join(encoded)

        self.assertEqual(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
            b'Content-Type: image/jpeg\r\n'
            b'\r\n'
            b'v\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

        self.assertEqual(content_type,
            'multipart/form-data; boundary=' + str(BOUNDARY))

    def test_request_fields(self):
      fields = [RequestField('k', b'v', filename='somefile.txt', headers={'Content-Type': 'image/jpeg'})]

      encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
      encoded = b''.join(encoded)

      self.assertEqual(encoded,
          b'--' + b(BOUNDARY) + b'\r\n'
          b'Content-Type: image/jpeg\r\n'
          b'\r\n'
          b'v\r\n'
          b'--' + b(BOUNDARY) + b'--\r\n'
          )


class _SeekableObject(object):
    def __init__(self, data):
        self.data = io.BytesIO(data)

    def seek(self, *args, **kwargs):
        return self.data.seek(*args, **kwargs)

    def tell(self, *args, **kwargs):
        return self.data.tell(*args, **kwargs)


class _ReadableObject(object):
    def __init__(self, data):
        self.data = io.BytesIO(data)

    def read(self, chunk=None):
        return self.data.read(chunk)


class _IterableObject(object):
    def __init__(self, data):
        self.data = io.BytesIO(data)

    def __iter__(self):
        return iter(self.data)


class _LengthObject(object):
    def __init__(self, data):
        self.length = len(data)

    def __len__(self):
        return self.length


class TestStreamingUploads(unittest.TestCase):
    def test_length_file_like_object(self):
        fields = [('k', ('somefile.txt', io.BytesIO(b'v'), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        self.assertEqual(len(encoded), 146)

    def test_length_readable_object(self):
        fields = [('k', ('somefile.txt', _ReadableObject(b'v'), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        self.assertEqual(len(encoded), 146)

    def test_length_iterable_object(self):
        fields = [('k', ('somefile.txt', _IterableObject(b'v'), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        self.assertEqual(len(encoded), 146)

    def test_length_unknown_object(self):
        fields = [('k', ('somefile.txt', object(), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        self.assertRaises(TypeError, encoded.__len__)

    def test_unknown_object(self):
        unknown_object = object()
        fields = [('k', ('somefile.txt', unknown_object, 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY, chunk_size=1)
        non_chunks = [b'--' + b(BOUNDARY) + b'\r\n',
                      b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
                      b'Content-Type: image/jpeg\r\n\r\n',
                      b'\r\n',
                      b'--' + b(BOUNDARY) + b'--\r\n']

        for chunk in encoded:
            if chunk not in non_chunks:
                self.assertIs(chunk, unknown_object)

    def test_file_like_object(self):
        fields = [('k', ('somefile.txt', io.BytesIO(b'v'), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = [b'--' + b(BOUNDARY) + b'\r\n',
                    b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n',
                    b'v',
                    b'\r\n',
                    b'--' + b(BOUNDARY) + b'--\r\n']

        for i, actual in enumerate(encoded):
            self.assertEqual(expected[i], actual)

    def test_readable_object(self):
        fields = [('k', ('somefile.txt', _ReadableObject(b'v'), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = [b'--' + b(BOUNDARY) + b'\r\n',
                    b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n',
                    b'v',
                    b'\r\n',
                    b'--' + b(BOUNDARY) + b'--\r\n']

        for i, actual in enumerate(encoded):
            self.assertEqual(expected[i], actual)

    def test_iterable_object(self):
        fields = [('k', ('somefile.txt', _IterableObject(b'v'), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = [b'--' + b(BOUNDARY) + b'\r\n',
                    b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n',
                    b'v',
                    b'\r\n',
                    b'--' + b(BOUNDARY) + b'--\r\n']

        for i, actual in enumerate(encoded):
            self.assertEqual(expected[i], actual)

    def test_readable_small_chunk_size(self):
        fields = [('k', ('somefile.txt', _ReadableObject(b'v' * 1024), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY, chunk_size=1)
        non_chunks = [b'--' + b(BOUNDARY) + b'\r\n',
                      b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
                      b'Content-Type: image/jpeg\r\n\r\n',
                      b'\r\n',
                      b'--' + b(BOUNDARY) + b'--\r\n']

        for chunk in encoded:
            if chunk not in non_chunks:
                self.assertEqual(len(chunk), 1)

    def test_seekable_small_chunk_size(self):
        fields = [('k', ('somefile.txt', io.BytesIO(b'v' * 1024), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY, chunk_size=1)
        non_chunks = [b'--' + b(BOUNDARY) + b'\r\n',
                      b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
                      b'Content-Type: image/jpeg\r\n\r\n',
                      b'\r\n',
                      b'--' + b(BOUNDARY) + b'--\r\n']

        for chunk in encoded:
            if chunk not in non_chunks:
                self.assertEqual(len(chunk), 1)

    def test_iterate_over_encoded(self):
        fields = [('k', ('somefile.txt', _IterableObject(b'v'), 'image/jpeg'))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = [b'--' + b(BOUNDARY) + b'\r\n',
                    b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n',
                    b'v',
                    b'\r\n',
                    b'--' + b(BOUNDARY) + b'--\r\n']

        i = 0
        try:
            actual = next(encoded)
            self.assertEqual(expected[i], actual)
            i += 1
        except StopIteration:
            self.assertEqual(i, len(expected) - 1)

    def test_iter_chunking_remaining(self):
        fields = [('k', ('somefile.txt', _ReadableObject(b'v' * 1024), 'image/jpeg'))]

        for chunk_size in range(1, 128):
            encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY, chunk_size=chunk_size)
            non_chunks = [b'--' + b(BOUNDARY) + b'\r\n',
                          b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
                          b'Content-Type: image/jpeg\r\n\r\n',
                          b'\r\n',
                          b'--' + b(BOUNDARY) + b'--\r\n']

            for chunk in encoded:
                if chunk not in non_chunks:
                    self.assertTrue(len(chunk) == chunk_size or len(chunk) == 1024 % chunk_size)

    def test_read_chunking_remaining(self):
        for chunk_size in range(2, 128):
            fields = [('k', ('somefile.txt', io.BytesIO(b'v' * 1024), 'image/jpeg'))]
            encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY, chunk_size=chunk_size)
            to_read = 1169

            while to_read > 0:
                read_size = min(chunk_size - 1, to_read)
                chunk = encoded.read(read_size)
                self.assertEqual(len(chunk), read_size)
                to_read -= len(chunk)

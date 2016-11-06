import binascii
import os

from .fields import RequestField


def choose_boundary():
    """
    Our embarrassingly-simple replacement for mimetools.choose_boundary.
    """
    return binascii.hexlify(os.urandom(16)).decode()


def iter_field_objects(fields):
    """
    Iterate over fields.

    Supports list of (k, v) tuples and dicts, and lists of
    :class:`~urllib3.fields.RequestField`.

    """
    if isinstance(fields, dict):
        i = fields.items()
    else:
        i = iter(fields)

    for field in i:
        if isinstance(field, RequestField):
            yield field
        else:
            yield RequestField.from_tuples(*field)


def iter_fields(fields):
    """
    .. deprecated:: 1.6

    Iterate over fields.

    The addition of :class:`~urllib3.fields.RequestField` makes this function
    obsolete. Instead, use :func:`iter_field_objects`, which returns
    :class:`~urllib3.fields.RequestField` objects.

    Supports list of (k, v) tuples and dicts.
    """
    if isinstance(fields, dict):
        return ((k, v) for k, v in fields.items())

    return ((k, v) for k, v in fields)


def encode(string):
    if isinstance(string, str):
        return string.encode()
    else:
        return string


def file_size(fp):
    pos = fp.tell()
    fp.seek(0, 2)
    size = fp.tell()
    fp.seek(pos)
    return size - pos


class IterStreamer:
    """
    File-like streaming iterator.
    """

    def __init__(self, generator):
        self.generator = generator
        self.iterator = iter(generator)
        self.leftover = b""

    def __len__(self):
        return self.generator.__len__()

    def __iter__(self):
        return self.iterator

    def __next__(self):
        return next(self.iterator)

    def read(self, size=None):
        data = self.leftover
        count = len(self.leftover)
        try:
            while count < size:
                chunk = next(self)
                data += chunk
                count += len(chunk)
        except StopIteration:
            pass

        if count > size:
            self.leftover = data[size:]

        return data[:size]


class MultipartEncoderGenerator:
    """
    Generator yielding chunk-by-chunk streaming data from fields, with proper
    headers and boundary separators along the way. This is useful for streaming
    large files as iterators without loading the entire data body into memory.

    ``fields`` is a dictionary where the parameter name is the key and the value
    is either a (filename, data) tuple or just data.

    The data can be a unicode string, an iterator producing strings, or a file-like
    object. File-like objects are read ``chunk_size`` bytes at a time.

    If no ``boundary`` is specified then a random one is used.
    """

    def __init__(self, fields, boundary=None, chunk_size=8192):
        self.fields = [field for field in iter_field_objects(fields)]
        self.chunk_size = chunk_size
        self.boundary = boundary or choose_boundary()

    def get_content_type(self):
        return f"multipart/form-data; boundary={self.boundary}"

    def __len__(self):
        """
        Figure out the expected body size by iterating over the fields as if they
        contained empty files, while accumulating the value file sizes as
        efficiently as we can.
        """
        size = (len(self.fields) + 1) * (len(self.boundary) + 6)
        for field in self.fields:
            size += len(field.render_headers())
            data = field.data
            if hasattr(data, "__len__"):
                size += len(encode(data))
            elif isinstance(data, int):
                size += len(str(data))
            elif hasattr(data, "seek"):
                size += file_size(data)
            elif hasattr(data, "read"):
                size += len(encode(data.read()))  # This is undesired
            elif hasattr(data, "__iter__"):
                size += sum(
                    len(encode(chunk)) for chunk in data
                )  # This is also undesired
            else:
                size += len(encode(data))  # Hope for the best

        return size

    def __iter__(self):
        for field in self.fields:
            data = field.data
            yield encode(f"--{self.boundary}\r\n")
            yield encode(field.render_headers())

            if isinstance(data, bytes):
                yield data

            elif isinstance(data, str):
                yield encode(data)

            elif isinstance(data, int):
                # Handle integers for backwards compatibility
                yield encode(str(data))

            elif hasattr(data, "read"):
                # Stream from a file-like object
                while True:
                    chunk = data.read(self.chunk_size)
                    if not chunk:
                        break
                    yield encode(chunk)

            elif hasattr(data, "__iter__"):
                # Stream from an iterator
                for chunk in data:
                    yield encode(chunk)

            else:
                # Hope for the best
                yield encode(data)

            yield b"\r\n"

        yield encode(f"--{self.boundary}--\r\n")


def encode_multipart_formdata(fields, boundary=None, chunk_size=8192):
    """
    Encode a dictionary of ``fields`` using the multipart/form-data MIME format.
    :param fields:
        Dictionary of fields or list of (key, :class:`~urllib3.fields.RequestField`).
    :param boundary:
        If not specified, then a random boundary will be generated using
        :func:`mimetools.choose_boundary`.
    """
    stream = MultipartEncoderGenerator(fields, boundary=boundary, chunk_size=chunk_size)
    return IterStreamer(stream), stream.get_content_type()

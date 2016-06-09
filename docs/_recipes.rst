Recipes
=======

This page includes a collection of recipes in the urlib3 cookbook.

Decode HTTP Response Data in Concatenated Gzip Format
-----------------------------------------------------

By default, urllib3 checks ``Content-Encoding`` header in HTTP response and decodes the data in ``gzip`` or ``deflate`` transparently. If ``Content-Encoding`` is not either of them, however, you will have to decode data in your application.

This recipe shows how to decode data in the concatenated gzip format where multiple gzipped data chunks are concatenated in HTTP response. 

.. doctest ::

    import zlib
    import urllib3

    CHUNK_SIZE = 1024

    def decode_gzip_raw_content(raw_data_fd):
        obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
        output = []
        d = raw_data_fd.read(CHUNK_SIZE)
        while d:
            output.append(obj.decompress(d))
            while obj.unused_data != b'':
                unused_data = obj.unused_data
                obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
                output.append(obj.decompress(unused_data))
            d = raw_data_fd.read(CHUNK_SIZE)
        return b''.join(output)


    def test_urllib3_concatenated_gzip_in_http_response():
        # example for urllib3
        http = urllib3.PoolManager()
        r = http.request('GET', 'http://example.com/abc.txt',
                         decode_content=False, preload_content=False)
        content = decode_gzip_raw_content(r).decode('utf-8')

``obj.unused_data`` includes the left over data in the previous ``obj.decompress`` method call. A new ``zlib.decompressobj`` is used to start decoding the next gzipped data chunk until no further data is given.

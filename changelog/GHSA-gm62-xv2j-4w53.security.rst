Fixed a security issue where an attacker could compose an HTTP response with
virtually unlimited links in the ``Content-Encoding`` header, potentially
leading to a denial of service (DoS) attack by exhausting system resources
during decoding. The number of allowed chained encodings is now limited to 5.

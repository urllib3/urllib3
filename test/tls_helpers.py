"""
These helpers are used with TLS tests, to factor out certain bits of common
code that are needed for effective TLS testing.
"""
import ssl

__all__ = ["TLS_VERSION", "TLS_VERSION_STRING"]

# Several tests use specific TLS versions to confirm that they work. This can
# be a bit risky, because not all implementations have the same set of TLS
# versions. For this reason, we pick one early on that *is* present on this
# implementation and use it. We also use the *lowest* version that is present
# because some Python implementations define constants they cannot actually
# use.
_options = [
    "PROTOCOL_SSLv2", "PROTOCOL_SSLv3", "PROTOCOL_TLSv1", "PROTOCOL_TLSv1_1",
    "PROTOCOL_TLSv1_2",
]
for option in _options:
    try:
        TLS_VERSION = getattr(ssl, option)
    except AttributeError:
        continue
    else:
        TLS_VERSION_STRING = option
        break
else:
    raise ValueError("Unable to find a version of TLS to use")

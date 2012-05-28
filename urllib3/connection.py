# urllib3/connection.py
# Copyright 2008-2012 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php


# XXX: This needs module to be rewritten and utilized from connectionpool.py


def create_proxy_socket(self):
    if self.proxy_url:
        # Extract the proxy components
        proxy_scheme, proxy_host, proxy_port = get_host(self.proxy_url)

        # Detect the proxy scheme
        if proxy_scheme == 'socks4':
            self.sock = socksipy.socks.create_connection(
                (self.host, self.port),
                self.timeout,
                proxy_type = socksipy.socks.PROXY_TYPE_SOCKS4, 
                proxy_host = proxy_host, 
                proxy_port = proxy_port
            )

        elif proxy_scheme == 'socks5':
            self.sock = socksipy.socks.create_connection(
                (self.host, self.port),
                self.timeout,
                proxy_type = socksipy.socks.PROXY_TYPE_SOCKS5, 
                proxy_host = proxy_host, 
                proxy_port = proxy_port
            )

        elif proxy_scheme == 'http':
            self.sock = socket.create_connection(
                (proxy_host, proxy_port),
                self.timeout
            )

            # Trigger the native proxy support in httplib/urllib2
            self._tunnel_host = self.host
            self._tunnel_port = self.port
            self._tunnel()

        else:
            raise AssertionError("bad proxy scheme: %r" % ( proxy_scheme, ) )

# Wrapped HTTPConnection object
class HTTPConnection(_HTTPConnection):
    _tunnel_host = None

    # Bit hacky, but it works
    create_proxy_socket = create_proxy_socket

    def connect(self):
        if self.proxy_url:
            self.create_proxy_socket()

        else:
            self.sock = socket.create_connection(
                (self.host,self.port),
                self.timeout
            )

## Connection objects (extension of httplib)
class HTTPSConnection(_HTTPSConnection):
    # Bit hacky, but it works
    create_proxy_socket = create_proxy_socket:

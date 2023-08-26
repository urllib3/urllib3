# Service only running on IPv6 localhost
# python -m http.server --bind ::1
# Service only running on IPv4 localhost
# python -m http.server --bind 127.0.0.1

import socket
from time import perf_counter
import urllib3

from unittest.mock import MagicMock, Mock, patch

with patch('socket.getaddrinfo') as getaddrinfo:
    # getaddrinfo.return_value = [
    #     (
    #         socket.AF_INET,
    #         socket.SOCK_STREAM,
    #         socket.IPPROTO_TCP,
    #         "",
    #         ("127.0.0.1", 8000)
    #     ),
    #     (
    #         socket.AF_INET6,
    #         socket.SOCK_STREAM,
    #         socket.IPPROTO_TCP,
    #         "",
    #         ("::1", 8000, 0, 0)
    #     ),
    # ]
    getaddrinfo.return_value = [(None, None, None, None, None)]

    # addr_info = socket.getaddrinfo("mycoolsite.abc", 8000, socket.AF_UNSPEC, socket.SOCK_STREAM)
    
    # sockets = []
    # start_time = perf_counter()
    # for res in addr_info:
    #     print(res)
    #     af, socktype, proto, canonname, sa = res
    #     sock = socket.socket(af, socktype, proto)

    #     sock.setblocking(False)

    #     try:
    #         sock.connect(sa)
    #     except OSError as exc:
    #         if exc.errno != 115:  # EINPROGRESS
    #             raise
        
    #     sockets.append(sock)
    
    # # Use the first connection that returns
    # # Prefer IPv6
    # while perf_counter() - start_time < 0.2:
    #     for sock in sockets:
    #         print(sock.getsockname())
    #         # 111 response code is connection refused, 0 is success
    #         # 111 doesn't neccesarily mean there's an error, connection might
    #         # still be on-going
    #         result = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
    #         print(result)
    #         if result == 0:
    #             exit(0)
    
    # response = urllib3.request("GET", "asdfasdfasd.com")
    # print(response.status)
    # print(response.data.decode("UTF-8"))

    http = urllib3.PoolManager()

    response = http.request('GET', 'http://www.compactcloud.co.uk')

    print(response.status)
    print(response.data[-32:])

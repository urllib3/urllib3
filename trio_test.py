import trio
import urllib3
from urllib3.backends.trio_backend import TrioBackend


async def main():
    http = urllib3.PoolManager(TrioBackend())
    r = await http.request('GET', 'http://httpbin.org/robots.txt', preload_content=False)
    print(r.status)  # prints "200"
    print(await r.read())  # prints "User-agent: *\nDisallow: /deny\n"

trio.run(main)

import urllib3
from urllib3.backends.twisted_backend import TwistedBackend
from twisted.internet import reactor
from twisted.internet.defer import ensureDeferred

async def main():
    http = urllib3.PoolManager(TwistedBackend(reactor))
    r = await http.request('GET', 'http://httpbin.org/robots.txt', preload_content=False)
    print(r.status)  # prints "200"
    print(await r.read())  # prints "User-agent: *\nDisallow: /deny\n"
    reactor.stop()

ensureDeferred(main())
reactor.run()

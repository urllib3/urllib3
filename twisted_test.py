import urllib3
from urllib3.backends.twisted_backend import TwistedBackend
from twisted.internet.task import react
from twisted.internet.defer import ensureDeferred

async def main(reactor):
    http = urllib3.PoolManager(TwistedBackend(reactor))
    r = await http.request('GET', 'http://httpbin.org/robots.txt', preload_content=False)
    print(r.status)  # prints "200"
    print(await r.read())  # prints "User-agent: *\nDisallow: /deny\n"

# Workaround for https://twistedmatrix.com/trac/ticket/9366
react(lambda r: ensureDeferred(main(r)))

import urllib3
from urllib3.backends import TrioBackend, SyncBackend, TwistedBackend

async def main(backend):
    http = urllib3.PoolManager(backend=backend)
    r = await http.request("GET", "http://httpbin.org/robots.txt",
                           preload_content=False)
    print("Status:", r.status)
    print("Data:", await r.read())

print("--- Trio ---")
import trio
trio.run(main, TrioBackend())

print("--- Synchronous ---")
def run_sync_coroutine(afn, *args):
    coro = afn(*args)
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    assert False
run_sync_coroutine(main, SyncBackend())

print("--- Twisted ---")
from twisted.internet.task import react
from twisted.internet.defer import ensureDeferred
def twisted_main(reactor):
    return ensureDeferred(main(TwistedBackend(reactor)))
react(twisted_main)

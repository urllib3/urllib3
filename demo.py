import urllib3
from urllib3.backends import TrioBackend, SyncBackend, TwistedBackend

URL = "http://httpbin.org/uuid"

async def main(backend):
    with urllib3.PoolManager(backend=backend) as http:
        print("URL:", URL)
        r = await http.request("GET", URL, preload_content=False)
        print("Status:", r.status)
        print("Data:", await r.read())

print("--- urllib3 using Trio ---")
import trio
trio.run(main, TrioBackend())

print("\n--- urllib3 using synchronous sockets ---")
def run_sync_coroutine(afn, *args):
    coro = afn(*args)
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    assert False
run_sync_coroutine(main, SyncBackend())

print("\n--- urllib3 using Twisted ---")
from twisted.internet.task import react
from twisted.internet.defer import ensureDeferred
def twisted_main(reactor):
    return ensureDeferred(main(TwistedBackend(reactor)))
react(twisted_main)

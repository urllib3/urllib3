from twisted.internet import reactor
from twisted.protocols import socks
import socket
import time
import urllib3

def aSillyBlockingMethod(x):
    http = urllib3.PoolManager(10)
    while True:
        print http.request("GET", "http://www.google.co.uk")

    reactor.stop()
    return

# run method in thread
reactor.listenTCP(1080, socks.SOCKSv4Factory("/dev/null"))
#reactor.callInThread(aSillyBlockingMethod, "2 seconds have passed")
reactor.run()
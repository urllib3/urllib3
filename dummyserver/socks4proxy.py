#!/usr/bin/env python
from twisted.internet import reactor
from twisted.protocols.socks import SOCKSv4Factory

def run_socks4_proxy(host="127.0.0.1", port=1080):
    reactor.listenTCP(port, SOCKSv4Factory("/dev/null"), interface=host)
    try:
        reactor.run()
    except (KeyboardInterrupt, SystemExit):
        reactor.stop()

if __name__ == "__main__":
    print("Starting SOCKS4 proxy server...")
    run_socks4_proxy()

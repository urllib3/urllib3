from twisted.internet import reactor, protocol
import struct

class remote_protocol(protocol.Protocol):
    def connectionMade(self):
        print 'Connection made'
        self.socks5 = self.factory.socks5
        # -- send success to client
        self.socks5.send_connect_response(0)
        self.socks5.remote = self.transport
        self.socks5.state = 'communicate'
    def dataReceived(self, data):
        self.socks5.transport.write(data)

class remote_factory(protocol.ClientFactory):
    def __init__(self, socks5):
        self.protocol = remote_protocol
        self.socks5 = socks5
    def clientConnectionFailed(self, connector, reason):
        print 'failed:', reason.getErrorMessage()
        self.socks5.send_connect_response(5)
        self.socks5.transport.loseConnection()
    def clientConnectionLost(self, connector, reason):
        print 'con lost:', reason.getErrorMessage()
        self.socks5.transport.loseConnection()

class socks5_protocol(protocol.Protocol):
    def connectionMade(self):
        self.state = 'wait_hello'
    def dataReceived(self, data):
        method = getattr(self, self.state)
        method(data)
    #--------------------------------------------------
    def wait_hello(self, data):
        (ver, nmethods) = struct.unpack('!BB', data[:2])
        print 'Got version = %x, nmethods = %x' % (ver,nmethods)
        if ver!=5:
            # we do SOCKS5 only
            self.transport.loseConnection()
            return
        if nmethods<1:
            # not SOCKS5 protocol?!
            self.transport.loseConnection()
            return
        methods = data[2:2+nmethods]
        for meth in methods:
            print 'method=%x' % ord(meth)
            if ord(meth)==0:
                # no auth, neato, accept
                resp = struct.pack('!BB', 5, 0)
                self.transport.write(resp)
                self.state = 'wait_connect'
                return
            if ord(meth)==255:
                # disconnect
                self.transport.loseConnection()
                return
        #-- we should have processed the request by now
        self.transport.loseConnection()
    #--------------------------------------------------
    def wait_connect(self, data):
        (ver, cmd, rsv, atyp) = struct.unpack('!BBBB', data[:4])
        if ver!=5 or rsv!=0:
            # protocol violation
            self.transport.loseConnection()
            return
        data = data[4:]
        if cmd==1:
            print 'CONNECT'
            host = None
            if atyp==1: # IP V4
                print 'ipv4'
                (b1,b2,b3,b4) = struct.unpack('!BBBB', data[:4])
                host = '%i.%i.%i.%i' % (b1,b2,b3,b4)
                data = data[4:]
            elif atyp==3: # domainname
                print 'domain'
                l = struct.unpack('!B', data[:1])
                host = data[1:1+l]
                data = data[1+l:]
            elif atyp==4: # IP V6
                print 'ipv6'
            else:
                # protocol violation
                self.transport.loseConnection()
                return
            (port) = struct.unpack('!H', data[:2])
            port=port[0]
            data = data[2:]
            print '* connecting %s:%d' % (host,port)
            return self.perform_connect(host, port)
        elif cmd==2:
            print 'BIND'
        elif cmd==3:
            print 'UDP ASSOCIATE'
        #-- we should have processed the request by now
        self.transport.loseConnection()
    #--------------------------------------------------
    def send_connect_response(self, code):
        try:
            myname = self.transport.getHost().host
        except:
            # this might fail as no longer a socket
            # is present
            self.transport.loseConnection()
            return
        ip = [int(i) for i in myname.split('.')]
        resp = struct.pack('!BBBB', 5, code, 0, 1 )
        resp += struct.pack('!BBBB', ip[0], ip[1], ip[2], ip[3])
        resp += struct.pack('!H', self.transport.getHost().port)
        self.transport.write(resp)
        
    def perform_connect(self, host, port):
        factory = remote_factory(self)
        reactor.connectTCP(host, port, factory)
    #--------------------------------------------------
    def communicate(self, data):
        self.remote.write(data)


def run_socks5_proxy(host="127.0.0.1", port=1081):
    factory = protocol.ServerFactory()
    factory.protocol = socks5_protocol
    reactor.listenTCP(port, factory, interface=host)
    try:
        reactor.run()
    except (KeyboardInterrupt, SystemExit):
        reactor.stop()

if __name__ == '__main__':
    run_socks5_proxy()
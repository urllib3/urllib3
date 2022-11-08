# Connection lifecycle

## Current implementation

`HTTPConnection` should be instantiated with `host` and `port` of the
**first origin being connected to** to reach the target origin. This either means
the target origin itself or the proxy origin if one is desired.

If the connection is an `HTTPSConnection`, then `HTTPSConnection.set_cert()` should
be called once with information about how to verify certificates. (What is stopping us
from putting this information in `HTTPSConnection.__init__()`?)

If using CONNECT tunneling with the proxy, call `HTTPConnection.set_tunnel()`
with the tunneled host, port, and headers. This will mark the `HTTPConnection`
as not-reusable.

Set the connection's `timeout` property to the "connect timeout" value.

Connect to the first origin by calling the `HTTPConnection.connect()` method.
If an error occurs here you can check whether the error occurred during the
connection to the proxy if `HTTPConnection._connecting_to_proxy` is true.
If the value is false then the error didn't occur while connecting to a proxy.

(Should we be setting `timeout` to some write timeout at this point? `None`?)

After connecting to the origin, the connection can be checked to see if `is_verified` is set to true. If not the pool emits a warning.
The warning only matters for when verification is disabled, because otherwise an error is raised on unverified TLS handshake.

Then the HTTP request can be sent with `HTTPConnection.request()`. If a `BrokenPipeError` (should we include `SSLEOFError`?)
is raised while sending the request body it can be swallowed as a response
can still be received from the origin even when the request isn't completely
sent.

Set the connections `timeout` property is set to the `read_timeout`. (Currently this appears calculated via some algorithm?)

Then response headers (and other info) are read from the connection via `HTTPConnection.getresponse()` and returned as a `urllib3.HTTPResponse`. The `HTTPResponse` instance carries a reference to the `HTTPConnection` instance. (Within `HTTPConnectionPool` the `HTTPResponse._connection` is set to `response_conn`, is that needed or can `HTTPConnection.getresponse()` handle this?)

If pooling is in use set `_connection` and `_pool` on the `HTTPResponse` instance. If retries are in use set `retries` on the `HTTPResponse` instance.

If any error is received from connecting to the origin, sending the request, or receiving the response, the pool will call `HTTPConnection.close()` and discard the connection.

### HTTP/HTTPS/proxies

- No proxy, HTTP origin -> `HTTPConnection`
- No proxy, HTTPS origin -> `HTTPSConnection`
- HTTP proxy, HTTP origin -> `HTTPConnection` in forwarding mode
- HTTP proxy, HTTPS origin -> `HTTPSConnection` in tunnel mode
- HTTPS proxy, HTTP origin -> `HTTPSConnection` in forwarding mode
- HTTPS proxy, HTTPS origin -> `HTTPSConnection` in tunnel mode
- HTTPS proxy, HTTPS origin, `use_forwarding_for_https=True` -> `HTTPSConnection` in forwarding mode

### Downsides

- Lots of internal property usage by connection pools/response.
  - Checking whether a connection is established
  - Accessing `.sock` property
- Proxies seem super clunky to setup even though we're giving all the information to the connection pool/connection?
- Timeouts are getting set throughout an HTTPConnection's lifecycle by the connection pool.
- The `auto_open` state property seems super suspicious to me, maybe had a different use when our code was originally written? Needs more investigation.

## How could things be better?

### Overall

It's confusing that there is a split between HTTP and HTTPS because we need to do a little dance to figure out which kind we want based on what kind of proxy is in use. Only difference between the two is properties and whether `ssl.wrap_socket` happens on `connect()`. Should connections support both HTTP and HTTPS?

### Lifecycle

Create an HTTPConnection or HTTPSConnection. All configuration options are given via the constructor.
Through this constructor the proxy is configured properly.

If tunneling is being used, call `HTTPConnection.set_tunnel()` with the tunnel target host, port, scheme, and headers.

(Add a property `is_connected` so the pool can check if this connection is new, closed but usable, or connected?
We have something similar in `is_connection_dropped(conn)`?)

Call `HTTPConnection.connect()`, this will establish a connection to the target origin and set `HTTPSConnection.is_verified` and `.proxy_is_verified` if using HTTPS for either of those hops.

Call `HTTPConnection.request()`

Call `HTTPConnection.getresponse()`, only set `_pool` and `retries`. `_connection` should get set automatically?

Once the connection is done being used, call `HTTPConnection.close()`.
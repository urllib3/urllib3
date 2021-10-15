from typing import TYPE_CHECKING, Optional, Union

from .ssl_ import create_urllib3_context, resolve_cert_reqs, resolve_ssl_version
from .url import Url

if TYPE_CHECKING:
    import ssl

    from ..connection import ProxyConfig


def connection_requires_http_tunnel(
    proxy_url: Optional[Url] = None,
    proxy_config: "Optional[ProxyConfig]" = None,
    destination_scheme: Optional[str] = None,
) -> bool:
    """
    Returns True if the connection requires an HTTP CONNECT through the proxy.

    :param URL proxy_url:
        URL of the proxy.
    :param ProxyConfig proxy_config:
        Proxy configuration from poolmanager.py
    :param str destination_scheme:
        The scheme of the destination. (i.e https, http, etc)
    """
    # If we're not using a proxy, no way to use a tunnel.
    if proxy_url is None:
        return False

    # HTTP destinations never require tunneling, we always forward.
    if destination_scheme == "http":
        return False

    # Support for forwarding with HTTPS proxies and HTTPS destinations.
    if (
        proxy_url.scheme == "https"
        and proxy_config
        and proxy_config.use_forwarding_for_https
    ):
        return False

    # Otherwise always use a tunnel.
    return True


def create_proxy_ssl_context(
    ssl_version: Optional[Union[int, str]] = None,
    cert_reqs: Optional[Union[int, str]] = None,
    ca_certs: Optional[str] = None,
    ca_cert_dir: Optional[str] = None,
    ca_cert_data: Union[None, str, bytes] = None,
) -> "ssl.SSLContext":
    """
    Generates a default proxy ssl context if one hasn't been provided by the
    user.
    """
    ssl_context = create_urllib3_context(
        ssl_version=resolve_ssl_version(ssl_version),
        cert_reqs=resolve_cert_reqs(cert_reqs),
    )
    if (
        not ca_certs
        and not ca_cert_dir
        and not ca_cert_data
        and hasattr(ssl_context, "load_default_certs")
    ):
        ssl_context.load_default_certs()

    return ssl_context

from typing import TYPE_CHECKING, Optional

from .url import Url

if TYPE_CHECKING:
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

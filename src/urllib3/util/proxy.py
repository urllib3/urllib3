import os

from .ssl_ import (
    resolve_cert_reqs,
    resolve_ssl_version,
    create_urllib3_context,
)


def connection_requires_http_tunnel(
    proxy_url=None, proxy_config=None, destination_scheme=None
):
    """
    Returns True if the connection requires an HTTP CONNECT through the proxy.

    :param destination_url:
        :URL URL of the destination.
    :param proxy_url:
        :URL URL of the proxy.
    :param proxy_config:
        :class:`PoolManager.ProxyConfig` proxy configuration
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


def generate_proxy_ssl_context(
    ssl_version, cert_reqs, ca_certs=None, ca_cert_dir=None, ca_cert_data=None
):
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

    proxy_cert, proxy_key, proxy_pass = client_certificate_and_key_from_env()

    if proxy_cert:
        ssl_context.load_cert_chain(proxy_cert, keyfile=proxy_key, password=proxy_pass)

    return ssl_context


def client_certificate_and_key_from_env():
    """
    Attempts to retrieve a client certificate and key from the environment
    variables to use with the proxy.
    """
    proxy_cert = os.environ.get("PROXY_SSLCERT")
    proxy_key = os.environ.get("PROXY_SSLKEY")
    proxy_pass = os.environ.get("PROXY_KEYPASSWD")

    return proxy_cert, proxy_key, proxy_pass

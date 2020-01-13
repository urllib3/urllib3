import collections
import contextlib
import threading
import platform
import sys

import pytest
import trustme
from tornado import web, ioloop

from dummyserver.handlers import TestingApp
from dummyserver.server import run_tornado_app
from dummyserver.server import (
    DEFAULT_CA,
    DEFAULT_CA_KEY,
    CLIENT_INTERMEDIATE_PEM,
    CLIENT_NO_INTERMEDIATE_PEM,
    CLIENT_INTERMEDIATE_KEY,
    NO_SAN_CA,
    NO_SAN_CERTS,
)


# The Python 3.8+ default loop on Windows breaks Tornado
@pytest.fixture(scope="session", autouse=True)
def configure_windows_event_loop():
    if sys.version_info >= (3, 8) and platform.system() == "Windows":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def certs_dir(tmp_path_factory):
    tmpdir = tmp_path_factory.mktemp("certs")
    # Start from existing root CA as we don't want to change the server certificate yet
    with open(DEFAULT_CA, "rb") as crt, open(DEFAULT_CA_KEY, "rb") as key:
        root_ca = trustme.CA.from_pem(crt.read(), key.read())

    # client cert chain
    intermediate_ca = root_ca.create_child_ca()
    cert = intermediate_ca.issue_cert(u"example.com")

    cert.private_key_pem.write_to_path(str(tmpdir / CLIENT_INTERMEDIATE_KEY))
    # Write the client cert and the intermediate CA
    client_cert = str(tmpdir / CLIENT_INTERMEDIATE_PEM)
    cert.cert_chain_pems[0].write_to_path(client_cert)
    cert.cert_chain_pems[1].write_to_path(client_cert, append=True)
    # Write only the client cert
    cert.cert_chain_pems[0].write_to_path(str(tmpdir / CLIENT_NO_INTERMEDIATE_PEM))

    yield tmpdir


ServerConfig = collections.namedtuple("ServerConfig", ["host", "port", "ca_certs"])


@contextlib.contextmanager
def run_server_in_thread(scheme, host, ca_certs, server_certs):
    io_loop = ioloop.IOLoop.current()
    app = web.Application([(r".*", TestingApp)])
    server, port = run_tornado_app(app, io_loop, server_certs, scheme, host)
    server_thread = threading.Thread(target=io_loop.start)
    server_thread.start()

    yield ServerConfig(host, port, ca_certs)

    io_loop.add_callback(server.stop)
    io_loop.add_callback(io_loop.stop)
    server_thread.join()


@pytest.fixture
def no_san_server(tmp_path_factory):
    with run_server_in_thread("https", "localhost", NO_SAN_CA, NO_SAN_CERTS) as cfg:
        yield cfg

import pytest
import trustme

from dummyserver.server import (
    DEFAULT_CA,
    DEFAULT_CA_KEY,
    CLIENT_INTERMEDIATE_PEM,
    CLIENT_NO_INTERMEDIATE_PEM,
    CLIENT_INTERMEDIATE_KEY,
)


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

from typing import Dict, Tuple, Union

# https://github.com/python/typeshed/blob/master/stdlib/2and3/ssl.pyi
_PCTRTT = Tuple[Tuple[str, str], ...]
_PCTRTTT = Tuple[_PCTRTT, ...]
_PeerCertRetDictType = Dict[str, Union[str, _PCTRTTT, _PCTRTT]]
_PeerCertRetType = Union[_PeerCertRetDictType, bytes, None]

class CertificateError(ValueError): ...

def match_hostname(cert: _PeerCertRetType, hostname: str) -> None: ...

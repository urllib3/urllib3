import struct


# TODO: docs
TLS_PROTOCOL_VERSIONS = {
    "SSLv2": (0, 2),
    "SSLv3": (3, 0),
    "TLSv1": (3, 1),
    "TLSv1.1": (3, 2),
    "TLSv1.2": (3, 3),
}
TLS_RECORD_TYPE_ALERT = 0x15
TLS_ALERT_DESCRIPTION_UNKNOWN_CA = 0x30
TLS_ALERT_SEVERITY_FATAL = 0x02


def build_tls_alert_record(version, severity, description):
    # TODO: docs
    alert_payload = _build_tls_alert_payload(severity, description)
    record = _build_tls_record(version, TLS_RECORD_TYPE_ALERT, alert_payload)
    return record


def _build_tls_record(version, record_type, msg):
    ver_maj, ver_min = TLS_PROTOCOL_VERSIONS[version]
    msg_len = len(msg)
    record = struct.pack(">BBBH", record_type, ver_maj, ver_min, msg_len) + msg
    return record


def _build_tls_alert_payload(severity, description):
    return struct.pack(">BB", severity, description)

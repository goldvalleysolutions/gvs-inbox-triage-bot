"""Throwaway TLS for the fake mail servers (test only).

``write(folder)`` makes a self-signed cert for 127.0.0.1/localhost and a CA bundle
(system CAs + this cert). Start the bot with ``SSL_CERT_FILE=<bundle>`` so Core's
verified default SSL context trusts the fakes (verification stays on) and real HTTPS
(a live LLM) still works. ``server_context()`` loads the cert for the fake servers.
"""

from __future__ import annotations

import datetime
import ipaddress
import os
import ssl
from pathlib import Path

DIR_ENV = "FAKE_MAIL_CERT_DIR"


def write(folder: Path) -> Path:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM)
    (folder / "cert.pem").write_bytes(pem)
    (folder / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    system = b""
    paths = ssl.get_default_verify_paths()
    for cand in (paths.cafile, "/etc/ssl/certs/ca-certificates.crt"):
        if cand and os.path.isfile(cand):
            system = Path(cand).read_bytes()
            break
    try:
        import certifi

        system += b"\n" + Path(certifi.where()).read_bytes()
    except ImportError:
        pass
    (folder / "bundle.pem").write_bytes(system + b"\n" + pem)
    os.environ[DIR_ENV] = str(folder)
    return folder / "bundle.pem"


def server_context() -> ssl.SSLContext:
    folder = Path(os.environ[DIR_ENV])
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(folder / "cert.pem", folder / "key.pem")
    return ctx

"""SNS signature checks: valid, tampered, and a certificate host that is not AWS."""

from __future__ import annotations

import base64
import datetime

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509 import CertificateBuilder, Name, NameAttribute, random_serial_number
from cryptography.x509.oid import NameOID

from docintel.apps.core.exceptions import DomainError
from docintel.apps.documents.sns import canonical_string, validate_cert_url, verify_signature


def _certificate():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = Name([NameAttribute(NameOID.COMMON_NAME, "sns.us-east-1.amazonaws.com")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM)


def _message(body: str = "hello") -> dict[str, str]:
    return {
        "Type": "Notification",
        "MessageId": "mid",
        "TopicArn": "arn:aws:sns:us-east-1:123:textract",
        "Message": body,
        "Timestamp": "2026-01-01T00:00:00.000Z",
        "SignatureVersion": "1",
    }


def _sign(key, message: dict[str, str]) -> dict[str, str]:
    signature = key.sign(
        canonical_string(message).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA1(),
    )
    signed = dict(message)
    signed["Signature"] = base64.b64encode(signature).decode("ascii")
    signed["SigningCertURL"] = "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-example.pem"
    return signed


def test_valid_signature_verifies() -> None:
    key, pem = _certificate()
    verify_signature(_sign(key, _message()), pem)


def test_tampered_body_is_rejected() -> None:
    key, pem = _certificate()
    signed = _sign(key, _message())
    signed["Message"] = "tampered"
    with pytest.raises(DomainError) as caught:
        verify_signature(signed, pem)
    assert caught.value.code == "invalid_sns_signature"


def test_certificate_host_must_be_sns() -> None:
    with pytest.raises(DomainError) as caught:
        validate_cert_url("https://evil.example/SimpleNotificationService-x.pem")
    assert caught.value.code == "invalid_sns_cert"


def test_certificate_path_must_look_like_sns() -> None:
    with pytest.raises(DomainError):
        validate_cert_url("https://sns.us-east-1.amazonaws.com/not-a-cert.pem")

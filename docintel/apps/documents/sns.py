"""SNS signature verification for the Textract notification channel.

The signing certificate is fetched only after the URL's host is checked
against ``sns.<region>.amazonaws.com``. Certificates are cached for an hour.
Subscription confirmation GETs the ``SubscribeURL`` with the same host rule,
so a forged message cannot turn this process into an open proxy.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate
from django.core.cache import cache

from docintel.apps.core.exceptions import DomainError

_SNS_HOST = re.compile(r"sns\.[a-z0-9-]+\.amazonaws\.com(\.cn)?\Z")
CertFetcher = Callable[[str], bytes]


def validate_sns_host(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise DomainError("SNS URL must be https with no userinfo.", code="invalid_sns_cert")
    host = parsed.hostname or ""
    if _SNS_HOST.fullmatch(host) is None:
        raise DomainError(
            "SNS URL host is not an AWS SNS endpoint.",
            code="invalid_sns_cert",
        )


def validate_cert_url(url: str) -> None:
    validate_sns_host(url)
    path = urllib.parse.urlparse(url).path
    if not path.startswith("/SimpleNotificationService-"):
        raise DomainError("SNS certificate path is not recognised.", code="invalid_sns_cert")


def canonical_string(message: Mapping[str, str]) -> str:
    kind = message.get("Type", "")
    if kind == "Notification":
        keys = ["Message", "MessageId"]
        if message.get("Subject"):
            keys.append("Subject")
        keys.extend(["Timestamp", "TopicArn", "Type"])
    elif kind in {"SubscriptionConfirmation", "UnsubscribeConfirmation"}:
        keys = ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]
    else:
        raise DomainError("Unsupported SNS message type.", code="invalid_sns_message")
    lines: list[str] = []
    for key in keys:
        if key not in message:
            raise DomainError(f"SNS message is missing {key}.", code="invalid_sns_message")
        lines.append(key)
        lines.append(message[key])
    return "\n".join(lines) + "\n"


def verify_signature(message: Mapping[str, str], certificate_pem: bytes) -> None:
    try:
        signature = base64.b64decode(message["Signature"])
    except (KeyError, ValueError) as exc:
        raise DomainError("SNS signature is missing or not base64.", code="invalid_sns_signature") from exc
    certificate = load_pem_x509_certificate(certificate_pem)
    public_key = certificate.public_key()
    algorithm = hashes.SHA256() if message.get("SignatureVersion") == "2" else hashes.SHA1()
    try:
        public_key.verify(  # type: ignore[call-arg]
            signature,
            canonical_string(message).encode("utf-8"),
            padding.PKCS1v15(),
            algorithm,
        )
    except InvalidSignature as exc:
        raise DomainError("SNS signature does not match the payload.", code="invalid_sns_signature") from exc


def fetch_certificate(url: str, *, fetcher: CertFetcher | None = None) -> bytes:
    validate_cert_url(url)
    cache_key = f"sns-cert:{url}"
    cached = cache.get(cache_key)
    if isinstance(cached, bytes):
        return cached
    pem = (fetcher or _default_fetcher)(url)
    if b"BEGIN CERTIFICATE" not in pem:
        raise DomainError("SNS certificate response was not a PEM.", code="invalid_sns_cert")
    cache.set(cache_key, pem, timeout=60 * 60)
    return pem


def parse_notification(message: Mapping[str, str]) -> dict[str, Any]:
    raw = message.get("Message", "")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DomainError("SNS notification body is not JSON.", code="invalid_sns_message") from exc
    if not isinstance(payload, dict):
        raise DomainError("SNS notification body is not an object.", code="invalid_sns_message")
    return payload


def confirm_subscription(url: str) -> None:
    validate_sns_host(url)
    with urllib.request.urlopen(url, timeout=5) as response:
        response.read(1024)


def _default_fetcher(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=5) as response:
        return bytes(response.read(1024 * 1024))

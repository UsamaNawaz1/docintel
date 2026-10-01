"""SES and the in-memory mailbox used by tests and seed."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings


@dataclass
class SentEmail:
    sender: str
    recipients: list[str]
    subject: str
    body: str


@dataclass
class MemoryMailbox:
    messages: list[SentEmail] = field(default_factory=list)

    def send(self, message: SentEmail) -> None:
        self.messages.append(message)


_mailbox = MemoryMailbox()


def mailbox() -> MemoryMailbox:
    return _mailbox


def send_email(*, sender: str, recipients: list[str], subject: str, body: str) -> None:
    if settings.EMAIL_BACKEND_IMPL == "memory":
        _mailbox.send(SentEmail(sender, list(recipients), subject, body))
        return
    import boto3

    boto3.client("ses", region_name=settings.AWS_DEFAULT_REGION).send_email(
        Source=sender,
        Destination={"ToAddresses": recipients[:50]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )

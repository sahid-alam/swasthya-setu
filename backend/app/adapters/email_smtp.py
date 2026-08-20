"""Real SMTP — Gmail, or any relay that speaks STARTTLS.

Selected only when `EMAIL_MOCK_MODE=false`. Failure here degrades: the delivery is
marked FAILED, the row still lands in the outbox, and the patient's flow carries on to
the next channel (`AdapterError`, never a crash).

Set in `.env` (never in code — Iron Rule 6):

    EMAIL_MOCK_MODE=false
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USERNAME=you@gmail.com
    SMTP_PASSWORD=<16-character Google app password, not your account password>
    SMTP_FROM="Swasthya-Setu <you@gmail.com>"

Gmail rejects a plain account password; the app password comes from Google Account →
Security → 2-Step Verification → App passwords.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.adapters.base import (
    AdapterError,
    DeliveryResult,
    MessagingAdapter,
    new_ref,
    normalise_email,
    render,
    subject,
)
from app.config import get_settings
from app.models import Channel, NotificationStatus

log = logging.getLogger("swasthya.email")

# Two attempts, not three: the failures worth retrying here are a dropped connection
# or a greylist, and an auth rejection will fail identically however many times you ask.
ATTEMPTS = 2
RETRYABLE = (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError)


class SmtpEmail(MessagingAdapter):
    channel = Channel.EMAIL

    def __init__(self) -> None:
        s = get_settings()
        if not (s.smtp_host and s.smtp_username and s.smtp_password):
            raise AdapterError("EMAIL_MOCK_MODE is false but SMTP_* is not configured")
        self._s = s

    async def send(self, *, to: str, template: str, params: dict) -> DeliveryResult:
        address = normalise_email(to)
        language = params.get("language", "EN")
        message = EmailMessage()
        # A display name, a Date and a Message-ID are what ordinary mail clients put on
        # every message. Their absence is a cheap spam signal, and this is the one part
        # of deliverability we control — the rest is domain reputation, which a Gmail
        # app password cannot buy. Expect the first send to land in spam regardless.
        message["From"] = self._s.smtp_from or formataddr(("Swasthya-Setu", self._s.smtp_username))
        message["To"] = address
        message["Reply-To"] = self._s.smtp_username
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=self._s.smtp_username.split("@")[-1])
        message["Auto-Submitted"] = "auto-generated"  # RFC 3834: this is transactional
        message["Subject"] = subject(template, language)
        message.set_content(render(template, params, language))

        last: Exception | None = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                # smtplib is blocking, and blocking the event loop would stall every
                # other request behind one slow relay.
                await asyncio.to_thread(self._deliver, message)
                return DeliveryResult(
                    status=NotificationStatus.SENT,
                    mock=False,
                    provider_ref=new_ref("smtp"),
                    # Body included, like the mock does: the outbox is judge-facing
                    # evidence, and "we sent something to this address" is not evidence.
                    payload={
                        "to": address,
                        "subject": message["Subject"],
                        "body": message.get_content(),
                    },
                )
            except RETRYABLE as exc:
                last = exc
                log.warning("smtp attempt %s/%s failed: %s", attempt, ATTEMPTS, exc)
                await asyncio.sleep(0.5 * attempt)
            except smtplib.SMTPException as exc:
                last = exc  # auth rejected, address refused — retrying changes nothing
                break

        return DeliveryResult(
            status=NotificationStatus.FAILED,
            mock=False,
            error=str(last),
            payload={
                "to": address,
                "subject": message["Subject"],
                "body": message.get_content(),
            },
        )

    def _deliver(self, message: EmailMessage) -> None:
        # Ten seconds, not the five the adapter skill asks of an HTTP vendor: SMTP is
        # connect, STARTTLS, auth and send — four round trips to a relay that is
        # allowed to be slow. Raise SMTP_TIMEOUT_SECONDS if your relay is slower.
        with smtplib.SMTP(
            self._s.smtp_host, self._s.smtp_port, timeout=self._s.smtp_timeout_seconds
        ) as server:
            server.starttls()
            server.login(self._s.smtp_username, self._s.smtp_password)
            server.send_message(message)

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(self._noop)
            return True
        except Exception:  # a health probe that raises is not a health probe
            return False

    def _noop(self) -> None:
        with smtplib.SMTP(
            self._s.smtp_host, self._s.smtp_port, timeout=self._s.smtp_timeout_seconds
        ) as server:
            server.noop()

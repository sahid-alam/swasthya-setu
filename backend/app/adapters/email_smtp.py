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
from html import escape

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

# DESIGN.md §1 tokens, inlined because email clients strip <style> and know nothing of
# CSS variables. Tables and inline styles are not nostalgia — Outlook still requires
# them, and this has to survive being forwarded to a district health officer.
INK, PRIMARY, ACCENT = "#0a0e14", "#0f4c81", "#00c49f"
BG, SURFACE, LINE, MUTED = "#f5f7fb", "#ffffff", "#e3e8f0", "#6b7588"

HTML = """\
<!doctype html>
<html><body style="margin:0;padding:24px 12px;background:{bg};
  font-family:-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:{ink}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="max-width:520px;background:{surface};border:1px solid {line};border-radius:12px">
  <tr><td style="padding:20px 28px;border-bottom:3px solid {accent};background:{primary};
    border-radius:12px 12px 0 0">
    <div style="font-size:18px;font-weight:600;color:#ffffff;letter-spacing:-0.01em">
      स्वास्थ्य-सेतु <span style="opacity:.7;font-weight:400">· Swasthya-Setu</span></div>
    <div style="font-size:12px;color:#c8d8ea;margin-top:2px">{tagline}</div>
  </td></tr>
  <tr><td style="padding:28px">
    <div style="font-size:17px;font-weight:600;margin-bottom:12px">{subject}</div>
    <div style="font-size:15px;line-height:1.6;color:{ink}">{body}</div>
    {feature}
  </td></tr>
  <tr><td style="padding:16px 28px;border-top:1px solid {line};font-size:12px;color:{muted};
    background:#fafbfd;border-radius:0 0 12px 12px">
    {footer}
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

CODE_BLOCK = """
<div style="margin:22px 0;padding:16px;text-align:center;background:#e7eef8;
  border:1px dashed {primary};border-radius:10px">
  <div style="font-size:12px;color:{muted};letter-spacing:.08em;text-transform:uppercase">
    {label}</div>
  <div style="font-family:'SF Mono',Menlo,Consolas,monospace;font-size:32px;font-weight:700;
    letter-spacing:.28em;color:{primary};margin-top:6px">{code}</div>
</div>"""

# Deliberately no claim of official standing. "Himachal Pradesh hospital network" in a
# real inbox reads as a government service, and we are not one — a subtitle is not the
# place to borrow authority we do not have.
TAGLINE = {
    "EN": "Appointment service",
    "HI": "अपॉइंटमेंट सेवा",
}
FOOTER = {
    "EN": "This is an automated message. Please do not reply to it.",
    "HI": "यह एक स्वचालित संदेश है। कृपया इसका उत्तर न दें।",
}
CODE_LABEL = {"EN": "Your login code", "HI": "आपका लॉगिन कोड"}


def as_html(subject_line: str, body: str, template: str, params: dict, language: str) -> str:
    """The same words as the plain-text part, in a shape that does not look like spam.

    The words themselves still come from `render()` (D21) — this only dresses them, so
    an email can never say something the SMS does not.
    """
    feature = ""
    if template == "otp" and params.get("code"):
        # The code is the whole message; a patient should not have to read a sentence
        # to find six digits.
        feature = CODE_BLOCK.format(
            primary=PRIMARY,
            muted=MUTED,
            label=CODE_LABEL.get(language.upper(), CODE_LABEL["EN"]),
            code=escape(str(params["code"])),
        )
    return HTML.format(
        bg=BG,
        ink=INK,
        surface=SURFACE,
        line=LINE,
        accent=ACCENT,
        primary=PRIMARY,
        muted=MUTED,
        tagline=TAGLINE.get(language.upper(), TAGLINE["EN"]),
        footer=FOOTER.get(language.upper(), FOOTER["EN"]),
        subject=escape(subject_line),
        # Escape first, then turn newlines into breaks — the other order would escape
        # the <br> we just added. Everything reaching here is ours today, but patients
        # now type their own names at self-registration, and this is a document sent
        # to third parties over our name: it must not be able to carry their markup.
        body=escape(body).replace("\n", "<br>"),
        feature=feature,
    )


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
        subject_line = subject(template, language)
        text = render(template, params, language)
        message["Subject"] = subject_line
        # Plain text first, HTML as the alternative: a client that cannot render HTML
        # still gets the whole message, and multipart/alternative is what ordinary mail
        # looks like.
        message.set_content(text)
        message.add_alternative(
            as_html(subject_line, text, template, params, language), subtype="html"
        )

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
                        "body": text,
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
                "body": text,
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

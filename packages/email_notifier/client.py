from __future__ import annotations

import smtplib
import time
from email.message import EmailMessage

from pydantic import BaseModel


class EmailSendResult(BaseModel):
    success: bool
    error: str | None = None
    latency_ms: int
    status_code: int | None = None


class SmtpEmailClient:
    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        username: str | None,
        password: str | None,
        from_email: str,
        from_name: str | None = None,
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout_seconds: int = 15,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout_seconds = timeout_seconds

    def send(self, *, subject: str, body_text: str, to_emails: list[str]) -> EmailSendResult:
        started = time.perf_counter()
        try:
            message = EmailMessage()
            sender = f"{self.from_name} <{self.from_email}>" if self.from_name else self.from_email
            message["From"] = sender
            message["To"] = ", ".join(to_emails)
            message["Subject"] = subject
            message.set_content(body_text)

            smtp_cls = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP
            with smtp_cls(self.smtp_host, self.smtp_port, timeout=self.timeout_seconds) as smtp:
                if self.use_tls and not self.use_ssl:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(message)
        except Exception as exc:
            return EmailSendResult(
                success=False,
                error=exc.__class__.__name__,
                latency_ms=_latency_ms(started),
                status_code=None,
            )
        return EmailSendResult(success=True, latency_ms=_latency_ms(started), status_code=None)


def _latency_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)

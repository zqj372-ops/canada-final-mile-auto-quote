import pytest

from apps.api.services import notification_service
from packages.email_notifier.client import EmailSendResult
from packages.wecom.bot_client import WeComSendResult


@pytest.mark.parametrize(
    ("channels", "expected"),
    [
        (set(), []),
        ({"email"}, ["email"]),
        ({"wecom"}, ["wecom"]),
        ({"email", "wecom"}, ["email", "wecom"]),
    ],
)
def test_requested_notification_channels_do_not_fall_back_to_another_channel(
    monkeypatch: pytest.MonkeyPatch,
    channels: set[str],
    expected: list[str],
) -> None:
    sent: list[str] = []
    monkeypatch.setattr(notification_service, "_select_email_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        notification_service,
        "_send_with_email_config",
        lambda *_args, **_kwargs: sent.append("email")
        or EmailSendResult(success=True, error=None, latency_ms=1, status_code=200),
    )
    monkeypatch.setattr(
        notification_service,
        "_send_markdown",
        lambda *_args, **_kwargs: sent.append("wecom")
        or WeComSendResult(success=True, error=None, latency_ms=1, status_code=200),
    )

    notification_service._send_notification(
        object(),  # type: ignore[arg-type]
        purpose="quote_success",
        subject="subject",
        body_text="body",
        markdown="markdown",
        channels=channels,  # type: ignore[arg-type]
    )

    assert sent == expected

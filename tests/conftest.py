import pytest


@pytest.fixture(autouse=True)
def disable_auth_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "true")
    monkeypatch.setenv("QUOTE_ADMISSION_DB", str(tmp_path / "quote_admission.sqlite3"))

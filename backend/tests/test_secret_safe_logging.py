import logging
import sys
from secret_safe_logging import SecretSafeFormatter


def test_rendered_logs_redact_telegram_mongo_authorization_and_environment_secrets(monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-secret-example")
    monkeypatch.setenv("JWT_SECRET", "jwt-secret-example")
    formatter = SecretSafeFormatter("%(levelname)s %(message)s")
    message = ('https://api.telegram.org/bot123:private-token/getUpdates '
               'https://api.telegram.org/file/bot123:private-token/file.jpg '
               'mongodb://database-user:database-password@db-host/db '
               'Authorization: Bearer private-bearer smtp-secret-example jwt-secret-example')
    record = logging.LogRecord("audit", logging.ERROR, __file__, 1, message, (), None)
    output = formatter.format(record)
    for value in ("private-token", "database-user", "database-password", "private-bearer", "smtp-secret-example", "jwt-secret-example"):
        assert value not in output
    assert "[REDACTED]" in output


def test_exception_traceback_also_redacts_bot_url():
    try:
        raise RuntimeError("HTTP failure at https://api.telegram.org/bot123:private-token/sendMessage")
    except RuntimeError:
        record = logging.LogRecord("audit", logging.ERROR, __file__, 1, "tenant slug=shop", (), sys.exc_info())
    rendered = SecretSafeFormatter("%(message)s").format(record)
    assert "private-token" not in rendered
    assert "tenant slug=shop" in rendered and "RuntimeError" in rendered

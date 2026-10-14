"""Redact credential-bearing URLs and environment secrets in rendered logs."""
import logging
import os
import re


class SecretSafeFormatter(logging.Formatter):
    def format(self, record):
        output = super().format(record)
        # Token-bearing Telegram URLs can appear in HTTPError tracebacks.
        output = re.sub(r"(api\.telegram\.org/(?:file/)?bot)[^/\s\"']+", r"\1[REDACTED]", output)
        output = re.sub(r"mongodb(?:\+srv)?://[^\s\"']+", "mongodb://[REDACTED]", output)
        output = re.sub(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?(?:Bearer\s+)?)[^\s\"',}]+", r"\1[REDACTED]", output)
        for name, value in os.environ.items():
            if len(value) >= 8 and any(key in name.upper() for key in (
                "TOKEN", "SECRET", "PASSWORD", "ENCRYPTION_KEY", "SESSION_KEY",
            )):
                output = output.replace(value, "[REDACTED]")
        return output


def protect_root_logs():
    for handler in logging.getLogger().handlers:
        handler.setFormatter(SecretSafeFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))

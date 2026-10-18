import logging
import re
from collections.abc import Iterable

# Query-string credentials that must never reach a log line, even for keys we don't know about.
_QUERY_SECRET = re.compile(r"(?i)\b(token|api_key|apikey)=[^&\s'\"]+")


class RedactSecretsFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _QUERY_SECRET.sub(r"\1=***", message)
        for secret in self._secrets:
            redacted = redacted.replace(secret, "***")
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def configure_logging(level: str, secrets: Iterable[str]) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactSecretsFilter(secrets))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # httpx logs full request URLs at INFO, and FRED requires its key in the query string.
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

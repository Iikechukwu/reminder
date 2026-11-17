"""Structured JSON logging: one JSON object per line, machine-parsable."""
import contextvars
import json
import logging
from datetime import datetime, timezone

# Set per request by middleware so every log line of a request shares an id.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# Attributes every LogRecord has; anything else came from `extra={...}`.
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            data["request_id"] = rid
        for key, value in record.__dict__.items():
            if key not in _STANDARD:
                data[key] = value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Idempotent. Only touches the 'reminder' logger namespace."""
    logger = logging.getLogger("reminder")
    logger.setLevel(level.upper())
    if not any(getattr(h, "_reminder_json", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler._reminder_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)

import logging
import json
from datetime import datetime
from typing import Any, Dict

class SelfHealingJSONFormatter(logging.Formatter):
    def __init__(self):
        super().__init__()
        self.sensitive_keys = {"password", "token", "api_key", "secret", "auth", "session"}

    def _sanitize(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                k: ("***" if any(sec in k.lower() for sec in self.sensitive_keys) else self._sanitize(v))
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._sanitize(item) for item in data]
        return data

    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "time": datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name
        }

        if hasattr(record, "diagnostic_data"):
            log_record["diagnostics"] = self._sanitize(record.diagnostic_data) # type: ignore

        if hasattr(record, "subsystem"):
            log_record["subsystem"] = getattr(record, "subsystem")

        if hasattr(record, "problem"):
            log_record["problem"] = getattr(record, "problem")

        if hasattr(record, "action"):
            log_record["action"] = getattr(record, "action")

        if hasattr(record, "result"):
            log_record["result"] = getattr(record, "result")

        return json.dumps(log_record)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = SelfHealingJSONFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

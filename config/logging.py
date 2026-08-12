"""
Logging configuration for HelpDesk Enterprise Copilot.
Supports JSON and human-readable formats with structured logging.
"""

import sys
import json
from pathlib import Path
from typing import Any, Dict
from loguru import logger
from config.settings import get_settings


class JSONFormatter:
    """JSON log formatter for structured logging."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def format(self, record: Dict[str, Any]) -> str:
        log_entry = {
            "timestamp": record["time"].isoformat(),
            "level": record["level"].name,
            "logger": record["name"],
            "module": record["module"],
            "function": record["function"],
            "line": record["line"],
            "message": record["message"],
        }

        if record["extra"]:
            log_entry["extra"] = record["extra"]

        if record["exception"]:
            log_entry["exception"] = {
                "type": record["exception"].type.__name__,
                "value": str(record["exception"].value),
                "traceback": str(record["exception"].traceback),
            }

        return json.dumps(log_entry, ensure_ascii=False)


def _json_sink(settings):
    """Return a sink callable that writes JSON-formatted records."""
    formatter = JSONFormatter(settings)

    def sink(message):
        record = message.record
        sys.stderr.write(formatter.format(record) + "\n")

    return sink


def setup_logging():
    """Configure application logging."""
    settings = get_settings()

    # Remove default handler
    logger.remove()

    # Console handler
    if settings.LOG_FORMAT.lower() == "json":
        logger.add(
            _json_sink(settings),
            level=settings.LOG_LEVEL,
        )
    else:
        logger.add(
            sys.stdout,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                   "<level>{message}</level>",
            level=settings.LOG_LEVEL,
            colorize=True,
        )

    # File handler
    log_path = Path(settings.LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if settings.LOG_FORMAT.lower() == "json":
        logger.add(
            log_path,
            level=settings.LOG_LEVEL,
            rotation="10 MB",
            retention="30 days",
            compression="zip",
            serialize=True,
        )
    else:
        logger.add(
            log_path,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
            level=settings.LOG_LEVEL,
            rotation="10 MB",
            retention="30 days",
            compression="zip",
        )

    # Error file handler
    error_log_path = log_path.parent / "errors.log"
    if settings.LOG_FORMAT.lower() == "json":
        logger.add(
            error_log_path,
            level="ERROR",
            rotation="10 MB",
            retention="90 days",
            compression="zip",
            serialize=True,
        )
    else:
        logger.add(
            error_log_path,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
            level="ERROR",
            rotation="10 MB",
            retention="90 days",
            compression="zip",
        )

    return logger


def get_logger(name: str = None):
    """Get a logger instance with optional name binding."""
    if name:
        return logger.bind(name=name)
    return logger


# Initialize logging on import
setup_logging()
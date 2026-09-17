"""Logging setup.

Uvicorn only configures its own loggers, so without this every `logger.info()`
in the app is dropped by a root logger that has no handler.
"""

import logging
import logging.config

from app.config import Settings

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
DATE_FORMAT = "%H:%M:%S"


def configure_logging(settings: Settings) -> None:
    level = settings.log_level.upper()

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
                "access": {"format": "%(asctime)s %(levelname)-8s access   | %(message)s", "datefmt": DATE_FORMAT},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                },
                "access": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "access",
                },
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                "app": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
                # Very chatty at INFO; raise deliberately when debugging SQL.
                "sqlalchemy.engine": {"level": "WARNING", "propagate": True},
            },
        }
    )

"""Rotating local log + uncaught-exception hook."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .paths import log_path


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("focusmic")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        handler = RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=3,
                                      encoding="utf-8")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    except OSError:
        pass
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    def excepthook(exc_type, exc, tb):
        logger.exception("Unhandled exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook
    return logger

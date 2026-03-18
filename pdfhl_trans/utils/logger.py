"""Centralized logging configuration."""

from __future__ import annotations

import logging

from rich.logging import RichHandler


_CONFIGURED = False


def setup_logger(
    verbose: bool = False,
    debug: bool = False,
) -> logging.Logger:
    """Configure and return the application root logger.

    Uses Rich for coloured, readable console output. Calling this
    function multiple times is safe — subsequent calls are no-ops.

    Args:
        verbose: If True, set level to INFO.
        debug: If True, set level to DEBUG (overrides verbose).

    Returns:
        The configured root logger for the ``pdfhl_trans`` package.
    """
    global _CONFIGURED  # noqa: PLW0603

    logger = logging.getLogger("pdfhl_trans")

    if _CONFIGURED:
        return logger

    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    else:
        level = logging.WARNING

    handler = RichHandler(
        show_time=debug,
        show_path=debug,
        rich_tracebacks=True,
        tracebacks_show_locals=debug,
        markup=True,
    )
    handler.setLevel(level)

    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _CONFIGURED = True
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the application namespace.

    Args:
        name: Dot-separated child logger name (e.g. ``core.pdf_processor``).

    Returns:
        A child logger instance.
    """
    return logging.getLogger(f"pdfhl_trans.{name}")

"""Minimal logging setup so the app's own INFO logs reach the console.

uvicorn only configures its own ``uvicorn.*`` loggers; without this the ``app.*``
loggers fall back to the WARNING-only last-resort handler and scan timing logs
never appear. We attach one handler to the ``app`` logger and stop propagation
so nothing double-logs through uvicorn's handlers.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a stdout handler to the ``app`` logger tree. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    app_logger.addHandler(handler)
    app_logger.propagate = False
    _CONFIGURED = True

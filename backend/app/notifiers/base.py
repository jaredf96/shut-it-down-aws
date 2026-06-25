"""Notifier interface.

A Notifier delivers a list of Alerts to one channel (Slack, email, …). Keeping
`format` separate from `send` makes the message construction unit-testable
without actually sending anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import Alert


class Notifier(ABC):
    name: str

    @abstractmethod
    def send(self, alerts: list[Alert]) -> None:
        """Deliver the alerts. Should be a no-op for an empty list."""

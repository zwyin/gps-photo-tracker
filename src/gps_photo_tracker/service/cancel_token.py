"""Cancellation token for service operations."""

import threading


class CancellationToken:
    """Thread-safe cancellation signal."""

    def __init__(self):
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

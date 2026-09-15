"""Bounded exact-response cache; no embeddings and no cross-date paraphrase matches."""

from __future__ import annotations

import time
from collections import OrderedDict
from copy import deepcopy
from threading import Lock


class ExactCache:
    def __init__(self, max_size: int = 256, ttl_seconds: float = 300) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: tuple) -> dict | None:
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            expires, response = item
            if time.monotonic() >= expires:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return deepcopy(response)

    def put(self, key: tuple, response: dict) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic() + self.ttl_seconds, deepcopy(response))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_size:
                self._entries.popitem(last=False)

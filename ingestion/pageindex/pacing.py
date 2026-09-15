"""Scoped, resumable OpenAI-compatible completion transport for PageIndex 0.2.10.

The SDK has no completion hook; replace only its two helper functions during local
indexing and restore all imported aliases afterwards. Never patch site-packages.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

logger = logging.getLogger(__name__)
_scope_lock = threading.Lock()


class IndexingTransportError(RuntimeError):
    pass


class EmptyCompletionError(ValueError):
    pass


def retry_delay(exc, attempt: int) -> float:
    """Honor provider seconds/date headers or Groq's duration, without logging it."""
    headers = getattr(getattr(exc, "response", None), "headers", {})
    value = headers.get("retry-after")
    if value:
        try:
            return max(0.0, float(value)) + 1
        except ValueError:
            try:
                return (
                    max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()) + 1
                )
            except (ValueError, TypeError):
                pass
    match = re.search(r"try again in\s+((?:[\d.]+\s*(?:ms|h|m|s)\s*)+)", str(exc), re.I)
    if match:
        factors = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
        return (
            sum(
                float(n) * factors[u.lower()]
                for n, u in re.findall(r"([\d.]+)\s*(ms|h|m|s)", match[1], re.I)
            )
            + 1
        )
    return min(60.0, 5.0 * 2**attempt)


class PacedCompletions:
    def __init__(
        self,
        client,
        cache: Path,
        interval: float,
        attempts: int,
        max_wait: float,
        max_output_tokens: int = 4096,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.client, self.cache = client, cache
        self.interval, self.attempts, self.max_wait = interval, attempts, max_wait
        self.max_output_tokens = max_output_tokens
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.next_call = 0.0
        self.failure = None
        self.completed = 0

    def complete(self, model, prompt, chat_history=None, return_finish_reason=False):
        with self.lock:
            if self.failure:
                raise self.failure
            try:
                result = self._complete(model, prompt, chat_history)
            except Exception as exc:
                safe_reason = (
                    str(exc)
                    if str(exc)
                    in {
                        "Paced indexing requires an openai/ model and compatible base URL",
                        "Empty indexing completion",
                    }
                    else type(exc).__name__
                )
                self.failure = IndexingTransportError(
                    f"PageIndex completion stopped ({safe_reason}, "
                    f"HTTP {getattr(exc, 'status_code', None)}); "
                    "successful calls are cached for resume"
                )
                raise self.failure from None
        return (result["text"], result["finish"]) if return_finish_reason else result["text"]

    def _complete(self, model, prompt, chat_history):
        # Adapter supports an OpenAI-compatible endpoint, including slashed wire IDs.
        if not model.startswith("openai/"):
            raise ValueError("Paced indexing requires an openai/ model and compatible base URL")
        messages = list(chat_history or []) + [{"role": "user", "content": prompt}]
        request = {
            "model": model[len("openai/") :],
            "messages": messages,
            "max_tokens": self.max_output_tokens,
        }
        identity = json.dumps(
            {"version": 1, "base_url": str(self.client.base_url), **request}, sort_keys=True
        )
        path = self.cache / (hashlib.sha256(identity.encode()).hexdigest() + ".json")
        if path.exists():
            result = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(result.get("text"), str) and result.get("finish") in (
                "finished",
                "max_output_reached",
            ):
                return result
        for attempt in range(self.attempts):
            self.sleep(max(0.0, self.next_call - self.clock()))
            try:
                response = self.client.chat.completions.create(**request)
                choice = response.choices[0]
                if (
                    not isinstance(choice.message.content, str)
                    or not choice.message.content.strip()
                ):
                    raise EmptyCompletionError("Empty indexing completion")
            except Exception as exc:
                self.next_call = self.clock() + self.interval
                status = getattr(exc, "status_code", None)
                if status not in (408, 429, 500, 502, 503, 504) and type(exc).__name__ not in (
                    "APIConnectionError",
                    "APITimeoutError",
                    "EmptyCompletionError",
                ):
                    raise
                delay = max(self.interval, retry_delay(exc, attempt))
                if attempt + 1 >= self.attempts or delay > self.max_wait:
                    raise
                self.next_call = self.clock() + delay
                logger.warning(
                    "PageIndex provider backoff: HTTP %s, %.1fs, attempt %s/%s",
                    status,
                    delay,
                    attempt + 1,
                    self.attempts,
                )
                continue
            self.next_call = self.clock() + self.interval
            result = {
                "text": choice.message.content,
                "finish": "max_output_reached" if choice.finish_reason == "length" else "finished",
            }
            self.cache.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(result), encoding="utf-8")
            temp.replace(path)
            self.completed += 1
            logger.warning("PageIndex completion %s saved for resume", self.completed)
            return result
        raise AssertionError("Unreachable retry state")

    async def acomplete(self, model, prompt):
        return await asyncio.to_thread(self.complete, model, prompt)


@contextmanager
def paced_sdk(controller):
    from importlib.metadata import version

    if version("pageindex") != "0.2.10":
        raise RuntimeError("Review the completion hook before changing PageIndex 0.2.10")
    import pageindex.utils as utils

    with _scope_lock:
        old_sync, old_async = utils.llm_completion, utils.llm_acompletion
        sync, async_ = controller.complete, controller.acomplete

        def replace(before_sync, before_async, after_sync, after_async):
            for name, module in list(sys.modules.items()):
                if module is None or not name.startswith("pageindex."):
                    continue
                for key, value in list(vars(module).items()):
                    if value is before_sync:
                        setattr(module, key, after_sync)
                    elif value is before_async:
                        setattr(module, key, after_async)

        replace(old_sync, old_async, sync, async_)
        try:
            yield
            if controller.failure:
                raise controller.failure
        except Exception:
            if controller.failure:
                raise controller.failure from None
            raise
        finally:
            replace(sync, async_, old_sync, old_async)

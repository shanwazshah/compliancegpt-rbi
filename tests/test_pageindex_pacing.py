from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ingestion.pageindex.pacing import IndexingTransportError, PacedCompletions, retry_delay


class ProviderError(Exception):
    def __init__(self, status, message="", headers=None):
        super().__init__(message)
        self.status_code = status
        self.response = SimpleNamespace(headers=headers or {})


def response():
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="tree"), finish_reason="stop")]
    )


def controller(tmp_path, effects):
    now = [0.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    client = SimpleNamespace(
        base_url="https://example.test/v1",
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=effects))),
    )
    paced = PacedCompletions(client, tmp_path, 20, 3, 120, clock=lambda: now[0], sleep=sleep)
    return paced, client.chat.completions.create, waits


def test_retry_after_and_serial_spacing(tmp_path):
    paced, call, waits = controller(
        tmp_path, [ProviderError(429, headers={"retry-after": "45"}), response(), response()]
    )
    assert paced.complete("openai/model", "first") == "tree"
    paced.complete("openai/model", "second")
    assert call.call_count == 3
    assert waits == [0, 46, 20]


def test_cache_resume_does_not_contact_provider(tmp_path):
    paced, call, _ = controller(tmp_path, [response()])
    paced.complete("openai/model", "first")
    resumed, new_call, _ = controller(tmp_path, [])
    assert resumed.complete("openai/model", "first", return_finish_reason=True) == (
        "tree",
        "finished",
    )
    assert new_call.call_count == 0
    assert call.call_count == 1


@pytest.mark.parametrize("status,delay", [(401, "1"), (400, "1"), (429, "3600")])
def test_permanent_or_long_quota_failure_stops_later_calls(tmp_path, status, delay):
    paced, call, _ = controller(tmp_path, [ProviderError(status, headers={"retry-after": delay})])
    with pytest.raises(IndexingTransportError):
        paced.complete("openai/model", "one")
    with pytest.raises(IndexingTransportError):
        paced.complete("openai/model", "two")
    assert call.call_count == 1


def test_retries_are_bounded(tmp_path):
    paced, call, _ = controller(tmp_path, [ProviderError(503)] * 3)
    with pytest.raises(IndexingTransportError):
        paced.complete("openai/model", "one")
    assert call.call_count == 3


def test_groq_duration_units():
    assert retry_delay(ProviderError(429, "Please try again in 1m2.5s."), 0) == 63.5
    assert retry_delay(ProviderError(429, "Please try again in 60ms."), 0) == 1.06


def test_sdk_hook_restored_even_after_failure(tmp_path):
    pytest.importorskip("pageindex")
    import pageindex.utils as utils

    from ingestion.pageindex.pacing import paced_sdk

    original = utils.llm_completion
    paced, _, _ = controller(tmp_path, [ProviderError(401)])
    with pytest.raises(IndexingTransportError), paced_sdk(paced):
        try:
            utils.llm_completion("openai/model", "one")
        except IndexingTransportError:
            pass  # Even if an SDK layer absorbs a failure, reject partial publication.
    assert utils.llm_completion is original


def test_async_calls_share_spacing_and_cache(tmp_path):
    import asyncio
    paced, call, waits = controller(tmp_path, [response(), response()])

    async def run():
        return await asyncio.gather(
            paced.acomplete("openai/model", "one"),
            paced.acomplete("openai/model", "two"),
            paced.acomplete("openai/model", "one"),
        )

    assert asyncio.run(run()) == ["tree", "tree", "tree"]
    assert call.call_count == 2
    assert waits == [0, 20]


def test_original_transport_error_survives_sdk_wrapper(tmp_path):
    pytest.importorskip("pageindex")
    from ingestion.pageindex.pacing import paced_sdk
    paced, _, _ = controller(tmp_path, [ProviderError(413)])
    with pytest.raises(IndexingTransportError, match="HTTP 413"), paced_sdk(paced):
        try:
            paced.complete("openai/model", "one")
        except IndexingTransportError:
            raise RuntimeError("SDK summary failed") from None


def test_empty_completion_retries_without_caching_empty_text(tmp_path):
    empty = response()
    empty.choices[0].message.content = None
    paced, call, waits = controller(tmp_path, [empty, response()])
    assert paced.complete("openai/model", "one") == "tree"
    assert call.call_count == 2
    assert waits == [0, 20]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_layout_mode_uses_official_extractor_without_llm(tmp_path, monkeypatch):
    pytest.importorskip("pageindex")
    from unittest.mock import patch

    from app.config import settings
    from ingestion.pageindex.adapter import build_tree, normalize_tree
    monkeypatch.setattr(settings, "pageindex_tree_mode", "layout")
    tree = [{"title": "KYC", "start_index": 2, "end_index": 4}]
    with patch("pageindex.flash.page_index_flash", return_value={"structure": tree}) as extract:
        with patch("pageindex.PageIndexLocalClient") as client:
            raw, metadata = build_tree(tmp_path / "source.pdf")
    extract.assert_called_once_with(str(tmp_path / "source.pdf"), summary=False, optimize=False)
    client.assert_not_called()
    assert metadata["tree_mode"] == "layout"
    assert metadata["summaries"] is False
    assert normalize_tree(raw, 4)[0]["page_start"] == 2

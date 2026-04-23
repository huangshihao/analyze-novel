import json
import httpx
import pytest

from chapter_splitter import Chapter
from deepseek_client import DeepSeekClient, DeepSeekError


def _chapter(cid: int) -> Chapter:
    return Chapter(id=cid, title=f"第{cid}章", content="章节内容" * 50)


def _ok_response(summaries: dict[int, str]) -> httpx.Response:
    payload = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "chapters": [
                        {"chapter_id": cid, "summary": s}
                        for cid, s in summaries.items()
                    ]
                }, ensure_ascii=False),
            },
        }],
    }
    return httpx.Response(200, json=payload)


def test_summarize_batch_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "deepseek-chat"
        assert body["response_format"] == {"type": "json_object"}
        return _ok_response({1: "摘要一", 2: "摘要二"})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport)
    result = client.summarize_batch([_chapter(1), _chapter(2)])
    assert result == {1: "摘要一", 2: "摘要二"}


def test_summarize_batch_400_no_retry():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    with pytest.raises(DeepSeekError):
        client.summarize_batch([_chapter(1)])
    assert call_count == 1  # no retry on 4xx


def test_summarize_batch_429_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return _ok_response({1: "成功了"})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    result = client.summarize_batch([_chapter(1)])
    assert result == {1: "成功了"}
    assert calls["n"] == 3


def test_summarize_batch_429_exhausts_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    with pytest.raises(DeepSeekError) as exc_info:
        client.summarize_batch([_chapter(1)])
    assert "429" in str(exc_info.value) or "rate" in str(exc_info.value).lower()


def test_summarize_batch_timeout_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("timeout", request=request)
        return _ok_response({1: "终于"})

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    result = client.summarize_batch([_chapter(1)])
    assert result == {1: "终于"}
    assert calls["n"] == 2


def test_summarize_batch_invalid_json_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "not valid json {{"}}]
        })

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    with pytest.raises(DeepSeekError):
        client.summarize_batch([_chapter(1)])


def test_summarize_batch_missing_chapter_in_response():
    # Model returned 2 entries when we asked for 3 — result dict only contains
    # what the model returned. Caller (analyzer) is responsible for detecting
    # missing chapters.
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response({1: "a", 3: "c"})  # ch 2 missing

    transport = httpx.MockTransport(handler)
    client = DeepSeekClient(api_key="test-key", _transport=transport, _retry_base_delay=0)
    result = client.summarize_batch([_chapter(1), _chapter(2), _chapter(3)])
    assert result == {1: "a", 3: "c"}

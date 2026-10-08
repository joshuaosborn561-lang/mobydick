import json

import pytest
import requests

from mobydick.mcp_http import McpError, McpHttpClient, extract_tool_result, parse_mcp_response, tool_error_detail


class _Resp:
    def __init__(self, payload, content_type="application/json", status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        return self._payload


def test_parse_plain_json_rpc():
    rpc = parse_mcp_response(_Resp({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}), 1)
    assert rpc["result"]["ok"] is True


def test_parse_sse_json_rpc():
    text = 'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"tools":[]}}\n\n'
    rpc = parse_mcp_response(_Resp(text, content_type="text/event-stream"), 7)
    assert rpc["result"]["tools"] == []


def test_extract_tool_result_from_text_json():
    parsed = extract_tool_result(
        {
            "result": {
                "content": [{"type": "text", "text": json.dumps({"total": 3})}],
            }
        }
    )
    assert parsed["total"] == 3


def test_is_error_keeps_upstream_body():
    detail = 'invalid_columns: ["title","email"]. column_replacements: {"title":"current_title"}'
    with pytest.raises(McpError) as caught:
        extract_tool_result(
            {
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": detail}],
                }
            }
        )
    assert "invalid_columns" in str(caught.value)
    assert caught.value.body == detail
    assert caught.value.is_tool_error is True
    assert tool_error_detail({"content": [{"type": "text", "text": detail}]}) == detail


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _client(session: _Session) -> McpHttpClient:
    client = McpHttpClient(url="https://example.test/mcp", session=session)
    client._initialized = True
    client._sleeper = lambda delay: None
    return client


def _ok(payload: dict) -> _Resp:
    return _Resp({"jsonrpc": "2.0", "id": payload["id"], "result": {"ok": True}})


def test_rpc_retries_gateway_errors_then_succeeds():
    session = _Session([_Resp("cloudfront", status=504), _Resp("cloudfront", status=502), None])

    def post(url, json=None, headers=None, timeout=None):
        session.calls += 1
        if session.calls < 3:
            return _Resp("cloudfront", status=504 if session.calls == 1 else 502)
        return _ok(json)

    session.post = post
    rpc = _client(session)._rpc("tools/call", {"name": "search_contacts", "arguments": {}})
    assert rpc["result"]["ok"] is True
    assert session.calls == 3


def test_rpc_retries_timeouts_and_stops_after_five():
    session = _Session([])

    def post(url, json=None, headers=None, timeout=None):
        session.calls += 1
        raise requests.Timeout("read timed out")

    session.post = post
    with pytest.raises(McpError) as caught:
        _client(session)._rpc("tools/call", {"name": "search_contacts", "arguments": {}})
    assert session.calls == 5
    assert caught.value.status == 504


def test_rpc_does_not_retry_a_client_error():
    session = _Session([])

    def post(url, json=None, headers=None, timeout=None):
        session.calls += 1
        return _Resp("bad request", status=400)

    session.post = post
    with pytest.raises(McpError) as caught:
        _client(session)._rpc("tools/call", {"name": "search_contacts", "arguments": {}})
    assert session.calls == 1
    assert caught.value.status == 400

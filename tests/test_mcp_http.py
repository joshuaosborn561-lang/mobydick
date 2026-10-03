import json

from mobydick.mcp_http import extract_tool_result, parse_mcp_response


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

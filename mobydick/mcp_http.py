"""Synchronous Streamable HTTP MCP client (same shape as email-waterfall)."""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Any

import requests

logger = logging.getLogger("mobydick.mcp_http")

# Long enough for GetLeads invalid_columns + column_replacements, short enough for a job error.
ERROR_BODY_LIMIT = 4000

DEFAULT_PROTOCOL = "2025-03-26"
# CloudFront 502/503/504 and timeouts are transient. Five tries, then surface the error.
RETRY_STATUSES = frozenset({502, 503, 504})
MAX_RPC_ATTEMPTS = 5


class McpError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: str = "",
        is_tool_error: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.body = body
        self.is_tool_error = is_tool_error


class StaticToken:
    def __init__(self, token: str = "") -> None:
        self._token = token or ""

    def access_token(self) -> str:
        return self._token

    def invalidate(self) -> None:
        return


def _sse_messages(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for chunk in text.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[5:].lstrip() for line in chunk.split("\n") if line.startswith("data:")
        ]
        if not data_lines:
            continue
        raw = "\n".join(data_lines).strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            messages.append(parsed)
    return messages


def parse_mcp_response(response: requests.Response, request_id: Any) -> dict[str, Any]:
    ctype = (response.headers.get("Content-Type") or "").lower()
    text = response.text or ""
    if (
        "text/event-stream" in ctype
        or text.lstrip().startswith("event:")
        or "\ndata:" in f"\n{text}"
    ):
        messages = _sse_messages(text)
        for msg in messages:
            if str(msg.get("id")) == str(request_id):
                return msg
        for msg in reversed(messages):
            if "result" in msg or "error" in msg:
                return msg
        raise McpError(
            "SSE response had no matching JSON-RPC id",
            status=response.status_code,
            body=text[:300],
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise McpError(
            "non-JSON MCP response",
            status=response.status_code,
            body=text[:300],
        ) from exc
    if isinstance(data, dict):
        return data
    raise McpError("MCP JSON was not an object", status=response.status_code, body=text[:300])


def backoff_seconds(attempt: int) -> float:
    """Exponential delay with jitter. attempt is 1-based for the try that just failed."""
    base = 0.5 * (2 ** max(0, attempt - 1))
    return base + random.uniform(0, base * 0.25)


def tool_error_detail(result: dict[str, Any]) -> str:
    """Text GetLeads (and other MCP servers) put on an isError result."""
    parts: list[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in (None, "text"):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            parts.append(text)
    structured = result.get("structuredContent")
    if isinstance(structured, (dict, list)):
        parts.append(json.dumps(structured, default=str))
    elif structured not in (None, ""):
        parts.append(str(structured))
    if not parts:
        parts.append(json.dumps(result, default=str))
    detail = "\n".join(parts).strip()
    return detail[:ERROR_BODY_LIMIT]


def extract_tool_result(rpc: dict[str, Any]) -> dict[str, Any]:
    if rpc.get("error"):
        err = rpc["error"]
        body = json.dumps(err, default=str)[:ERROR_BODY_LIMIT]
        message = str(err.get("message") or err)
        if body and body not in message:
            message = f"{message}: {body}"
        raise McpError(message, body=body)
    result = rpc.get("result")
    if not isinstance(result, dict):
        raise McpError("MCP tools/call missing result object")
    if result.get("isError") is True:
        detail = tool_error_detail(result)
        raise McpError(f"MCP tool isError: {detail}", is_tool_error=True, body=detail)
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    if isinstance(structured, list):
        return {"items": structured}
    for item in result.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = str(item.get("text") or "")
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            return {"text": text}
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"value": parsed}
    return result


class McpHttpClient:
    def __init__(
        self,
        *,
        url: str,
        token: str = "",
        timeout: int = 60,
        client_name: str = "mobydick",
        client_version: str = "1.0.0",
        session: requests.Session | None = None,
    ) -> None:
        self.url = url
        self.token = StaticToken(token)
        self.timeout = timeout
        self._client_name = client_name
        self._client_version = client_version
        self._session = session or requests.Session()
        self._lock = threading.Lock()
        self._id_lock = threading.Lock()
        self._next_id = 1
        self._session_id = ""
        self._protocol = DEFAULT_PROTOCOL
        self._initialized = False
        self._sleeper = time.sleep

    def _next_rpc_id(self) -> int:
        with self._id_lock:
            rid = self._next_id
            self._next_id += 1
            return rid

    def _headers(self, *, include_protocol: bool) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        access = self.token.access_token()
        if access:
            headers["Authorization"] = f"Bearer {access}"
        if include_protocol:
            headers["MCP-Protocol-Version"] = self._protocol
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(
        self,
        payload: dict[str, Any],
        *,
        include_protocol: bool,
        timeout: float | None = None,
    ) -> requests.Response:
        return self._session.post(
            self.url,
            json=payload,
            headers=self._headers(include_protocol=include_protocol),
            timeout=self.timeout if timeout is None else timeout,
        )

    def initialize(self) -> dict[str, Any]:
        with self._lock:
            return self._initialize_locked()

    def _initialize_locked(self) -> dict[str, Any]:
        rpc_id = self._next_rpc_id()
        payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "initialize",
            "params": {
                "protocolVersion": DEFAULT_PROTOCOL,
                "capabilities": {},
                "clientInfo": {
                    "name": self._client_name,
                    "version": self._client_version,
                },
            },
        }
        resp = self._post(payload, include_protocol=False)
        if resp.status_code >= 400:
            body = (resp.text or "")[:ERROR_BODY_LIMIT]
            raise McpError(
                f"MCP initialize failed: {body}",
                status=resp.status_code,
                body=body,
            )
        session = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
        if session:
            self._session_id = session
        rpc = parse_mcp_response(resp, rpc_id)
        result = rpc.get("result") if isinstance(rpc.get("result"), dict) else {}
        self._protocol = str(result.get("protocolVersion") or DEFAULT_PROTOCOL)
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            include_protocol=True,
        )
        self._initialized = True
        return result

    def _rpc_once(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        rpc_id = self._next_rpc_id()
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
        if params is not None:
            payload["params"] = params
        resp = self._post(payload, include_protocol=True, timeout=timeout)
        if resp.status_code == 404 and self._session_id:
            with self._lock:
                self._session_id = ""
                self._initialized = False
                self._initialize_locked()
            resp = self._post(payload, include_protocol=True, timeout=timeout)
        if resp.status_code >= 400:
            body = (resp.text or "")[:ERROR_BODY_LIMIT]
            raise McpError(
                f"MCP HTTP {resp.status_code}: {body}",
                status=resp.status_code,
                body=body,
            )
        return parse_mcp_response(resp, rpc_id)

    def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not self._initialized:
            self.initialize()
        last_error: Exception | None = None
        for attempt in range(1, MAX_RPC_ATTEMPTS + 1):
            try:
                return self._rpc_once(method, params, timeout=timeout)
            except requests.Timeout as exc:
                last_error = exc
            except McpError as exc:
                if exc.status not in RETRY_STATUSES or exc.is_tool_error:
                    raise
                last_error = exc
            if attempt >= MAX_RPC_ATTEMPTS:
                break
            delay = backoff_seconds(attempt)
            logger.warning("MCP %s attempt %s failed (%s); retrying in %.2fs", method, attempt, last_error, delay)
            self._sleeper(delay)
        if isinstance(last_error, McpError):
            raise last_error
        raise McpError(f"MCP timeout: {last_error}", status=504, body=str(last_error or "")) from last_error

    def list_tools(self) -> list[dict[str, Any]]:
        rpc = self._rpc("tools/list")
        result = rpc.get("result") if isinstance(rpc.get("result"), dict) else {}
        tools = result.get("tools") or []
        return [t for t in tools if isinstance(t, dict)]

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        rpc = self._rpc("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout)
        try:
            return extract_tool_result(rpc)
        except McpError as exc:
            if exc.is_tool_error or exc.body:
                logger.error("MCP tool %s failed: %s", name, exc.body or exc)
            raise McpError(
                f"MCP tool {name} failed: {exc.body or exc}",
                status=exc.status,
                body=exc.body,
                is_tool_error=exc.is_tool_error,
            ) from exc

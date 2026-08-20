"""Vapi voice agent — the tool-call boundary.

Vapi runs the speech: the browser talks to Vapi, Vapi decides when to call one of our
tools, and posts to our webhook from its own servers. So the only vendor shape that
reaches us is the tool-call envelope, and it stops here.

There is no `vapi_mock.py`, because the fallback for a voice agent is not a fake voice
agent: it is `simulators/vapi_call.py` posting this exact envelope with no internet, and
the IVR line, which books the same appointment from a feature phone. Iron Rule 4 asks
that the demo survive offline, not that every vendor get a puppet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.adapters.base import AdapterError


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


def parse_tool_calls(payload: dict) -> tuple[str, list[ToolCall]]:
    """`(call_id, calls)`. Raises `AdapterError` if this is not a tool-call message.

    Vapi has shipped the call under both `{"name", "arguments"}` and a nested
    `{"function": {...}}`, and sends `arguments` as either an object or a JSON string.
    Accepting all of them here is the adapter doing its job; the flow sees one shape.
    """
    message = payload.get("message") or {}
    if message.get("type") not in (None, "tool-calls"):
        raise AdapterError(f"not a tool-call message: {message.get('type')}")

    raw = message.get("toolCallList") or message.get("toolCalls") or []
    if not raw:
        raise AdapterError("tool-call message carries no tool calls")

    call_id = str((message.get("call") or {}).get("id") or payload.get("callId") or "")
    if not call_id:
        raise AdapterError("tool call has no call id to hang a conversation on")

    calls = []
    for item in raw:
        fn = item.get("function") or item
        arguments = fn.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                raise AdapterError(f"tool arguments are not JSON: {exc}") from exc
        name = fn.get("name")
        if not name:
            raise AdapterError("tool call has no function name")
        calls.append(ToolCall(id=str(item.get("id") or ""), name=str(name), arguments=arguments))
    return call_id, calls


def tool_results(results: list[tuple[str, str]]) -> dict:
    """What Vapi expects back: one result per tool call id, as text the model reads."""
    return {"results": [{"toolCallId": call_id, "result": text} for call_id, text in results]}

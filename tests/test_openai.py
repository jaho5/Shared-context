"""Tests for the OpenAI integration module."""

import json

import pytest

from shared_context import SharedContextStore
from shared_context.openai import handle_tool_call, process_response, tool_definition


@pytest.fixture
def store() -> SharedContextStore:
    return SharedContextStore("test")


# -- tool_definition ---------------------------------------------------------

def test_tool_definition_is_openai_format() -> None:
    td = tool_definition()
    assert td["type"] == "function"
    assert td["function"]["name"] == "shared_context"


# -- handle_tool_call (dict format) ------------------------------------------

def _make_tool_call(action: str, key: str = "", value: str = "", call_id: str = "tc_1") -> dict:
    args = {"action": action}
    if key:
        args["key"] = key
    if value:
        args["value"] = value
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "shared_context",
            "arguments": json.dumps(args),
        },
    }


def test_handle_write_and_read(store: SharedContextStore) -> None:
    # Write.
    tc = _make_tool_call("write", key="foo", value="bar")
    result = handle_tool_call(tc, store, participant="agent_a")
    assert result is not None
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "tc_1"
    body = json.loads(result["content"])
    assert body["version"] == 1
    assert body["written_by"] == "agent_a"

    # Read back.
    tc2 = _make_tool_call("read", key="foo", call_id="tc_2")
    result2 = handle_tool_call(tc2, store, participant="agent_a")
    body2 = json.loads(result2["content"])
    assert body2["value"] == "bar"


def test_handle_list_keys(store: SharedContextStore) -> None:
    store.write("x", "1", written_by="a")
    tc = _make_tool_call("list_keys")
    result = handle_tool_call(tc, store, participant="agent")
    body = json.loads(result["content"])
    assert len(body["keys"]) == 1


def test_handle_ignores_other_tools(store: SharedContextStore) -> None:
    tc = {
        "id": "tc_99",
        "type": "function",
        "function": {"name": "web_search", "arguments": "{}"},
    }
    result = handle_tool_call(tc, store, participant="agent")
    assert result is None


def test_handle_error_returns_json(store: SharedContextStore) -> None:
    tc = _make_tool_call("read", key="missing")
    result = handle_tool_call(tc, store, participant="agent")
    body = json.loads(result["content"])
    assert body["error"] == "KEY_NOT_FOUND"


# -- process_response (dict format) ------------------------------------------

def _make_response(content: str | None, tool_calls: list | None, finish_reason: str) -> dict:
    message: dict = {"role": "assistant"}
    if content:
        message["content"] = content
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message, "finish_reason": finish_reason}]}


def test_process_response_stop(store: SharedContextStore) -> None:
    resp = _make_response("Hello!", None, "stop")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is True
    assert len(msgs) == 1
    assert msgs[0]["content"] == "Hello!"


def test_process_response_tool_calls(store: SharedContextStore) -> None:
    tc = _make_tool_call("write", key="a", value="b")
    resp = _make_response(None, [tc], "tool_calls")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is False
    # msgs[0] is the assistant message, msgs[1] is the tool result.
    assert len(msgs) == 2
    assert msgs[0]["role"] == "assistant"
    assert msgs[1]["role"] == "tool"
    body = json.loads(msgs[1]["content"])
    assert body["version"] == 1


def test_process_response_multiple_tool_calls(store: SharedContextStore) -> None:
    tc1 = _make_tool_call("write", key="a", value="1", call_id="tc_1")
    tc2 = _make_tool_call("write", key="b", value="2", call_id="tc_2")
    resp = _make_response(None, [tc1, tc2], "tool_calls")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is False
    # assistant + 2 tool results.
    assert len(msgs) == 3
    assert store.read("a")["value"] == "1"
    assert store.read("b")["value"] == "2"


# -- SDK-like object format --------------------------------------------------

class _FakeFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, tc_id: str, fn_name: str, arguments: str):
        self.id = tc_id
        self.function = _FakeFunction(fn_name, arguments)


class _FakeMessage:
    def __init__(self, content: str | None, tool_calls: list | None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, finish_reason: str, message: _FakeMessage):
        self.finish_reason = finish_reason
        self.message = message


class _FakeResponse:
    def __init__(self, choices: list):
        self.choices = choices


def test_handle_tool_call_sdk_object(store: SharedContextStore) -> None:
    tc = _FakeToolCall("tc_1", "shared_context", json.dumps({"action": "write", "key": "x", "value": "y"}))
    result = handle_tool_call(tc, store, participant="agent")
    assert result is not None
    body = json.loads(result["content"])
    assert body["version"] == 1


def test_process_response_sdk_object(store: SharedContextStore) -> None:
    tc = _FakeToolCall("tc_1", "shared_context", json.dumps({"action": "write", "key": "k", "value": "v"}))
    msg = _FakeMessage(content=None, tool_calls=[tc])
    choice = _FakeChoice(finish_reason="tool_calls", message=msg)
    resp = _FakeResponse(choices=[choice])

    msgs, done = process_response(resp, store, participant="agent")
    assert done is False
    assert len(msgs) == 2
    assert store.read("k")["value"] == "v"


def test_process_response_sdk_stop(store: SharedContextStore) -> None:
    msg = _FakeMessage(content="Done!", tool_calls=None)
    choice = _FakeChoice(finish_reason="stop", message=msg)
    resp = _FakeResponse(choices=[choice])

    msgs, done = process_response(resp, store, participant="agent")
    assert done is True
    assert msgs[0]["content"] == "Done!"

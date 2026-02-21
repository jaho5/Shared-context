"""Tests for the Anthropic integration module."""

import json

import pytest

from shared_context import SharedContextStore
from shared_context.anthropic import handle_tool_use, process_response, tool_definition


@pytest.fixture
def store() -> SharedContextStore:
    return SharedContextStore("test")


# -- tool_definition ---------------------------------------------------------

def test_tool_definition_is_anthropic_format() -> None:
    td = tool_definition()
    assert td["name"] == "shared_context"
    assert "input_schema" in td


# -- handle_tool_use (dict format) -------------------------------------------

def _make_tool_use(action: str, key: str = "", value: str = "", block_id: str = "tu_1") -> dict:
    input_data = {"action": action}
    if key:
        input_data["key"] = key
    if value:
        input_data["value"] = value
    return {
        "type": "tool_use",
        "id": block_id,
        "name": "shared_context",
        "input": input_data,
    }


def test_handle_write_and_read(store: SharedContextStore) -> None:
    block = _make_tool_use("write", key="foo", value="bar")
    result = handle_tool_use(block, store, participant="agent_a")
    assert result is not None
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == "tu_1"
    body = json.loads(result["content"])
    assert body["version"] == 1

    block2 = _make_tool_use("read", key="foo", block_id="tu_2")
    result2 = handle_tool_use(block2, store, participant="agent_a")
    body2 = json.loads(result2["content"])
    assert body2["value"] == "bar"


def test_handle_list_keys(store: SharedContextStore) -> None:
    store.write("x", "1", written_by="a")
    block = _make_tool_use("list_keys")
    result = handle_tool_use(block, store, participant="agent")
    body = json.loads(result["content"])
    assert len(body["keys"]) == 1


def test_handle_ignores_other_tools(store: SharedContextStore) -> None:
    block = {"type": "tool_use", "id": "tu_99", "name": "web_search", "input": {}}
    result = handle_tool_use(block, store, participant="agent")
    assert result is None


def test_handle_ignores_text_blocks(store: SharedContextStore) -> None:
    block = {"type": "text", "text": "hello"}
    result = handle_tool_use(block, store, participant="agent")
    assert result is None


def test_handle_error_returns_json(store: SharedContextStore) -> None:
    block = _make_tool_use("read", key="missing")
    result = handle_tool_use(block, store, participant="agent")
    body = json.loads(result["content"])
    assert body["error"] == "KEY_NOT_FOUND"


# -- process_response (dict format) ------------------------------------------

def _make_response(content: list, stop_reason: str) -> dict:
    return {"content": content, "stop_reason": stop_reason}


def test_process_response_end_turn(store: SharedContextStore) -> None:
    resp = _make_response([{"type": "text", "text": "Hello!"}], "end_turn")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is True
    assert len(msgs) == 1
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"][0]["text"] == "Hello!"


def test_process_response_tool_use(store: SharedContextStore) -> None:
    tu = _make_tool_use("write", key="a", value="b")
    resp = _make_response([tu], "tool_use")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is False
    # msgs[0] is assistant, msgs[1] is user with tool_result.
    assert len(msgs) == 2
    assert msgs[0]["role"] == "assistant"
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"][0]["type"] == "tool_result"
    body = json.loads(msgs[1]["content"][0]["content"])
    assert body["version"] == 1


def test_process_response_mixed_content(store: SharedContextStore) -> None:
    content = [
        {"type": "text", "text": "Let me check..."},
        _make_tool_use("write", key="k", value="v"),
    ]
    resp = _make_response(content, "tool_use")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is False
    # Assistant message has both blocks.
    assert len(msgs[0]["content"]) == 2
    assert msgs[0]["content"][0]["type"] == "text"
    assert msgs[0]["content"][1]["type"] == "tool_use"


def test_process_response_multiple_tool_uses(store: SharedContextStore) -> None:
    tu1 = _make_tool_use("write", key="a", value="1", block_id="tu_1")
    tu2 = _make_tool_use("write", key="b", value="2", block_id="tu_2")
    resp = _make_response([tu1, tu2], "tool_use")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is False
    # User message has 2 tool_result blocks.
    assert len(msgs[1]["content"]) == 2
    assert store.read("a")["value"] == "1"
    assert store.read("b")["value"] == "2"


# -- SDK-like object format --------------------------------------------------

class _FakeTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    def __init__(self, block_id: str, name: str, input_data: dict):
        self.type = "tool_use"
        self.id = block_id
        self.name = name
        self.input = input_data


class _FakeMessageResponse:
    def __init__(self, content: list, stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


def test_handle_tool_use_sdk_object(store: SharedContextStore) -> None:
    block = _FakeToolUseBlock("tu_1", "shared_context", {"action": "write", "key": "x", "value": "y"})
    result = handle_tool_use(block, store, participant="agent")
    assert result is not None
    body = json.loads(result["content"])
    assert body["version"] == 1


def test_process_response_sdk_end_turn(store: SharedContextStore) -> None:
    resp = _FakeMessageResponse([_FakeTextBlock("Done!")], "end_turn")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is True
    assert msgs[0]["content"][0]["text"] == "Done!"


def test_process_response_sdk_tool_use(store: SharedContextStore) -> None:
    tu = _FakeToolUseBlock("tu_1", "shared_context", {"action": "write", "key": "k", "value": "v"})
    resp = _FakeMessageResponse([tu], "tool_use")
    msgs, done = process_response(resp, store, participant="agent")
    assert done is False
    assert store.read("k")["value"] == "v"

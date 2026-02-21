"""Tests for subagent OpenAI runner integration."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from subagent import AgentConfig
from subagent.openai import create_runner


# -- helpers -----------------------------------------------------------------

def _make_config(**overrides) -> AgentConfig:
    defaults = {
        "name": "researcher",
        "description": "Test agent",
        "system_prompt": "You are a test agent.",
        "tools": (),
        "model": "test-model",
        "max_turns": 10,
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _openai_response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    """Build a dict-format OpenAI chat completion response."""
    message: dict[str, Any] = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": message,
            }
        ]
    }


def _tool_call(
    call_id: str,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


# -- tests -------------------------------------------------------------------

class TestOpenAIRunner:
    def test_simple_text_response(self) -> None:
        """Agent responds with text on the first turn."""
        client = MagicMock()
        client.chat.completions.create.return_value = _openai_response(
            content="The answer is 42."
        )

        runner = create_runner(
            client=client,
            tool_definitions={},
        )
        config = _make_config()
        result, turns = runner(config, "What is the answer?", "subagent:researcher:t_01")

        assert result == "The answer is 42."
        assert turns == 1
        client.chat.completions.create.assert_called_once()

    def test_tool_call_then_response(self) -> None:
        """Agent calls a tool, then responds with text."""
        client = MagicMock()

        client.chat.completions.create.side_effect = [
            _openai_response(
                tool_calls=[_tool_call("tc_1", "search", {"query": "latency"})],
                finish_reason="tool_calls",
            ),
            _openai_response(content="Found the issue: latency spike at 14:00."),
        ]

        search_handler = MagicMock(return_value={"results": ["log entry 1"]})

        runner = create_runner(
            client=client,
            tool_definitions={
                "search": {
                    "type": "function",
                    "function": {"name": "search", "parameters": {}},
                }
            },
            tool_handlers={"search": search_handler},
        )
        config = _make_config(tools=("search",))
        result, turns = runner(config, "Investigate latency", "subagent:researcher:t_01")

        assert "Found the issue" in result
        assert turns == 2
        search_handler.assert_called_once_with({"query": "latency"})

    def test_max_turns_exceeded(self) -> None:
        """Agent keeps calling tools until max_turns is reached."""
        client = MagicMock()
        client.chat.completions.create.return_value = _openai_response(
            tool_calls=[_tool_call("tc_1", "search", {"query": "x"})],
            finish_reason="tool_calls",
        )

        runner = create_runner(
            client=client,
            tool_definitions={
                "search": {
                    "type": "function",
                    "function": {"name": "search", "parameters": {}},
                }
            },
            tool_handlers={"search": lambda req: {"result": "data"}},
        )
        config = _make_config(tools=("search",), max_turns=3)

        with pytest.raises(Exception, match="Max turns exceeded"):
            runner(config, "Loop forever", "subagent:researcher:t_01")

        assert client.chat.completions.create.call_count == 3

    def test_shared_context_integration(self) -> None:
        """Agent uses shared_context tool with correct participant identity."""
        from shared_context import SharedContextStore

        store = SharedContextStore("test-session")

        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _openai_response(
                tool_calls=[
                    _tool_call(
                        "tc_1",
                        "shared_context",
                        {"action": "write", "key": "findings", "value": "root cause found"},
                    )
                ],
                finish_reason="tool_calls",
            ),
            _openai_response(content="Wrote findings to shared context."),
        ]

        runner = create_runner(
            client=client,
            tool_definitions={},
            shared_context_store=store,
        )
        config = _make_config(tools=("shared_context",))
        result, turns = runner(config, "Investigate", "subagent:researcher:t_01")

        assert "Wrote findings" in result
        entry = store.read("findings")
        assert entry["value"] == "root cause found"
        assert entry["written_by"] == "subagent:researcher:t_01"

    def test_system_prompt_in_messages(self) -> None:
        """The system prompt + suffix is sent as the first message."""
        client = MagicMock()
        client.chat.completions.create.return_value = _openai_response(content="ok")

        runner = create_runner(client=client, tool_definitions={})
        config = _make_config(system_prompt="Be concise.")
        runner(config, "test", "subagent:x:t_01")

        call_kwargs = client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "Be concise." in messages[0]["content"]
        assert "subagent" in messages[0]["content"].lower()

    def test_no_tools_omits_tools_param(self) -> None:
        """When the agent has no tools, the tools param is omitted."""
        client = MagicMock()
        client.chat.completions.create.return_value = _openai_response(
            content="no tools needed"
        )

        runner = create_runner(client=client, tool_definitions={})
        config = _make_config(tools=())
        runner(config, "just chat", "subagent:x:t_01")

        call_kwargs = client.chat.completions.create.call_args[1]
        assert "tools" not in call_kwargs

    def test_multiple_tool_calls_in_one_turn(self) -> None:
        """Agent calls multiple tools in a single response."""
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _openai_response(
                tool_calls=[
                    _tool_call("tc_1", "search", {"query": "cpu"}),
                    _tool_call("tc_2", "search", {"query": "memory"}),
                ],
                finish_reason="tool_calls",
            ),
            _openai_response(content="CPU and memory both look fine."),
        ]

        call_count = 0
        def search_handler(req):
            nonlocal call_count
            call_count += 1
            return {"result": f"data_{call_count}"}

        runner = create_runner(
            client=client,
            tool_definitions={
                "search": {
                    "type": "function",
                    "function": {"name": "search", "parameters": {}},
                }
            },
            tool_handlers={"search": search_handler},
        )
        config = _make_config(tools=("search",))
        result, turns = runner(config, "Check resources", "subagent:x:t_01")

        assert call_count == 2
        assert turns == 2

    def test_model_kwarg_from_config(self) -> None:
        """The model from agent config is passed to the API."""
        client = MagicMock()
        client.chat.completions.create.return_value = _openai_response(content="ok")

        runner = create_runner(client=client, tool_definitions={})
        config = _make_config(model="gpt-4o")
        runner(config, "test", "subagent:x:t_01")

        call_kwargs = client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o"

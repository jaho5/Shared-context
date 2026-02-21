"""Tests for subagent Anthropic runner integration."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from subagent import AgentConfig
from subagent.anthropic import create_runner


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


def _anthropic_response(
    content: list[dict[str, Any]],
    stop_reason: str = "end_turn",
) -> dict[str, Any]:
    """Build a dict-format Anthropic messages response."""
    return {
        "stop_reason": stop_reason,
        "content": content,
    }


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _tool_use_block(
    tool_id: str,
    name: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": tool_id,
        "name": name,
        "input": input_data,
    }


# -- tests -------------------------------------------------------------------

class TestAnthropicRunner:
    def test_simple_text_response(self) -> None:
        """Agent responds with text on the first turn."""
        client = MagicMock()
        client.messages.create.return_value = _anthropic_response(
            [_text_block("The answer is 42.")]
        )

        runner = create_runner(
            client=client,
            tool_definitions={},
        )
        config = _make_config()
        result, turns = runner(config, "What is the answer?", "subagent:researcher:t_01")

        assert result == "The answer is 42."
        assert turns == 1
        client.messages.create.assert_called_once()

    def test_tool_call_then_response(self) -> None:
        """Agent calls a tool, then responds with text."""
        client = MagicMock()

        # First call: model uses a tool.
        client.messages.create.side_effect = [
            _anthropic_response(
                [_tool_use_block("tu_1", "search", {"query": "latency"})],
                stop_reason="tool_use",
            ),
            _anthropic_response(
                [_text_block("Found the issue: latency spike at 14:00.")]
            ),
        ]

        search_handler = MagicMock(return_value={"results": ["log entry 1"]})

        runner = create_runner(
            client=client,
            tool_definitions={"search": {"name": "search", "input_schema": {}}},
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
        # Always return a tool call, never end_turn.
        client.messages.create.return_value = _anthropic_response(
            [_tool_use_block("tu_1", "search", {"query": "x"})],
            stop_reason="tool_use",
        )

        runner = create_runner(
            client=client,
            tool_definitions={"search": {"name": "search", "input_schema": {}}},
            tool_handlers={"search": lambda req: {"result": "data"}},
        )
        config = _make_config(tools=("search",), max_turns=3)

        with pytest.raises(Exception, match="Max turns exceeded"):
            runner(config, "Loop forever", "subagent:researcher:t_01")

        assert client.messages.create.call_count == 3

    def test_shared_context_integration(self) -> None:
        """Agent uses shared_context tool with correct participant identity."""
        from shared_context import SharedContextStore

        store = SharedContextStore("test-session")

        client = MagicMock()
        client.messages.create.side_effect = [
            _anthropic_response(
                [_tool_use_block(
                    "tu_1",
                    "shared_context",
                    {"action": "write", "key": "findings", "value": "root cause found"},
                )],
                stop_reason="tool_use",
            ),
            _anthropic_response(
                [_text_block("Wrote findings to shared context.")]
            ),
        ]

        runner = create_runner(
            client=client,
            tool_definitions={},
            shared_context_store=store,
        )
        config = _make_config(tools=("shared_context",))
        result, turns = runner(config, "Investigate", "subagent:researcher:t_01")

        assert "Wrote findings" in result
        # Verify the store was written to with the correct participant.
        entry = store.read("findings")
        assert entry["value"] == "root cause found"
        assert entry["written_by"] == "subagent:researcher:t_01"

    def test_system_prompt_has_suffix(self) -> None:
        """The subagent suffix is appended to the system prompt."""
        client = MagicMock()
        client.messages.create.return_value = _anthropic_response(
            [_text_block("ok")]
        )

        runner = create_runner(client=client, tool_definitions={})
        config = _make_config(system_prompt="Be concise.")
        runner(config, "test", "subagent:x:t_01")

        call_kwargs = client.messages.create.call_args[1]
        assert "Be concise." in call_kwargs["system"]
        assert "subagent" in call_kwargs["system"].lower()

    def test_no_tools_omits_tools_param(self) -> None:
        """When the agent has no tools, the tools param is omitted."""
        client = MagicMock()
        client.messages.create.return_value = _anthropic_response(
            [_text_block("no tools needed")]
        )

        runner = create_runner(client=client, tool_definitions={})
        config = _make_config(tools=())
        runner(config, "just chat", "subagent:x:t_01")

        call_kwargs = client.messages.create.call_args[1]
        assert "tools" not in call_kwargs

    def test_multiple_tool_calls_in_one_turn(self) -> None:
        """Agent calls multiple tools in a single response."""
        client = MagicMock()
        client.messages.create.side_effect = [
            _anthropic_response(
                [
                    _tool_use_block("tu_1", "search", {"query": "cpu"}),
                    _tool_use_block("tu_2", "search", {"query": "memory"}),
                ],
                stop_reason="tool_use",
            ),
            _anthropic_response(
                [_text_block("CPU and memory both look fine.")]
            ),
        ]

        call_count = 0
        def search_handler(req):
            nonlocal call_count
            call_count += 1
            return {"result": f"data_{call_count}"}

        runner = create_runner(
            client=client,
            tool_definitions={"search": {"name": "search", "input_schema": {}}},
            tool_handlers={"search": search_handler},
        )
        config = _make_config(tools=("search",))
        result, turns = runner(config, "Check resources", "subagent:x:t_01")

        assert call_count == 2
        assert turns == 2

    def test_model_kwarg_from_config(self) -> None:
        """The model from agent config is passed to the API."""
        client = MagicMock()
        client.messages.create.return_value = _anthropic_response(
            [_text_block("ok")]
        )

        runner = create_runner(client=client, tool_definitions={})
        config = _make_config(model="claude-sonnet-4-20250514")
        runner(config, "test", "subagent:x:t_01")

        call_kwargs = client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"

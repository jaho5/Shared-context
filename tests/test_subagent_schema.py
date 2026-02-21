"""Tests for subagent tool schema definitions."""

from subagent.schema import (
    PARAMETERS_SCHEMA,
    TOOL_NAME,
    anthropic_tool,
    openai_tool,
)


def test_openai_tool_structure() -> None:
    tool = openai_tool()
    assert tool["type"] == "function"
    fn = tool["function"]
    assert fn["name"] == TOOL_NAME
    assert "description" in fn
    assert fn["parameters"]["type"] == "object"
    props = fn["parameters"]["properties"]
    assert "action" in props
    assert "agent" in props
    assert "task" in props
    assert "task_id" in props
    assert "name" in props
    assert "system_prompt" in props
    assert fn["parameters"]["required"] == ["action"]


def test_openai_tool_custom_name() -> None:
    tool = openai_tool(name="my_subagent")
    assert tool["function"]["name"] == "my_subagent"


def test_openai_tool_strict_mode() -> None:
    tool = openai_tool(strict=True)
    assert tool["function"]["strict"] is True


def test_openai_tool_no_strict_by_default() -> None:
    tool = openai_tool()
    assert "strict" not in tool["function"]


def test_anthropic_tool_structure() -> None:
    tool = anthropic_tool()
    assert tool["name"] == TOOL_NAME
    assert "description" in tool
    schema = tool["input_schema"]
    assert schema["type"] == "object"
    props = schema["properties"]
    assert "action" in props
    assert "agent" in props
    assert "task" in props
    assert "task_id" in props
    assert "name" in props
    assert "system_prompt" in props
    assert schema["required"] == ["action"]


def test_anthropic_tool_custom_name() -> None:
    tool = anthropic_tool(name="my_subagent")
    assert tool["name"] == "my_subagent"


def test_schemas_are_deep_copies() -> None:
    """Mutating a returned schema must not affect future calls."""
    t1 = openai_tool()
    t1["function"]["parameters"]["properties"]["action"]["extra"] = True
    t2 = openai_tool()
    assert "extra" not in t2["function"]["parameters"]["properties"]["action"]

"""Tests for tool schema definitions."""

from shared_context.schema import (
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
    assert "action" in fn["parameters"]["properties"]
    assert "key" in fn["parameters"]["properties"]
    assert "value" in fn["parameters"]["properties"]
    assert fn["parameters"]["required"] == ["action"]


def test_openai_tool_custom_name() -> None:
    tool = openai_tool(name="my_ctx")
    assert tool["function"]["name"] == "my_ctx"


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
    assert tool["input_schema"]["type"] == "object"
    assert "action" in tool["input_schema"]["properties"]
    assert "key" in tool["input_schema"]["properties"]
    assert "value" in tool["input_schema"]["properties"]
    assert tool["input_schema"]["required"] == ["action"]


def test_anthropic_tool_custom_name() -> None:
    tool = anthropic_tool(name="my_ctx")
    assert tool["name"] == "my_ctx"


def test_schemas_are_deep_copies() -> None:
    """Mutating a returned schema must not affect future calls."""
    t1 = openai_tool()
    t1["function"]["parameters"]["properties"]["action"]["extra"] = True
    t2 = openai_tool()
    assert "extra" not in t2["function"]["parameters"]["properties"]["action"]

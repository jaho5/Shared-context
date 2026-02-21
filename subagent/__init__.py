"""Subagent — reference implementation of the subagent tool spec."""

from subagent.errors import (
    AgentAlreadyExistsError,
    AgentNotFoundError,
    InvalidAgentNameError,
    InvalidToolError,
    MaxTasksExceededError,
    PromptTooLargeError,
    SubagentError,
    TaskNotFoundError,
    TaskNotReadyError,
    TaskTooLargeError,
)
from subagent.registry import AgentConfig, AgentRegistry
from subagent.schema import anthropic_tool, openai_tool
from subagent.task import Task, TaskManager
from subagent.tool import SubagentTool

__all__ = [
    "SubagentTool",
    "AgentConfig",
    "AgentRegistry",
    "Task",
    "TaskManager",
    "SubagentError",
    "AgentNotFoundError",
    "AgentAlreadyExistsError",
    "TaskNotFoundError",
    "TaskNotReadyError",
    "TaskTooLargeError",
    "MaxTasksExceededError",
    "InvalidAgentNameError",
    "InvalidToolError",
    "PromptTooLargeError",
    "openai_tool",
    "anthropic_tool",
]

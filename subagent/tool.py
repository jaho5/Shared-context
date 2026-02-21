"""Subagent tool — main entry point (spec sections 3, 4, 8).

This module provides :class:`SubagentTool`, which dispatches orchestrator
tool calls to the agent registry and task manager, and runs subagent loops
in background threads.

Usage::

    from subagent import SubagentTool, AgentConfig

    def my_runner(config, task_string, participant):
        # Run a full agent loop, return (response_text, turns_used)
        ...

    tool = SubagentTool(runner=my_runner, available_tools={"search", "shared_context"})
    tool.register(AgentConfig(
        name="researcher",
        description="Investigates issues",
        system_prompt="You are a researcher...",
        tools=("search", "shared_context"),
        model="claude-sonnet-4-20250514",
    ))

    # In the orchestrator's agent loop:
    result = tool.handle({"action": "spawn", "agent": "researcher", "task": "..."})
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from subagent.errors import SubagentError, TaskTooLargeError
from subagent.registry import AgentConfig, AgentRegistry
from subagent.task import Task, TaskManager

# Spec §4.1 — result size limit.
_MAX_RESULT_TOKENS = 1000
# Spec §4.2 — task string size limit.
_MAX_TASK_TOKENS = 1000
# Spec §4.3 — max concurrent tasks.
_DEFAULT_MAX_CONCURRENT = 5
# Truncation notice appended when result exceeds limit (spec §4.1).
_TRUNCATION_NOTICE = "\n[truncated — full response exceeded 1000 token limit]"

_VALID_ACTIONS = {"list_agents", "define", "spawn", "status", "collect"}

# Type for the runner function injected by the application.
# Signature: (config, task_string, participant) -> (response_text, turns_used)
RunnerFn = Callable[[AgentConfig, str, str], tuple[str, int]]


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _truncate_result(text: str) -> str:
    """Truncate result to ~1000 tokens if needed (spec §4.1)."""
    if _estimate_tokens(text) <= _MAX_RESULT_TOKENS:
        return text
    # Truncate at approximate character boundary.
    max_chars = _MAX_RESULT_TOKENS * 4
    return text[:max_chars] + _TRUNCATION_NOTICE


class SubagentTool:
    """Dispatch orchestrator tool calls and manage subagent execution.

    Parameters
    ----------
    runner:
        A callable that runs a full agent loop.  Signature:
        ``(config: AgentConfig, task: str, participant: str) -> (result: str, turns_used: int)``.
        The runner is responsible for model calls, tool execution, and
        turn counting.  It should raise on unrecoverable errors.
    available_tools:
        Set of tool names registered in the application.  Used to validate
        ``define`` requests.  If ``None``, tool validation is skipped.
    max_concurrent:
        Maximum number of simultaneously running tasks (spec §4.3).
    """

    def __init__(
        self,
        runner: RunnerFn,
        *,
        available_tools: set[str] | None = None,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT,
    ) -> None:
        self._registry = AgentRegistry(available_tools=available_tools)
        self._tasks = TaskManager(max_concurrent=max_concurrent)
        self._runner = runner
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._lock = threading.RLock()

    # -- public API ----------------------------------------------------------

    def register(self, config: AgentConfig) -> None:
        """Pre-register an agent (application setup, before session starts)."""
        self._registry.register(config)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch an orchestrator tool call (spec §3).

        Parameters
        ----------
        request:
            The JSON body from the orchestrator.  Must contain ``"action"``.

        Returns
        -------
        dict
            JSON-serializable response, or an error dict.
        """
        action = request.get("action")
        if action not in _VALID_ACTIONS:
            return {
                "error": "INVALID_ACTION",
                "message": f"Unknown action: {action!r}. Valid: {sorted(_VALID_ACTIONS)}",
            }

        try:
            if action == "list_agents":
                return self._list_agents()
            if action == "define":
                return self._define(request)
            if action == "spawn":
                return self._spawn(request)
            if action == "status":
                return self._status(request)
            if action == "collect":
                return self._collect(request)
        except SubagentError as exc:
            return exc.to_dict()

        return {"error": "INTERNAL", "message": "Unexpected state."}  # pragma: no cover

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the thread pool.  Call when the session ends."""
        self._executor.shutdown(wait=wait)

    # -- actions -------------------------------------------------------------

    def _list_agents(self) -> dict[str, Any]:
        """Spec §3.1."""
        return {"agents": self._registry.list_agents()}

    def _define(self, request: dict[str, Any]) -> dict[str, Any]:
        """Spec §3.2."""
        config = self._registry.define(
            name=request.get("name", ""),
            description=request.get("description", ""),
            system_prompt=request.get("system_prompt", ""),
            tools=request.get("tools"),
            model=request.get("model", ""),
            max_turns=request.get("max_turns", 10),
        )
        return {
            "defined": config.name,
            "description": config.description,
        }

    def _spawn(self, request: dict[str, Any]) -> dict[str, Any]:
        """Spec §3.3."""
        agent_name = request.get("agent", "")
        task_string = request.get("task", "")

        # Validate task string size (spec §4.2).
        task_tokens = _estimate_tokens(task_string)
        if task_tokens > _MAX_TASK_TOKENS:
            raise TaskTooLargeError(
                f"Task string is ~{task_tokens} tokens, max is {_MAX_TASK_TOKENS}."
            )

        # Validate agent exists.
        config = self._registry.get(agent_name)

        # Create task (validates concurrent limit).
        task = self._tasks.create(agent_name, task_string)

        # Capture response before submitting — the runner may finish
        # before to_spawn_response() would otherwise execute.
        response = task.to_spawn_response()

        # Submit to thread pool.
        self._executor.submit(self._execute_task, task, config)

        return response

    def _status(self, request: dict[str, Any]) -> dict[str, Any]:
        """Spec §3.4."""
        task_id = request.get("task_id", "")
        task = self._tasks.get(task_id)
        return task.to_status_response()

    def _collect(self, request: dict[str, Any]) -> dict[str, Any]:
        """Spec §3.5."""
        task_id = request.get("task_id", "")
        task = self._tasks.collect(task_id)
        return task.to_collect_response()

    # -- execution backend (spec §8.1) ---------------------------------------

    def _execute_task(self, task: Task, config: AgentConfig) -> None:
        """Run in a background thread.  Updates the task in place."""
        participant = f"subagent:{config.name}:{task.task_id}"
        try:
            result_text, turns_used = self._runner(config, task.task, participant)
            with self._lock:
                task.result = _truncate_result(result_text)
                task.turns_used = turns_used
                task.status = "completed"
                task.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            with self._lock:
                task.error = str(exc)
                task.turns_used = getattr(exc, "turns_used", 0)
                task.status = "failed"
                task.completed_at = datetime.now(timezone.utc)

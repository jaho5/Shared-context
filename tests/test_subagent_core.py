"""Tests for subagent registry, task manager, and tool handler."""

from __future__ import annotations

import time

import pytest

from subagent import (
    AgentAlreadyExistsError,
    AgentConfig,
    AgentNotFoundError,
    AgentRegistry,
    InvalidAgentNameError,
    InvalidToolError,
    MaxTasksExceededError,
    PromptTooLargeError,
    SubagentTool,
    Task,
    TaskManager,
    TaskNotFoundError,
    TaskNotReadyError,
    TaskTooLargeError,
)


# -- helpers -----------------------------------------------------------------

def _noop_runner(config: AgentConfig, task: str, participant: str) -> tuple[str, int]:
    """Runner that returns immediately with a canned response."""
    return f"done: {task}", 1


def _slow_runner(config: AgentConfig, task: str, participant: str) -> tuple[str, int]:
    """Runner that takes a moment (for concurrency tests)."""
    time.sleep(0.1)
    return f"done: {task}", 3


def _failing_runner(config: AgentConfig, task: str, participant: str) -> tuple[str, int]:
    raise RuntimeError("model exploded")


def _make_config(name: str = "researcher", **overrides) -> AgentConfig:
    defaults = {
        "name": name,
        "description": "A test agent",
        "system_prompt": "You are a test agent.",
        "tools": (),
        "model": "test-model",
        "max_turns": 10,
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


# -- fixtures ----------------------------------------------------------------

@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry(available_tools={"search", "shared_context"})


@pytest.fixture
def task_manager() -> TaskManager:
    return TaskManager(max_concurrent=3)


@pytest.fixture
def tool() -> SubagentTool:
    t = SubagentTool(
        runner=_noop_runner,
        available_tools={"search", "shared_context"},
        max_concurrent=5,
    )
    t.register(_make_config("researcher"))
    t.register(_make_config("writer", description="Writes docs"))
    return t


# ===========================================================================
# AgentRegistry
# ===========================================================================

class TestAgentRegistry:
    def test_register_and_get(self, registry: AgentRegistry) -> None:
        config = _make_config()
        registry.register(config)
        assert registry.get("researcher").name == "researcher"

    def test_register_duplicate_rejected(self, registry: AgentRegistry) -> None:
        registry.register(_make_config())
        with pytest.raises(AgentAlreadyExistsError):
            registry.register(_make_config())

    def test_get_missing_raises(self, registry: AgentRegistry) -> None:
        with pytest.raises(AgentNotFoundError):
            registry.get("nonexistent")

    def test_list_agents_empty(self, registry: AgentRegistry) -> None:
        assert registry.list_agents() == []

    def test_list_agents_returns_summaries(self, registry: AgentRegistry) -> None:
        registry.register(_make_config("a"))
        registry.register(_make_config("b"))
        agents = registry.list_agents()
        names = {a["name"] for a in agents}
        assert names == {"a", "b"}
        # Summaries should not contain system_prompt.
        for a in agents:
            assert "system_prompt" not in a

    # -- define --------------------------------------------------------------

    def test_define_creates_agent(self, registry: AgentRegistry) -> None:
        config = registry.define(
            name="analyst",
            description="Analyzes data",
            system_prompt="You analyze data.",
            tools=["search"],
        )
        assert config.name == "analyst"
        assert registry.get("analyst").description == "Analyzes data"

    def test_define_duplicate_rejected(self, registry: AgentRegistry) -> None:
        registry.define(name="a", description="x", system_prompt="y")
        with pytest.raises(AgentAlreadyExistsError):
            registry.define(name="a", description="x", system_prompt="y")

    def test_define_strips_subagent_tool(self, registry: AgentRegistry) -> None:
        config = registry.define(
            name="sneaky",
            description="Tries to nest",
            system_prompt="...",
            tools=["search", "subagent"],
        )
        assert "subagent" not in config.tools
        assert "search" in config.tools

    def test_define_invalid_tool_rejected(self, registry: AgentRegistry) -> None:
        with pytest.raises(InvalidToolError):
            registry.define(
                name="bad",
                description="x",
                system_prompt="y",
                tools=["nonexistent_tool"],
            )

    def test_define_prompt_too_large(self, registry: AgentRegistry) -> None:
        big_prompt = "x" * 16100  # ~4025 tokens
        with pytest.raises(PromptTooLargeError):
            registry.define(
                name="verbose",
                description="x",
                system_prompt=big_prompt,
            )

    def test_define_clamps_max_turns(self, registry: AgentRegistry) -> None:
        config = registry.define(
            name="capped",
            description="x",
            system_prompt="y",
            max_turns=100,
        )
        assert config.max_turns == 25  # Capped at absolute max.

    def test_define_defaults(self, registry: AgentRegistry) -> None:
        config = registry.define(
            name="minimal",
            description="x",
            system_prompt="y",
        )
        assert config.tools == ()
        assert config.max_turns == 10
        assert config.model == ""

    # -- name validation -----------------------------------------------------

    @pytest.mark.parametrize("bad_name", [
        "",
        "HAS_UPPER",
        "has.dot",
        "has/slash",
        "has space",
        "a" * 65,
    ])
    def test_invalid_name_rejected(self, registry: AgentRegistry, bad_name: str) -> None:
        with pytest.raises(InvalidAgentNameError):
            registry.register(_make_config(bad_name))

    @pytest.mark.parametrize("good_name", [
        "a",
        "researcher",
        "my-agent",
        "agent_v2",
        "a" * 64,
    ])
    def test_valid_name_accepted(self, registry: AgentRegistry, good_name: str) -> None:
        registry.register(_make_config(good_name))
        assert registry.get(good_name).name == good_name


# ===========================================================================
# TaskManager
# ===========================================================================

class TestTaskManager:
    def test_create_and_get(self, task_manager: TaskManager) -> None:
        task = task_manager.create("researcher", "investigate")
        assert task.task_id == "t_01"
        assert task.status == "running"
        assert task_manager.get("t_01") is task

    def test_sequential_ids(self, task_manager: TaskManager) -> None:
        t1 = task_manager.create("a", "task1")
        t2 = task_manager.create("b", "task2")
        assert t1.task_id == "t_01"
        assert t2.task_id == "t_02"

    def test_get_missing_raises(self, task_manager: TaskManager) -> None:
        with pytest.raises(TaskNotFoundError):
            task_manager.get("t_99")

    def test_max_concurrent_enforced(self, task_manager: TaskManager) -> None:
        for i in range(3):
            task_manager.create("a", f"task{i}")
        with pytest.raises(MaxTasksExceededError):
            task_manager.create("a", "one too many")

    def test_completed_tasks_dont_count_toward_limit(self, task_manager: TaskManager) -> None:
        for i in range(3):
            task_manager.create("a", f"task{i}")
        # Complete one task.
        task_manager.get("t_01").status = "completed"
        # Should now be able to create another.
        t4 = task_manager.create("a", "after completion")
        assert t4.task_id == "t_04"

    def test_collect_completed(self, task_manager: TaskManager) -> None:
        task = task_manager.create("a", "t")
        task.status = "completed"
        task.result = "done"
        collected = task_manager.collect("t_01")
        assert collected.result == "done"
        # Collected task is removed.
        with pytest.raises(TaskNotFoundError):
            task_manager.get("t_01")

    def test_collect_failed(self, task_manager: TaskManager) -> None:
        task = task_manager.create("a", "t")
        task.status = "failed"
        task.error = "boom"
        collected = task_manager.collect("t_01")
        assert collected.error == "boom"

    def test_collect_running_raises(self, task_manager: TaskManager) -> None:
        task_manager.create("a", "t")
        with pytest.raises(TaskNotReadyError):
            task_manager.collect("t_01")

    def test_collect_missing_raises(self, task_manager: TaskManager) -> None:
        with pytest.raises(TaskNotFoundError):
            task_manager.collect("t_99")

    def test_double_collect_raises(self, task_manager: TaskManager) -> None:
        task = task_manager.create("a", "t")
        task.status = "completed"
        task_manager.collect("t_01")
        with pytest.raises(TaskNotFoundError):
            task_manager.collect("t_01")


# ===========================================================================
# Task response methods
# ===========================================================================

class TestTaskResponses:
    def test_spawn_response(self) -> None:
        task = Task("t_01", "researcher", "investigate")
        resp = task.to_spawn_response()
        assert resp == {"task_id": "t_01", "agent": "researcher", "status": "running"}

    def test_status_response_running(self) -> None:
        task = Task("t_01", "researcher", "investigate")
        task.turns_used = 4
        resp = task.to_status_response()
        assert resp["status"] == "running"
        assert resp["turns_used"] == 4
        assert "error" not in resp

    def test_status_response_failed(self) -> None:
        task = Task("t_01", "researcher", "investigate")
        task.status = "failed"
        task.error = "boom"
        task.turns_used = 3
        resp = task.to_status_response()
        assert resp["error"] == "boom"

    def test_collect_response_completed(self) -> None:
        task = Task("t_01", "researcher", "investigate")
        task.status = "completed"
        task.result = "found it"
        task.turns_used = 5
        resp = task.to_collect_response()
        assert resp["result"] == "found it"
        assert "error" not in resp

    def test_collect_response_failed(self) -> None:
        task = Task("t_01", "researcher", "investigate")
        task.status = "failed"
        task.error = "timeout"
        resp = task.to_collect_response()
        assert resp["error"] == "timeout"
        assert "result" not in resp


# ===========================================================================
# SubagentTool (integration through handle())
# ===========================================================================

class TestSubagentTool:
    def test_list_agents(self, tool: SubagentTool) -> None:
        result = tool.handle({"action": "list_agents"})
        names = {a["name"] for a in result["agents"]}
        assert names == {"researcher", "writer"}

    def test_define_via_handle(self, tool: SubagentTool) -> None:
        result = tool.handle({
            "action": "define",
            "name": "analyst",
            "description": "Analyzes stuff",
            "system_prompt": "You analyze.",
            "tools": ["search"],
        })
        assert result["defined"] == "analyst"
        # Should appear in list_agents.
        agents = tool.handle({"action": "list_agents"})
        names = {a["name"] for a in agents["agents"]}
        assert "analyst" in names

    def test_spawn_and_collect(self, tool: SubagentTool) -> None:
        result = tool.handle({
            "action": "spawn",
            "agent": "researcher",
            "task": "investigate",
        })
        assert result["status"] == "running"
        task_id = result["task_id"]

        # Wait for the noop runner to finish.
        time.sleep(0.05)

        # Status should show completed.
        status = tool.handle({"action": "status", "task_id": task_id})
        assert status["status"] == "completed"

        # Collect.
        collected = tool.handle({"action": "collect", "task_id": task_id})
        assert collected["status"] == "completed"
        assert "done: investigate" in collected["result"]
        assert collected["turns_used"] == 1

        # Double collect should fail.
        err = tool.handle({"action": "collect", "task_id": task_id})
        assert err["error"] == "TASK_NOT_FOUND"

    def test_spawn_unknown_agent(self, tool: SubagentTool) -> None:
        result = tool.handle({
            "action": "spawn",
            "agent": "nonexistent",
            "task": "x",
        })
        assert result["error"] == "AGENT_NOT_FOUND"

    def test_spawn_task_too_large(self, tool: SubagentTool) -> None:
        big_task = "x" * 4100  # ~1025 tokens
        result = tool.handle({
            "action": "spawn",
            "agent": "researcher",
            "task": big_task,
        })
        assert result["error"] == "TASK_TOO_LARGE"

    def test_collect_running_task(self, tool: SubagentTool) -> None:
        # Use a slow runner to ensure the task is still running.
        slow_tool = SubagentTool(
            runner=_slow_runner,
            available_tools={"search"},
            max_concurrent=5,
        )
        slow_tool.register(_make_config("researcher"))
        result = slow_tool.handle({
            "action": "spawn",
            "agent": "researcher",
            "task": "slow task",
        })
        task_id = result["task_id"]

        # Immediately try to collect.
        err = slow_tool.handle({"action": "collect", "task_id": task_id})
        assert err["error"] == "TASK_NOT_READY"

        # Wait and collect successfully.
        time.sleep(0.2)
        collected = slow_tool.handle({"action": "collect", "task_id": task_id})
        assert collected["status"] == "completed"
        slow_tool.shutdown()

    def test_status_unknown_task(self, tool: SubagentTool) -> None:
        result = tool.handle({"action": "status", "task_id": "t_99"})
        assert result["error"] == "TASK_NOT_FOUND"

    def test_invalid_action(self, tool: SubagentTool) -> None:
        result = tool.handle({"action": "explode"})
        assert result["error"] == "INVALID_ACTION"

    def test_failed_task(self) -> None:
        fail_tool = SubagentTool(
            runner=_failing_runner,
            available_tools=set(),
            max_concurrent=5,
        )
        fail_tool.register(_make_config("broken"))
        result = fail_tool.handle({
            "action": "spawn",
            "agent": "broken",
            "task": "doomed",
        })
        task_id = result["task_id"]

        time.sleep(0.05)

        collected = fail_tool.handle({"action": "collect", "task_id": task_id})
        assert collected["status"] == "failed"
        assert "model exploded" in collected["error"]
        fail_tool.shutdown()

    def test_result_truncation(self) -> None:
        def big_runner(config, task, participant):
            return "x" * 8000, 2  # ~2000 tokens, exceeds 1000 limit

        trunc_tool = SubagentTool(runner=big_runner, max_concurrent=5)
        trunc_tool.register(_make_config("verbose"))
        result = trunc_tool.handle({
            "action": "spawn",
            "agent": "verbose",
            "task": "go",
        })
        time.sleep(0.05)

        collected = trunc_tool.handle({"action": "collect", "task_id": result["task_id"]})
        assert collected["status"] == "completed"
        assert "truncated" in collected["result"]
        assert len(collected["result"]) < 8000
        trunc_tool.shutdown()

    def test_parallel_spawn_and_collect(self, tool: SubagentTool) -> None:
        ids = []
        for i in range(3):
            result = tool.handle({
                "action": "spawn",
                "agent": "researcher",
                "task": f"task_{i}",
            })
            ids.append(result["task_id"])

        time.sleep(0.1)

        for task_id in ids:
            collected = tool.handle({"action": "collect", "task_id": task_id})
            assert collected["status"] == "completed"

    def test_define_and_spawn_dynamic_agent(self, tool: SubagentTool) -> None:
        tool.handle({
            "action": "define",
            "name": "custom",
            "description": "Custom agent",
            "system_prompt": "You are custom.",
            "tools": ["search"],
        })
        result = tool.handle({
            "action": "spawn",
            "agent": "custom",
            "task": "custom task",
        })
        assert result["status"] == "running"

        time.sleep(0.05)

        collected = tool.handle({"action": "collect", "task_id": result["task_id"]})
        assert collected["status"] == "completed"

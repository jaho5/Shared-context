"""Task model and task manager (spec sections 2.3, 2.4)."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from subagent.errors import (
    MaxTasksExceededError,
    TaskNotFoundError,
    TaskNotReadyError,
)

_DEFAULT_MAX_CONCURRENT = 5


class Task:
    """A single subagent invocation (spec section 2.3).

    Mutable — status, result, error, turns_used, and completed_at are
    updated by the execution backend as the subagent loop runs.
    """

    __slots__ = (
        "task_id",
        "agent",
        "task",
        "status",
        "result",
        "error",
        "turns_used",
        "created_at",
        "completed_at",
    )

    def __init__(self, task_id: str, agent: str, task: str) -> None:
        self.task_id = task_id
        self.agent = agent
        self.task = task
        self.status = "running"
        self.result: str | None = None
        self.error: str | None = None
        self.turns_used: int = 0
        self.created_at: datetime = datetime.now(timezone.utc)
        self.completed_at: datetime | None = None

    def to_spawn_response(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
        }

    def to_status_response(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
            "turns_used": self.turns_used,
        }
        if self.status == "failed" and self.error:
            d["error"] = self.error
        return d

    def to_collect_response(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
            "turns_used": self.turns_used,
        }
        if self.status == "completed":
            d["result"] = self.result
        elif self.status == "failed":
            d["error"] = self.error
        return d


class TaskManager:
    """Thread-safe tracker for active tasks (spec section 2.4).

    Tasks move through the lifecycle: running → completed | failed.
    Collected tasks are removed from tracking.
    """

    def __init__(self, *, max_concurrent: int = _DEFAULT_MAX_CONCURRENT) -> None:
        self._tasks: dict[str, Task] = {}
        self._counter = 0
        self._max_concurrent = max_concurrent
        self._lock = threading.RLock()

    def create(self, agent: str, task: str) -> Task:
        """Create a new task and add it to tracking.

        Raises :class:`MaxTasksExceededError` if the concurrent limit is hit.
        """
        with self._lock:
            running = sum(1 for t in self._tasks.values() if t.status == "running")
            if running >= self._max_concurrent:
                raise MaxTasksExceededError(
                    f"Maximum concurrent tasks ({self._max_concurrent}) reached."
                )
            self._counter += 1
            task_id = f"t_{self._counter:02d}"
            t = Task(task_id, agent, task)
            self._tasks[task_id] = t
            return t

    def get(self, task_id: str) -> Task:
        """Look up a task. Raises :class:`TaskNotFoundError`."""
        with self._lock:
            t = self._tasks.get(task_id)
        if t is None:
            raise TaskNotFoundError(
                f"Unknown or already-collected task: {task_id!r}"
            )
        return t

    def collect(self, task_id: str) -> Task:
        """Retrieve a completed/failed task and remove it from tracking.

        Raises :class:`TaskNotReadyError` if still running.
        Raises :class:`TaskNotFoundError` if unknown or already collected.
        """
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                raise TaskNotFoundError(
                    f"Unknown or already-collected task: {task_id!r}"
                )
            if t.status == "running":
                raise TaskNotReadyError(
                    f"Task {task_id!r} is still running (turns_used={t.turns_used})."
                )
            del self._tasks[task_id]
            return t

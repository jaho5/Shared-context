"""Agent configuration and registry (spec sections 2.1, 2.2)."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from subagent.errors import (
    AgentAlreadyExistsError,
    AgentNotFoundError,
    InvalidAgentNameError,
    InvalidToolError,
    PromptTooLargeError,
)

_NAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")
_MAX_NAME_LENGTH = 64
_MAX_PROMPT_TOKENS = 4000
_DEFAULT_MAX_TURNS = 10
_ABSOLUTE_MAX_TURNS = 25


def _estimate_tokens(text: str) -> int:
    """Approximate token count: len(text) / 4 (same heuristic as shared context)."""
    return max(1, len(text) // 4)


def _validate_agent_name(name: str) -> None:
    """Spec section 4.6 — lowercase alphanumeric + underscores + hyphens, max 64 chars."""
    if not name or len(name) > _MAX_NAME_LENGTH:
        raise InvalidAgentNameError(
            f"Agent name must be 1-{_MAX_NAME_LENGTH} characters, got {len(name)}."
        )
    if not _NAME_PATTERN.match(name):
        raise InvalidAgentNameError(
            f"Agent name must match [a-z0-9_-]+, got: {name!r}"
        )


@dataclass(frozen=True)
class AgentConfig:
    """Immutable configuration for a specialist agent (spec section 2.2).

    Parameters
    ----------
    name:
        Unique identifier. Lowercase alphanumeric + underscores + hyphens.
    description:
        One-line purpose, shown in list_agents.
    system_prompt:
        Instructions for the subagent.
    tools:
        Tool names available to the subagent. References the application
        tool registry. The ``subagent`` tool is never included.
    model:
        Model identifier (e.g. ``"claude-sonnet-4-20250514"``).
    max_turns:
        Maximum agent loop iterations. Default 10, max 25.
    """

    name: str
    description: str
    system_prompt: str
    tools: tuple[str, ...] = ()
    model: str = ""
    max_turns: int = _DEFAULT_MAX_TURNS

    def to_summary(self) -> dict[str, Any]:
        """Return the dict shown in list_agents responses."""
        return {
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "max_turns": self.max_turns,
            "tools": list(self.tools),
        }


class AgentRegistry:
    """Thread-safe registry of agent configurations (spec section 2.1).

    Holds both pre-registered agents (added via :meth:`register`) and
    dynamically defined agents (added via the ``define`` action at runtime).
    All agents are session-scoped — they exist only for the lifetime of
    this registry instance.
    """

    def __init__(self, *, available_tools: set[str] | None = None) -> None:
        self._agents: dict[str, AgentConfig] = {}
        self._available_tools = available_tools or set()
        self._lock = threading.RLock()

    def register(self, config: AgentConfig) -> None:
        """Pre-register an agent configuration (application setup).

        Raises :class:`AgentAlreadyExistsError` if the name is taken.
        """
        _validate_agent_name(config.name)
        with self._lock:
            if config.name in self._agents:
                raise AgentAlreadyExistsError(
                    f"Agent already registered: {config.name!r}"
                )
            self._agents[config.name] = config

    def define(
        self,
        *,
        name: str,
        description: str,
        system_prompt: str,
        tools: list[str] | None = None,
        model: str = "",
        max_turns: int = _DEFAULT_MAX_TURNS,
    ) -> AgentConfig:
        """Dynamically define a new agent at runtime (spec section 3.2).

        Validates the name, system prompt size, tool references, and
        max_turns cap. Returns the created :class:`AgentConfig`.
        """
        _validate_agent_name(name)

        # Validate system prompt size (spec section 4.7).
        prompt_tokens = _estimate_tokens(system_prompt)
        if prompt_tokens > _MAX_PROMPT_TOKENS:
            raise PromptTooLargeError(
                f"System prompt is ~{prompt_tokens} tokens, max is {_MAX_PROMPT_TOKENS}."
            )

        # Clamp max_turns (spec section 4.4).
        max_turns = min(max(1, max_turns), _ABSOLUTE_MAX_TURNS)

        # Filter out 'subagent' and validate tool names (spec section 3.2).
        clean_tools: list[str] = []
        if tools:
            for t in tools:
                if t == "subagent":
                    continue  # Silently excluded (spec section 4.5).
                if self._available_tools and t not in self._available_tools:
                    raise InvalidToolError(
                        f"Tool not in application registry: {t!r}"
                    )
                clean_tools.append(t)

        config = AgentConfig(
            name=name,
            description=description,
            system_prompt=system_prompt,
            tools=tuple(clean_tools),
            model=model,
            max_turns=max_turns,
        )

        with self._lock:
            if name in self._agents:
                raise AgentAlreadyExistsError(
                    f"Agent already registered: {name!r}"
                )
            self._agents[name] = config

        return config

    def get(self, name: str) -> AgentConfig:
        """Look up an agent by name. Raises :class:`AgentNotFoundError`."""
        with self._lock:
            config = self._agents.get(name)
        if config is None:
            raise AgentNotFoundError(f"Unknown agent: {name!r}")
        return config

    def list_agents(self) -> list[dict[str, Any]]:
        """Return summaries of all registered agents."""
        with self._lock:
            return [c.to_summary() for c in self._agents.values()]

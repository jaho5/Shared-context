"""Tool handler that translates agent JSON requests into store operations.

This module provides the bridge between an agent tool-use interface and
the :class:`SharedContextStore`.  The :func:`handle` function accepts
the JSON request dict an agent would send (spec §3) and returns the
JSON-serializable response dict.
"""

from __future__ import annotations

from typing import Any

from shared_context.errors import SharedContextError
from shared_context.store import SharedContextStore

_VALID_ACTIONS = {"list_keys", "read", "write", "delete"}


def handle(
    store: SharedContextStore,
    request: dict[str, Any],
    *,
    participant: str = "unknown",
) -> dict[str, Any]:
    """Dispatch a shared_context tool call to the store.

    Parameters
    ----------
    store:
        The session's :class:`SharedContextStore` instance.
    request:
        The JSON body sent by the agent.  Must contain ``"action"``; may
        contain ``"key"`` and ``"value"`` depending on the action.
    participant:
        Identity of the calling agent (set by the tool execution layer,
        not by the agent itself — spec §8.3).

    Returns
    -------
    dict
        JSON-serializable response, or an error dict with ``"error"``
        and ``"message"`` keys.
    """
    action = request.get("action")
    if action not in _VALID_ACTIONS:
        return {
            "error": "INVALID_ACTION",
            "message": f"Unknown action: {action!r}. Valid: {sorted(_VALID_ACTIONS)}",
        }

    try:
        if action == "list_keys":
            return store.list_keys()

        if action == "read":
            key = request.get("key", "")
            return store.read(key)

        if action == "write":
            key = request.get("key", "")
            value = request.get("value", "")
            return store.write(key, value, written_by=participant)

        if action == "delete":
            key = request.get("key", "")
            return store.delete(key)

    except SharedContextError as exc:
        return exc.to_dict()

    # Should be unreachable, but just in case.
    return {"error": "INTERNAL", "message": "Unexpected state."}  # pragma: no cover

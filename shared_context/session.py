"""Session manager — creates, retrieves, archives, and deletes sessions.

Provides the lifecycle operations described in spec §8.4.  Each session
maps to a single :class:`SharedContextStore` backed by a JSON file under
a configurable storage directory.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from shared_context.errors import SessionArchivedError, SessionNotFoundError
from shared_context.store import SharedContextStore


class SessionManager:
    """Manages multiple shared-context sessions on disk.

    Parameters
    ----------
    storage_dir:
        Root directory.  Each session is stored as
        ``{storage_dir}/{session_id}/context.json``.
    """

    def __init__(self, storage_dir: str | Path) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, SharedContextStore] = {}

    def create_session(self, session_id: str) -> SharedContextStore:
        """Create a new empty session.  Raises if it already exists."""
        session_dir = self._dir / session_id
        if session_dir.exists():
            raise ValueError(f"Session {session_id!r} already exists.")
        path = self._session_path(session_id)
        store = SharedContextStore(session_id, storage_path=path)
        # Eagerly persist the empty store so the directory/file exist on disk.
        store._persist()
        self._cache[session_id] = store
        return store

    def get_session(self, session_id: str) -> SharedContextStore:
        """Return an existing session, loading from disk if needed."""
        if session_id in self._cache:
            return self._cache[session_id]
        path = self._session_path(session_id)
        if not path.exists():
            raise SessionNotFoundError(f"Session {session_id!r} not found.")
        store = SharedContextStore(session_id, storage_path=path)
        self._cache[session_id] = store
        return store

    def archive_session(self, session_id: str) -> None:
        """Mark a session as archived (read-only)."""
        store = self.get_session(session_id)
        store.archive()

    def delete_session(self, session_id: str) -> None:
        """Permanently delete a session's data."""
        session_dir = self._dir / session_id
        if not session_dir.exists():
            raise SessionNotFoundError(f"Session {session_id!r} not found.")
        shutil.rmtree(session_dir)
        self._cache.pop(session_id, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return metadata for all sessions on disk."""
        sessions = []
        for child in sorted(self._dir.iterdir()):
            if child.is_dir() and (child / "context.json").exists():
                store = self.get_session(child.name)
                info = store.list_keys()
                sessions.append(
                    {
                        "session_id": child.name,
                        "archived": store.archived,
                        "key_count": len(info["keys"]),
                        "total_size_tokens": info["total_size_tokens"],
                    }
                )
        return sessions

    def _session_path(self, session_id: str) -> Path:
        return self._dir / session_id / "context.json"

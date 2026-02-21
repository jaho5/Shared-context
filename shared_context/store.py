"""Reference implementation of the Shared Context store (spec §§2-5, 8)."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared_context.errors import (
    InvalidKeyError,
    KeyNotFoundError,
    SessionArchivedError,
    StoreFullError,
    ValueTooLargeError,
)

_KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")
_MAX_KEY_LENGTH = 64
_MAX_VALUE_TOKENS = 1000
_WARN_VALUE_TOKENS = 800
_MAX_STORE_TOKENS = 10_000


def _estimate_tokens(text: str) -> int:
    """Approximate token count: len(text) / 4 (spec §8.2)."""
    return max(1, len(text) // 4)


def _validate_key(key: str) -> None:
    if not key or len(key) > _MAX_KEY_LENGTH:
        raise InvalidKeyError(
            f"Key must be 1-{_MAX_KEY_LENGTH} characters, got {len(key)}."
        )
    if not _KEY_PATTERN.match(key):
        raise InvalidKeyError(
            f"Key must match [a-z0-9_]+, got: {key!r}"
        )


class _Entry:
    """Internal representation of a single shared context entry."""

    __slots__ = ("key", "value", "written_by", "written_at", "version")

    def __init__(
        self,
        key: str,
        value: str,
        written_by: str,
        written_at: datetime,
        version: int,
    ) -> None:
        self.key = key
        self.value = value
        self.written_by = written_by
        self.written_at = written_at
        self.version = version

    @property
    def value_size_tokens(self) -> int:
        return _estimate_tokens(self.value)

    def to_meta(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "written_by": self.written_by,
            "written_at": self.written_at.isoformat(),
            "version": self.version,
            "value_size_tokens": self.value_size_tokens,
        }

    def to_full(self) -> dict[str, Any]:
        d = self.to_meta()
        d["value"] = self.value
        return d

    def to_serializable(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "written_by": self.written_by,
            "written_at": self.written_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> _Entry:
        return cls(
            key=d["key"],
            value=d["value"],
            written_by=d["written_by"],
            written_at=datetime.fromisoformat(d["written_at"]),
            version=d["version"],
        )


class SharedContextStore:
    """A single-session shared context store backed by a JSON file.

    Thread-safe via a reentrant lock. Persists to ``storage_path`` on
    every write/delete so the store survives process restarts (spec §4.5).

    Parameters
    ----------
    session_id:
        Unique identifier for this session.
    storage_path:
        Path to the JSON file used for persistence.  Created on first write
        if it doesn't exist.  If ``None``, the store is in-memory only
        (useful for tests).
    """

    def __init__(
        self,
        session_id: str,
        storage_path: str | Path | None = None,
        *,
        archived: bool = False,
    ) -> None:
        self.session_id = session_id
        self._storage_path = Path(storage_path) if storage_path else None
        self._entries: dict[str, _Entry] = {}
        self._archived = archived
        self._lock = threading.RLock()
        if self._storage_path and self._storage_path.exists():
            self._load()

    # -- public operations (spec §3) -----------------------------------------

    def list_keys(self) -> dict[str, Any]:
        """Spec §3.1 — return all keys with metadata, no values."""
        with self._lock:
            total_tokens = sum(e.value_size_tokens for e in self._entries.values())
            return {
                "keys": [e.to_meta() for e in self._entries.values()],
                "total_size_tokens": total_tokens,
            }

    def read(self, key: str) -> dict[str, Any]:
        """Spec §3.2 — return full entry for *key*."""
        _validate_key(key)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise KeyNotFoundError(f"Key not found: {key!r}")
            return entry.to_full()

    def write(
        self,
        key: str,
        value: str,
        written_by: str = "unknown",
    ) -> dict[str, Any]:
        """Spec §3.3 — create or overwrite *key*."""
        self._check_writable()
        _validate_key(key)

        value_tokens = _estimate_tokens(value)
        if value_tokens > _MAX_VALUE_TOKENS:
            raise ValueTooLargeError(
                f"Value is ~{value_tokens} tokens, max is {_MAX_VALUE_TOKENS}."
            )

        with self._lock:
            # Compute new total (subtract old value if overwriting).
            old_tokens = 0
            version = 1
            if key in self._entries:
                old_tokens = self._entries[key].value_size_tokens
                version = self._entries[key].version + 1

            current_total = sum(e.value_size_tokens for e in self._entries.values())
            new_total = current_total - old_tokens + value_tokens
            if new_total > _MAX_STORE_TOKENS:
                raise StoreFullError(
                    f"Write would bring store to ~{new_total} tokens, "
                    f"max is {_MAX_STORE_TOKENS}."
                )

            now = datetime.now(timezone.utc)
            entry = _Entry(
                key=key,
                value=value,
                written_by=written_by,
                written_at=now,
                version=version,
            )
            self._entries[key] = entry
            self._persist()

            result: dict[str, Any] = {
                "key": key,
                "version": version,
                "written_by": written_by,
                "written_at": now.isoformat(),
            }
            if value_tokens >= _WARN_VALUE_TOKENS:
                result["warning"] = (
                    f"Value is ~{value_tokens} tokens. Consider distilling further."
                )
            return result

    def delete(self, key: str) -> dict[str, Any]:
        """Spec §3.4 — remove *key* entirely."""
        self._check_writable()
        _validate_key(key)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise KeyNotFoundError(f"Key not found: {key!r}")
            prev_version = entry.version
            del self._entries[key]
            self._persist()
            return {"deleted": key, "previous_version": prev_version}

    # -- session lifecycle helpers (spec §8.4) --------------------------------

    def archive(self) -> None:
        """Mark session as archived (read-only)."""
        self._archived = True
        self._persist()

    @property
    def archived(self) -> bool:
        return self._archived

    # -- internal -------------------------------------------------------------

    def _check_writable(self) -> None:
        if self._archived:
            raise SessionArchivedError(
                f"Session {self.session_id!r} is archived (read-only)."
            )

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        data = {
            "session_id": self.session_id,
            "archived": self._archived,
            "entries": [e.to_serializable() for e in self._entries.values()],
        }
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._storage_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self._storage_path)

    def _load(self) -> None:
        assert self._storage_path is not None
        data = json.loads(self._storage_path.read_text())
        self._archived = data.get("archived", False)
        self._entries = {}
        for raw in data.get("entries", []):
            entry = _Entry.from_dict(raw)
            self._entries[entry.key] = entry

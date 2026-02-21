"""Tests for SessionManager."""

from pathlib import Path

import pytest

from shared_context.errors import SessionArchivedError, SessionNotFoundError
from shared_context.session import SessionManager


@pytest.fixture
def manager(tmp_path: Path) -> SessionManager:
    return SessionManager(tmp_path / "sessions")


def test_create_and_get(manager: SessionManager) -> None:
    store = manager.create_session("s1")
    store.write("k", "v", written_by="a")

    fetched = manager.get_session("s1")
    assert fetched.read("k")["value"] == "v"


def test_create_duplicate_raises(manager: SessionManager) -> None:
    manager.create_session("s1")
    with pytest.raises(ValueError, match="already exists"):
        manager.create_session("s1")


def test_get_missing_raises(manager: SessionManager) -> None:
    with pytest.raises(SessionNotFoundError):
        manager.get_session("nope")


def test_archive(manager: SessionManager) -> None:
    store = manager.create_session("s1")
    store.write("k", "v", written_by="a")
    manager.archive_session("s1")

    archived = manager.get_session("s1")
    assert archived.archived
    assert archived.read("k")["value"] == "v"
    with pytest.raises(SessionArchivedError):
        archived.write("k2", "v2", written_by="a")


def test_delete(manager: SessionManager) -> None:
    manager.create_session("s1")
    manager.delete_session("s1")
    with pytest.raises(SessionNotFoundError):
        manager.get_session("s1")


def test_delete_missing_raises(manager: SessionManager) -> None:
    with pytest.raises(SessionNotFoundError):
        manager.delete_session("nope")


def test_list_sessions(manager: SessionManager) -> None:
    s1 = manager.create_session("alpha")
    s1.write("k", "v", written_by="a")
    manager.create_session("beta")

    sessions = manager.list_sessions()
    ids = {s["session_id"] for s in sessions}
    assert ids == {"alpha", "beta"}
    alpha = next(s for s in sessions if s["session_id"] == "alpha")
    assert alpha["key_count"] == 1
    assert alpha["archived"] is False

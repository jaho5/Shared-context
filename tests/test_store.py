"""Tests for SharedContextStore and the tool handler."""

import tempfile
from pathlib import Path

import pytest

from shared_context import (
    InvalidKeyError,
    KeyNotFoundError,
    SessionArchivedError,
    SharedContextStore,
    StoreFullError,
    ValueTooLargeError,
)
from shared_context.tool import handle


# -- fixtures ----------------------------------------------------------------

@pytest.fixture
def store() -> SharedContextStore:
    """In-memory store (no persistence)."""
    return SharedContextStore("test-session")


@pytest.fixture
def persisted_store(tmp_path: Path) -> SharedContextStore:
    """Store backed by a temp JSON file."""
    return SharedContextStore("test-session", storage_path=tmp_path / "ctx.json")


# -- list_keys ---------------------------------------------------------------

def test_list_keys_empty(store: SharedContextStore) -> None:
    result = store.list_keys()
    assert result["keys"] == []
    assert result["total_size_tokens"] == 0


def test_list_keys_after_writes(store: SharedContextStore) -> None:
    store.write("alpha", "hello", written_by="agent")
    store.write("beta", "world", written_by="agent")
    result = store.list_keys()
    keys = {k["key"] for k in result["keys"]}
    assert keys == {"alpha", "beta"}
    assert result["total_size_tokens"] > 0
    # Values must NOT be present in list_keys output.
    for entry in result["keys"]:
        assert "value" not in entry


# -- read --------------------------------------------------------------------

def test_read_existing(store: SharedContextStore) -> None:
    store.write("foo", "bar", written_by="tester")
    result = store.read("foo")
    assert result["value"] == "bar"
    assert result["written_by"] == "tester"
    assert result["version"] == 1


def test_read_missing(store: SharedContextStore) -> None:
    with pytest.raises(KeyNotFoundError):
        store.read("nope")


# -- write -------------------------------------------------------------------

def test_write_creates_key(store: SharedContextStore) -> None:
    result = store.write("new_key", "new_value", written_by="agent")
    assert result["version"] == 1
    assert result["key"] == "new_key"


def test_write_overwrites_and_increments_version(store: SharedContextStore) -> None:
    store.write("k", "v1", written_by="a")
    result = store.write("k", "v2", written_by="b")
    assert result["version"] == 2
    assert store.read("k")["value"] == "v2"
    assert store.read("k")["written_by"] == "b"


def test_write_value_too_large(store: SharedContextStore) -> None:
    big = "x" * 4100  # ~1025 tokens
    with pytest.raises(ValueTooLargeError):
        store.write("big", big, written_by="a")


def test_write_store_full(store: SharedContextStore) -> None:
    # Fill up the store with multiple keys.
    chunk = "x" * 3900  # ~975 tokens each, under single-value limit
    for i in range(10):
        store.write(f"k{i}", chunk, written_by="a")
    # One more should exceed the 10,000-token total.
    with pytest.raises(StoreFullError):
        store.write("overflow", chunk, written_by="a")


def test_write_warns_on_large_value(store: SharedContextStore) -> None:
    big_ish = "x" * 3300  # ~825 tokens, above 800 warning threshold
    result = store.write("big_ish", big_ish, written_by="a")
    assert "warning" in result


# -- delete ------------------------------------------------------------------

def test_delete_existing(store: SharedContextStore) -> None:
    store.write("temp", "val", written_by="a")
    result = store.delete("temp")
    assert result["deleted"] == "temp"
    assert result["previous_version"] == 1
    with pytest.raises(KeyNotFoundError):
        store.read("temp")


def test_delete_missing(store: SharedContextStore) -> None:
    with pytest.raises(KeyNotFoundError):
        store.delete("nope")


# -- key validation ----------------------------------------------------------

@pytest.mark.parametrize("bad_key", [
    "",
    "Has-Dash",
    "has.dot",
    "has/slash",
    "UPPERCASE",
    "a" * 65,
])
def test_invalid_key_rejected(store: SharedContextStore, bad_key: str) -> None:
    with pytest.raises(InvalidKeyError):
        store.write(bad_key, "val", written_by="a")


@pytest.mark.parametrize("good_key", [
    "a",
    "problem_summary",
    "k123",
    "a" * 64,
])
def test_valid_key_accepted(store: SharedContextStore, good_key: str) -> None:
    store.write(good_key, "val", written_by="a")
    assert store.read(good_key)["value"] == "val"


# -- persistence -------------------------------------------------------------

def test_persistence_survives_reload(tmp_path: Path) -> None:
    path = tmp_path / "ctx.json"
    s1 = SharedContextStore("sess", storage_path=path)
    s1.write("x", "hello", written_by="a")

    # Load a fresh instance from the same file.
    s2 = SharedContextStore("sess", storage_path=path)
    assert s2.read("x")["value"] == "hello"
    assert s2.read("x")["version"] == 1


def test_delete_persists(tmp_path: Path) -> None:
    path = tmp_path / "ctx.json"
    s1 = SharedContextStore("sess", storage_path=path)
    s1.write("x", "hello", written_by="a")
    s1.delete("x")

    s2 = SharedContextStore("sess", storage_path=path)
    with pytest.raises(KeyNotFoundError):
        s2.read("x")


# -- archive -----------------------------------------------------------------

def test_archived_store_is_read_only(store: SharedContextStore) -> None:
    store.write("k", "v", written_by="a")
    store.archive()
    # Reads still work.
    assert store.read("k")["value"] == "v"
    assert store.list_keys()["keys"]
    # Writes and deletes are rejected.
    with pytest.raises(SessionArchivedError):
        store.write("k2", "v2", written_by="a")
    with pytest.raises(SessionArchivedError):
        store.delete("k")


# -- tool handler ------------------------------------------------------------

def test_tool_list_keys(store: SharedContextStore) -> None:
    store.write("a", "1", written_by="x")
    result = handle(store, {"action": "list_keys"}, participant="agent")
    assert len(result["keys"]) == 1


def test_tool_read(store: SharedContextStore) -> None:
    store.write("a", "1", written_by="x")
    result = handle(store, {"action": "read", "key": "a"}, participant="agent")
    assert result["value"] == "1"


def test_tool_write(store: SharedContextStore) -> None:
    result = handle(
        store,
        {"action": "write", "key": "b", "value": "2"},
        participant="subagent:test",
    )
    assert result["version"] == 1
    assert result["written_by"] == "subagent:test"


def test_tool_delete(store: SharedContextStore) -> None:
    store.write("c", "3", written_by="x")
    result = handle(store, {"action": "delete", "key": "c"}, participant="agent")
    assert result["deleted"] == "c"


def test_tool_invalid_action(store: SharedContextStore) -> None:
    result = handle(store, {"action": "explode"}, participant="agent")
    assert result["error"] == "INVALID_ACTION"


def test_tool_error_returns_dict(store: SharedContextStore) -> None:
    result = handle(store, {"action": "read", "key": "missing"}, participant="agent")
    assert result["error"] == "KEY_NOT_FOUND"

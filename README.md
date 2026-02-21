# Shared Context

A session-scoped key-value store for multi-agent orchestration systems. Gives your agents working memory that persists across subagent invocations — so they stop re-investigating and start collaborating.

## Why

- **Chat history is noisy.** Extracting signal from 50 turns is wasteful.
- **Subagents are stateless.** Every invocation starts from scratch without shared state.
- **Databases are for persistence, not reasoning.** Agents need fast access to distilled, curated state.

Shared context sits between chat history and your database — a small, disciplined store of conclusions, decisions, and status that any agent in the session can read and write.

## Install

```bash
pip install -e .
```

## Quick Start (OpenAI)

```python
from openai import OpenAI
from shared_context import SharedContextStore
from shared_context.openai import tool_definition, process_response

client = OpenAI()
store = SharedContextStore("session_1", storage_path="./data/context.json")

messages = [
    {"role": "system", "content": "You have a shared_context tool..."},
    {"role": "user", "content": "Investigate the latency issue."},
]

while True:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=[tool_definition()],
    )
    new_messages, done = process_response(response, store, participant="agent")
    messages.extend(new_messages)
    if done:
        break
```

## Quick Start (Anthropic)

```python
from anthropic import Anthropic
from shared_context import SharedContextStore
from shared_context.anthropic import tool_definition, process_response

client = Anthropic()
store = SharedContextStore("session_1", storage_path="./data/context.json")

messages = [{"role": "user", "content": "Investigate the latency issue."}]

while True:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=messages,
        tools=[tool_definition()],
    )
    new_messages, done = process_response(response, store, participant="agent")
    messages.extend(new_messages)
    if done:
        break
```

## Multi-Agent Pattern

The real value shows up when multiple subagents share the same store:

```python
from shared_context import SharedContextStore
from shared_context.openai import tool_definition, process_response

store = SharedContextStore("session_1", storage_path="./data/context.json")

# Orchestrator sets up the problem
store.write("problem_summary", "Throughput dropped 30% after config change.", written_by="orchestrator")
store.write("scope", "Identify root cause. Read-only access to prod.", written_by="orchestrator")

# Subagent 1: investigates, writes findings
run_agent(store, participant="subagent:investigation", task="Investigate the problem.")

# Subagent 2: reads findings, drafts remediation — zero re-investigation
run_agent(store, participant="subagent:remediation", task="Draft a remediation plan.")
```

See [`examples/`](examples/) for complete working scripts.

## Operations

Four operations, all synchronous and atomic at the single-key level:

| Operation | Description |
|-----------|-------------|
| `list_keys` | Returns all keys with metadata (no values). Always call this first. |
| `read` | Returns the value for a single key. |
| `write` | Creates or overwrites a key. |
| `delete` | Removes a key entirely. |

## Constraints

| Constraint | Limit |
|------------|-------|
| Value size | 1,000 tokens (~4,000 chars) per key |
| Store size | 10,000 tokens total across all keys |
| Key format | `[a-z0-9_]+`, max 64 characters |

These limits enforce discipline — shared context is for distilled conclusions, not raw data.

## Project Structure

```
SPEC.md                    Full specification (v0.1.0-draft)
shared_context/
  __init__.py              Public API
  errors.py                Error types (KEY_NOT_FOUND, VALUE_TOO_LARGE, etc.)
  store.py                 Core key-value store with JSON persistence
  tool.py                  JSON request dispatcher (API-agnostic)
  schema.py                Tool schemas for OpenAI and Anthropic formats
  openai.py                OpenAI chat completions integration
  anthropic.py             Anthropic messages API integration
  session.py               Multi-session lifecycle manager
examples/
  openai_agent_loop.py     Single agent with OpenAI
  anthropic_agent_loop.py  Single agent with Anthropic
  multi_agent.py           Multi-agent orchestration
tests/                     68 tests
```

## Key Design Decisions

- **No SDK dependencies.** Works with `openai` and `anthropic` SDKs but doesn't require them. All integrations accept both SDK objects and raw dicts.
- **JSON file persistence.** Atomic writes (write-to-tmp, rename) for crash safety. Swap the backend for Redis/Postgres in production.
- **Thread-safe.** Reentrant lock on all operations.
- **Last-write-wins.** No locking or transactions. Version numbers let agents detect unexpected overwrites.
- **Token-based limits.** Approximate counting (`len/4`) — good enough for budgeting, no tokenizer dependency.

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Specification

See [SPEC.md](SPEC.md) for the full specification including system prompt integration guidance, anti-patterns, and extension points.

# Shared Context Specification

**Version:** 0.1.0-draft
**Scope:** General-purpose working memory for multi-agent orchestration systems

---

## 1. Overview

Shared Context is a mutable key-value store scoped to an agent session. It serves as working memory accessible by an orchestrator agent and any subagents it launches. Its purpose is to hold **curated, distilled state** — not raw data, not full history, not formal records.

It exists because:

- Chat history accumulates noise. Extracting signal from 50 turns is wasteful and error-prone.
- Formal records/databases are structured for persistence and compliance, not for agent reasoning.
- Subagents are stateless. Without shared context, every invocation requires full context re-assembly from external sources.

Shared context is **additional** to other data access tools (database reads, search indexes, document retrieval). It reduces how often those tools are needed, not replaces them.

---

## 2. Concepts

### 2.1 Session

A session is the lifecycle scope of a shared context instance. One session = one shared context store. Sessions map to whatever the domain's unit of work is (a CAPA, a support ticket, a project, a research task). A session may span multiple conversations, multiple days, and multiple subagent invocations.

Sessions are identified by a unique `session_id`.

### 2.2 Participants

Any agent (orchestrator or subagent) that holds a reference to the session's shared context and has the `shared_context` tool available. All participants have equal read/write access. Access control, if needed, is enforced at the tool layer, not the store layer (see §7 Extensions).

### 2.3 Entry

A single key-value pair with metadata.

```
Entry:
  key:         string    # identifier
  value:       string    # content (always text — structured data is serialized)
  written_by:  string    # participant identifier
  written_at:  datetime  # UTC timestamp
  version:     integer   # monotonic, increments on every write to this key
```

### 2.4 Key Namespace

A defined set of key conventions for a given domain. Provided in the system prompt. Keys outside the namespace are permitted (ad-hoc keys) but conventioned keys are preferred for interoperability between orchestrator and subagents.

---

## 3. Operations

Four operations. All are synchronous and atomic at the single-key level.

### 3.1 list_keys

Returns all keys with metadata. Does **not** return values.

**Request:**
```json
{
  "action": "list_keys"
}
```

**Response:**
```json
{
  "keys": [
    {
      "key": "problem_summary",
      "written_by": "orchestrator",
      "written_at": "2026-02-20T14:30:00Z",
      "version": 2,
      "value_size_tokens": 180
    }
  ]
}
```

**Purpose:** Agents inspect what's available before reading. The `value_size_tokens` field lets agents budget context — skip large values they don't need.

### 3.2 read

Returns the value for a single key.

**Request:**
```json
{
  "action": "read",
  "key": "problem_summary"
}
```

**Response:**
```json
{
  "key": "problem_summary",
  "value": "Customer reported intermittent alarm...",
  "written_by": "subagent:initiation",
  "written_at": "2026-02-20T14:30:00Z",
  "version": 2
}
```

Returns error if key does not exist (see §5 Error Handling).

### 3.3 write

Creates or overwrites a key.

**Request:**
```json
{
  "action": "write",
  "key": "problem_summary",
  "value": "Updated summary after investigation..."
}
```

**Response:**
```json
{
  "key": "problem_summary",
  "version": 3,
  "written_by": "subagent:investigation",
  "written_at": "2026-02-20T15:45:00Z"
}
```

Semantics:
- Key exists → overwrite value, increment version.
- Key does not exist → create with version 1.
- `written_by` is set automatically by the system based on the calling participant's identity. Agents cannot spoof this.

### 3.4 delete

Removes a key entirely.

**Request:**
```json
{
  "action": "delete",
  "key": "open_questions"
}
```

**Response:**
```json
{
  "deleted": "open_questions",
  "previous_version": 5
}
```

Returns error if key does not exist.

---

## 4. Constraints

### 4.1 Value Size

Maximum value size: **1000 tokens** (approximately 750 words / 4000 characters).

Rationale: Shared context is for distilled state. If a value approaches 1000 tokens, the agent is likely storing raw data rather than conclusions. The limit enforces discipline.

Implementation may return a warning at 800 tokens and reject writes above 1000 tokens.

### 4.2 Total Store Size

Maximum total across all values: **10,000 tokens**.

This ensures that even if a subagent reads the entire shared context (which it shouldn't, but might), it doesn't blow the context budget. At typical agent context windows of 100K-200K tokens, 10K for shared context is a modest allocation.

Implementation should return current total size in `list_keys` response metadata.

### 4.3 Key Naming

- Lowercase alphanumeric + underscores only: `[a-z0-9_]+`
- Maximum length: 64 characters
- No dots, slashes, or hierarchical separators (flat namespace; see §7 Extensions for namespacing)

### 4.4 Concurrency

Last-write-wins. No locking, no transactions. This is acceptable because:

- Agent systems are typically sequential (orchestrator → subagent → orchestrator). True concurrent writes to the same key are rare.
- Version numbers allow detection of unexpected overwrites. An agent can read a key's version, do work, and check the version hasn't changed before writing.
- If stronger consistency is needed, implement at the tool layer (see §7 Extensions).

### 4.5 Durability

Shared context persists for the lifetime of the session. It survives:
- Individual subagent completion
- Conversation boundaries (user returns tomorrow)
- Orchestrator restarts within the same session

It does NOT survive:
- Session closure/archival
- Explicit session deletion

Implementation must persist to durable storage (not in-memory only).

---

## 5. Error Handling

```
KEY_NOT_FOUND        read/delete on nonexistent key
VALUE_TOO_LARGE      write value exceeds 1000 token limit
STORE_FULL           write would exceed 10,000 token total limit
INVALID_KEY          key does not match [a-z0-9_]+ or exceeds 64 characters
SESSION_NOT_FOUND    session_id is invalid or closed
SESSION_ARCHIVED     session has been archived (read-only)
```

All errors return the error code and a human-readable message. Agents should handle `KEY_NOT_FOUND` gracefully — it's expected when checking for optional keys.

---

## 6. System Prompt Integration

The shared context tool is useful only if agents know **what to write, what to read, and what not to store.** This is communicated via system prompt instructions in three parts.

### 6.1 Key Namespace Definition

Domain-specific. Provided by the admin who configures the agent system. Defines conventioned keys, their purpose, and expected content shape.

**Example structure (domain-neutral):**

```
Shared context key conventions:

State keys:
  current_phase         - current workflow phase/stage
  phase_status          - what's done, what's next
  blocking_issues       - anything preventing progress

Problem definition:
  problem_summary       - distilled statement of the problem/goal
  scope                 - boundaries of the work
  constraints           - known constraints or requirements

Findings:
  findings_summary      - key findings so far (distilled, not raw)
  open_questions        - unresolved questions for the user or next agent
  decisions_made        - user decisions with brief rationale

Output tracking:
  deliverables_status   - what's been produced, what's pending
  quality_checks        - validation results (pass/fail + brief reason)
```

Implementations should provide a domain-specific namespace. The above is a starting template.

### 6.2 Write Discipline Instructions

Included in the system prompt for all participants.

```
When writing to shared_context:

DO store:
  - Conclusions and current state
  - User decisions with brief rationale
  - Distilled findings (the "so what", not the raw data)
  - Active references (IDs, not full content — re-fetch if needed)
  - Open questions and blockers
  - Status of in-progress work

Do NOT store:
  - Raw data, full documents, or chat transcripts
  - Content that belongs in the formal record/database
  - PII or sensitive data (names, identifiers, credentials)
  - Full text of external sources (store reference IDs, re-fetch as needed)
  - Intermediate reasoning or scratch work

Discipline:
  - If a value exceeds ~500 tokens, consider whether you're storing
    raw data rather than conclusions. Distill further.
  - Update existing keys rather than creating new ones for the same concept.
  - After writing a deliverable to shared_context, also write it to the
    formal record if it's a reviewable artifact.
  - Delete keys that are no longer relevant (e.g., resolved open_questions).
```

### 6.3 Read Pattern Instructions

```
When reading from shared_context:

  1. Always call list_keys first to see what's available.
  2. Read only keys relevant to your current task.
  3. Use value_size_tokens to decide whether a key is worth reading
     — large values may not be relevant to your specific task.
  4. If a key was written_by a previous subagent and is marked as
     approved/validated by the user (check phase_status or decisions_made),
     treat it as authoritative.
  5. If a key was written_by a subagent and is still in draft state,
     treat it as input to your reasoning, not as settled fact.
  6. If you need information not present in shared_context,
     use other tools (database read, search, etc.). Shared context
     is a cache of distilled state, not the source of truth.
```

---

## 7. Extensions

These are not part of the core spec but are anticipated needs.

### 7.1 Key Namespacing

For complex systems with many subagent types, prefix conventions may help:

```
inv:findings_summary      (investigation subagent's namespace)
rev:review_result         (review subagent's namespace)
```

Core spec uses flat namespace for simplicity. Implementations may add prefixes if collision becomes a problem.

### 7.2 Access Control

Some deployments may want read-only access for certain participants, or keys visible only to certain roles.

```
Entry (extended):
  readable_by:  list[string]  # participant patterns, default ["*"]
  writable_by:  list[string]  # participant patterns, default ["*"]
```

Not recommended for most deployments. Adds complexity. Prefer trust + write discipline.

### 7.3 History / Audit Trail

Core spec is current-value-only. Some deployments may want version history:

```json
{
  "action": "read_history",
  "key": "root_cause_draft",
  "versions": [1, 2, 3]
}
```

Returns all historical values for a key. Useful for understanding how conclusions evolved. Implementation concern: storage growth. Consider retaining only last N versions.

### 7.4 Batch Read

For efficiency, agents may want to read multiple keys in one call:

```json
{
  "action": "read_batch",
  "keys": ["problem_summary", "current_phase", "risk_current"]
}
```

Reduces tool call overhead. Straightforward to implement.

### 7.5 TTL / Expiry

Keys that auto-expire after a duration. Useful for transient state like `blocking_issues` that should not persist indefinitely if no one cleans them up. Not recommended for most deployments — prefer explicit delete.

### 7.6 Snapshots

Freeze the entire shared context at a point in time (e.g., at phase transitions, before/after user approval checkpoints). Enables rollback and audit.

```json
{
  "action": "snapshot",
  "label": "pre_approval_phase_3"
}
```

Valuable for regulated domains where you need to show what the agent knew at decision points.

### 7.7 Subscriptions / Notifications

Orchestrator gets notified when a subagent writes to certain keys. Useful in async architectures where subagents run in parallel.

Outside scope of this spec. Mention for completeness.

---

## 8. Implementation Guidance

### 8.1 Storage Backend

Any key-value store works. Requirements:

- Durable (survives process restarts)
- Supports per-session isolation (sessions don't leak into each other)
- Millisecond read/write latency (agents are waiting synchronously)

Redis with session-prefixed keys, a document database with session-scoped collections, or even a relational table with (session_id, key, value, metadata) rows all work.

For prototyping: an in-memory Python dict serialized to disk per session is fine.

### 8.2 Token Counting

`value_size_tokens` in `list_keys` response requires token counting. Options:

- Exact: run the value through the model's tokenizer. Accurate but adds latency.
- Approximate: `len(value) / 4`. Good enough for budgeting decisions. Recommended for most implementations.

The 1000-token write limit and 10,000-token store limit can use approximate counting.

### 8.3 Participant Identity

`written_by` should be set by the system, not by the agent self-reporting. The tool execution layer knows which agent is calling. Format recommendation:

```
"orchestrator"
"subagent:{task_type}"        e.g. "subagent:investigation"
"subagent:{task_type}:{id}"   e.g. "subagent:investigation:3"  (if multiple invocations)
```

### 8.4 Session Lifecycle

```
create_session(session_id, config?)  → empty store
  ↓
  ... agents read/write over hours/days/weeks ...
  ↓
archive_session(session_id)          → read-only, retained for audit
  ↓
delete_session(session_id)           → gone
```

Session creation and archival are orchestrator/system operations, not agent-facing tool calls. Agents operate within an already-active session.

### 8.5 Observability

Log all write and delete operations with:
- session_id
- key
- written_by
- timestamp
- value_size_tokens
- version

Do NOT log values themselves (may contain distilled but still sensitive content). Log keys and metadata only.

For debugging, provide an admin-only interface to inspect full session contents.

---

## 9. Anti-Patterns

### 9.1 Using Shared Context as the Primary Database

Shared context is working memory. The formal record/database is the source of truth. Agents must write deliverables to the formal record, not rely on shared context as the permanent store. Shared context can be wiped and rebuilt from formal records; the reverse is not true.

### 9.2 Storing Raw Data

A 2000-token investigation data dump does not belong in shared context. A 150-token summary of findings does. If an agent writes raw data, the value size limit should catch it. If it doesn't (raw data happens to be short), the write discipline instructions should prevent it.

### 9.3 Never Deleting Keys

Over a long session, keys accumulate. Resolved questions, superseded drafts, and completed status entries should be deleted or updated. The total store size limit is a backstop, but agents should actively clean up.

### 9.4 Reading Everything Every Time

Agents should read selectively based on `list_keys`. A subagent doing effectiveness review doesn't need `investigation_data_summary`. The `value_size_tokens` field exists specifically to support this decision.

### 9.5 Duplicating the Formal Record

If the formal record has a `risk_assessment` field and shared context has a `risk_current` key, they will drift unless agents maintain both. The convention should be clear: shared context holds the *current working value* for quick access. The formal record is updated at defined checkpoints (phase transitions, approvals). Agents should not be expected to keep both in sync on every write.

### 9.6 PII in Shared Context

Shared context values are visible to all participants and logged at the metadata level. Never store names, patient identifiers, credentials, or other PII. Store role references, record IDs, and anonymized references. This applies even if the formal record contains PII — shared context is a reasoning layer, not a data layer.

---

## 10. Example: Full Interaction Cycle

Domain-agnostic example. An orchestrator launches a subagent to analyze something.

```
ORCHESTRATOR:
  shared_context(action="write", key="current_phase", value="analysis")
  shared_context(action="write", key="problem_summary",
    value="Throughput dropped 30% after config change on Feb 18.")
  shared_context(action="write", key="scope",
    value="Identify which config parameter caused degradation. Do not modify production.")
  shared_context(action="write", key="constraints",
    value="Read-only access to prod. Staging available for experiments.")

  → launches subagent:analysis with shared_context tool + domain-specific tools

SUBAGENT:
  shared_context(action="list_keys")
  → sees: current_phase, problem_summary, scope, constraints

  shared_context(action="read", key="problem_summary")
  shared_context(action="read", key="scope")
  shared_context(action="read", key="constraints")

  → uses domain tools to investigate...
  → finds the cause

  shared_context(action="write", key="findings_summary",
    value="Connection pool size reduced from 200 to 20 in Feb 18 config change.
           Thread starvation under load. Staging test confirmed:
           restoring to 200 resolves throughput.")
  shared_context(action="write", key="open_questions",
    value="Was the pool size change intentional? Need user confirmation before recommending revert.")

  → subagent completes

ORCHESTRATOR:
  shared_context(action="list_keys")
  → sees new keys: findings_summary, open_questions

  shared_context(action="read", key="open_questions")
  → surfaces question to user

USER: "No, that was accidental."

ORCHESTRATOR:
  shared_context(action="write", key="decisions_made",
    value="Config change was accidental. User approves revert recommendation.")
  shared_context(action="delete", key="open_questions")

  → launches subagent:remediation with shared_context tool + write tools

SUBAGENT:
  shared_context(action="list_keys")
  shared_context(action="read", key="findings_summary")
  shared_context(action="read", key="decisions_made")

  → knows exactly what to do without re-investigating
  → drafts remediation plan
  → writes to shared_context + formal record
```

Total external tool calls saved by shared context: the remediation subagent needed zero investigation — it read two keys and had full situational awareness.

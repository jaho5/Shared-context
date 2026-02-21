# Subagent Tool Specification

**Version:** 0.1.0-draft
**Scope:** Task delegation for multi-agent orchestration systems
**Companion spec:** Shared Context Specification v0.1.0-draft

---

## 1. Overview

The Subagent tool lets an orchestrator agent delegate tasks to specialist agents via a tool call. The orchestrator describes what it needs done, the tool runs a full agent loop behind the scenes, and the orchestrator collects the result.

It exists because:

- Orchestrators currently cannot dynamically decide to delegate. Delegation patterns are hardcoded in application control flow, not available to the agent's reasoning.
- Subagent configurations (system prompts, tools, constraints) are scattered across application code with no standard interface.
- Every framework wires delegation differently. There is no portable, tool-level primitive for "ask a specialist, get an answer."

The subagent tool standardizes task delegation the way shared context standardizes state sharing. Together they form a complete orchestration primitive set: **subagent** handles delegation, **shared context** handles state.

---

## 2. Concepts

### 2.1 Agent Registry

A collection of agent configurations, each identified by a unique name. The registry contains both **pre-registered** agents (defined in application code before the session starts) and **dynamically defined** agents (created by the orchestrator at runtime via the `define` action).

### 2.2 Agent Configuration

The definition of a specialist agent. What it knows, what tools it has, and how it behaves.

```
AgentConfig:
  name:          string         # unique identifier
  description:   string         # one-line purpose (shown in list_agents)
  system_prompt: string         # instructions for the subagent
  tools:         list[string]   # tool names available to the subagent
  model:         string         # model identifier (e.g. "claude-sonnet-4-20250514")
  max_turns:     integer        # maximum agent loop iterations (default 10)
```

The `tools` field references tool names registered in the application's tool registry. The subagent tool itself is **never** included — subagents cannot delegate further (see §4.5).

### 2.3 Task

A single subagent invocation. Created by `spawn`, tracked by `task_id`, resolved by `collect`.

```
Task:
  task_id:       string         # unique identifier, assigned by the system
  agent:         string         # name of the agent config used
  task:          string         # the task description sent as the user message
  status:        string         # "running" | "completed" | "failed"
  result:        string | null  # final text response (null until completed)
  error:         string | null  # error message (null unless failed)
  turns_used:    integer        # how many agent loop iterations were consumed
  created_at:    datetime       # UTC timestamp
  completed_at:  datetime|null  # UTC timestamp (null until resolved)
```

### 2.4 Task Lifecycle

```
spawn(agent, task)
  → task_id, status="running"
  ↓
  ... subagent loop executes (up to max_turns) ...
  ↓
status(task_id)
  → "running" | "completed" | "failed"
  ↓
collect(task_id)
  → result string (or error)
  → task is removed from active tracking
```

Tasks are fire-and-forget from the orchestrator's perspective. The orchestrator spawns, polls, and collects. It does not interact with the subagent during execution.

---

## 3. Operations

Five operations. `spawn` is asynchronous (returns immediately). All others are synchronous.

### 3.1 list_agents

Returns all available agent configurations with their descriptions.

**Request:**
```json
{
  "action": "list_agents"
}
```

**Response:**
```json
{
  "agents": [
    {
      "name": "researcher",
      "description": "Investigates technical issues using logs and metrics",
      "model": "claude-sonnet-4-20250514",
      "max_turns": 10,
      "tools": ["search_logs", "query_metrics", "shared_context"]
    },
    {
      "name": "writer",
      "description": "Drafts documentation and reports",
      "model": "claude-sonnet-4-20250514",
      "max_turns": 5,
      "tools": ["shared_context"]
    }
  ]
}
```

**Purpose:** The orchestrator discovers what specialists are available before deciding who to delegate to. Includes both pre-registered and dynamically defined agents.

### 3.2 define

Registers a new agent configuration at runtime.

**Request:**
```json
{
  "action": "define",
  "name": "analyst",
  "description": "Analyzes data patterns and produces summaries",
  "system_prompt": "You are a data analyst. Examine the data provided via tools and produce a concise summary of patterns, anomalies, and recommendations. Write findings to shared context.",
  "tools": ["query_database", "shared_context"],
  "model": "claude-sonnet-4-20250514",
  "max_turns": 10
}
```

**Response:**
```json
{
  "defined": "analyst",
  "description": "Analyzes data patterns and produces summaries"
}
```

Semantics:
- Name must be unique. If name already exists, returns `AGENT_ALREADY_EXISTS` error.
- `system_prompt` and `description` are required.
- `tools` defaults to `[]` if omitted. Only tool names already registered in the application's tool registry are valid. Invalid tool names return `INVALID_TOOL` error.
- `model` defaults to the orchestrator's model if omitted.
- `max_turns` defaults to 10 if omitted.
- The `subagent` tool is automatically excluded from the tools list even if specified. Subagents cannot delegate.

### 3.3 spawn

Starts a task on a named agent. Returns immediately with a task ID.

**Request:**
```json
{
  "action": "spawn",
  "agent": "researcher",
  "task": "Find the root cause of the latency spike that started at 14:00 UTC today. Check connection pool settings and thread utilization."
}
```

**Response:**
```json
{
  "task_id": "t_01",
  "agent": "researcher",
  "status": "running"
}
```

Semantics:
- `agent` must reference a registered agent name (pre-registered or dynamically defined). Returns `AGENT_NOT_FOUND` if unknown.
- `task` is sent as the user message in the subagent's conversation. The subagent sees its `system_prompt` (from the agent config) plus this task string.
- The subagent receives the tools specified in its agent config. It does **not** receive the `subagent` tool.
- The subagent has access to the session's shared context if `shared_context` is in its tool list.
- Execution is asynchronous. The orchestrator can spawn multiple tasks, do other work, and collect results later.

### 3.4 status

Checks the current status of a task.

**Request:**
```json
{
  "action": "status",
  "task_id": "t_01"
}
```

**Response (running):**
```json
{
  "task_id": "t_01",
  "agent": "researcher",
  "status": "running",
  "turns_used": 4
}
```

**Response (completed):**
```json
{
  "task_id": "t_01",
  "agent": "researcher",
  "status": "completed",
  "turns_used": 7
}
```

**Response (failed):**
```json
{
  "task_id": "t_01",
  "agent": "researcher",
  "status": "failed",
  "turns_used": 3,
  "error": "Max turns exceeded without producing a final response"
}
```

**Purpose:** Enables the orchestrator to poll for completion, especially when multiple tasks are running in parallel. The `turns_used` field lets the orchestrator gauge progress relative to `max_turns`.

### 3.5 collect

Retrieves the result of a completed or failed task. Removes the task from active tracking.

**Request:**
```json
{
  "action": "collect",
  "task_id": "t_01"
}
```

**Response (completed):**
```json
{
  "task_id": "t_01",
  "agent": "researcher",
  "status": "completed",
  "result": "Root cause: connection pool was reduced from 200 to 20 in the Feb 18 config change. Thread starvation under load confirmed in staging.",
  "turns_used": 7
}
```

**Response (failed):**
```json
{
  "task_id": "t_01",
  "agent": "researcher",
  "status": "failed",
  "error": "Max turns exceeded without producing a final response",
  "turns_used": 10
}
```

Semantics:
- Returns `TASK_NOT_READY` if the task is still running.
- Returns `TASK_NOT_FOUND` if the task ID is unknown or already collected.
- After a successful `collect`, the task ID is no longer valid. Calling `status` or `collect` again returns `TASK_NOT_FOUND`.
- The `result` field contains the subagent's final text response, distilled to the result size limit (see §4.1).
- For failed tasks, `result` is null and `error` contains a description of the failure.

---

## 4. Constraints

### 4.1 Result Size

Maximum result size: **1000 tokens** (approximately 750 words / 4000 characters).

Rationale: Subagents return distilled conclusions, not raw dumps. The orchestrator needs a summary it can reason about, not a data transfer. Rich or structured output should be written to shared context; the result is a concise answer to the task.

Implementation should instruct the subagent (via system prompt appendix) to keep its final response concise. If the subagent's raw response exceeds 1000 tokens, the implementation truncates and appends a notice: `[truncated — full response exceeded 1000 token limit]`.

### 4.2 Task String Size

Maximum task description: **1000 tokens**.

Rationale: Forces clear, scoped delegation. If the orchestrator needs to pass more context, it should write to shared context and reference it in the task string (e.g., "Investigate the problem described in shared context key `problem_summary`").

### 4.3 Max Concurrent Tasks

Maximum active (running) tasks: **5**.

Rationale: Prevents runaway spawning. Each running task consumes model inference resources. Five parallel specialists is sufficient for most orchestration patterns. Spawn returns `MAX_TASKS_EXCEEDED` if the limit is reached.

### 4.4 Max Turns per Subagent

Default: **10 turns** (configurable per agent config, max 25).

A "turn" is one iteration of the agent loop: model call → tool use → model call. If the subagent hasn't produced a final response within `max_turns`, the task fails with error "Max turns exceeded."

Rationale: Bounds execution cost. A subagent that cannot complete in 25 turns is likely stuck or poorly scoped.

### 4.5 No Nesting

Subagents do **not** receive the `subagent` tool. Only the orchestrator delegates. Delegation depth is always 1.

Rationale:
- Prevents runaway recursion (agent spawns agent spawns agent).
- Keeps the execution model simple and predictable.
- The orchestrator is the single point of coordination. If a task requires further delegation, the orchestrator should decompose it.

### 4.6 Agent Name Format

- Lowercase alphanumeric + underscores + hyphens: `[a-z0-9_-]+`
- Maximum length: 64 characters
- Must not collide with an existing registered name (for `define`)

### 4.7 System Prompt Size

Maximum system prompt in `define`: **4000 tokens**.

Rationale: System prompts should be focused instructions, not knowledge dumps. Domain knowledge should be accessible via tools, not embedded in the prompt.

---

## 5. Error Handling

```
AGENT_NOT_FOUND        spawn with unknown agent name
AGENT_ALREADY_EXISTS   define with a name that is already registered
TASK_NOT_FOUND         status/collect with unknown or already-collected task_id
TASK_NOT_READY         collect on a task that is still running
TASK_TOO_LARGE         task string exceeds 1000 token limit
MAX_TASKS_EXCEEDED     spawn when 5 tasks are already running
INVALID_AGENT_NAME     name does not match [a-z0-9_-]+ or exceeds 64 chars
INVALID_TOOL           define references a tool name not in the application registry
PROMPT_TOO_LARGE       system_prompt in define exceeds 4000 token limit
```

All errors return the error code and a human-readable message. The orchestrator should handle `TASK_NOT_READY` as expected flow — it means "check back later."

---

## 6. System Prompt Integration

The subagent tool is useful only if the orchestrator knows **when to delegate, how to scope tasks, and how to compose results.** This is communicated via system prompt instructions.

### 6.1 Available Agents Description

Describe each pre-registered agent's purpose, strengths, and when to use it. Dynamically defined agents are self-documenting via `list_agents`.

**Example:**

```
Available specialist agents (use subagent tool to delegate):

  researcher    - Investigates technical issues. Has access to logs,
                  metrics, and database queries. Use when you need
                  root cause analysis or data gathering.

  writer        - Drafts documentation and reports. Has access to
                  shared context only. Use when findings are ready
                  and need to be formatted for stakeholders.

You may also define new agents at runtime using the define action
if the available specialists don't match the task at hand.
```

### 6.2 Delegation Discipline Instructions

```
When delegating to subagents:

DO:
  - Write relevant context to shared_context BEFORE spawning
  - Scope tasks narrowly — one clear objective per delegation
  - Reference shared context keys in the task string rather than
    inlining large amounts of context
  - Collect results promptly and synthesize across multiple agents
  - Define new agents when the task requires a specialist not
    already registered

Do NOT:
  - Delegate tasks you can complete in a single tool call
  - Spawn multiple agents for the same task (redundant work)
  - Pass raw data in the task string (use shared context)
  - Assume the subagent knows your conversation history —
    provide context explicitly via shared context or the task string
  - Define agents with overly broad system prompts — focus on
    the specific capability needed
```

### 6.3 Composition with Shared Context

```
Subagents and shared context work together:

  1. BEFORE spawning: Write problem context, scope, and constraints
     to shared context so the subagent can read them.
  2. TASK STRING: Keep it short. Reference shared context keys
     (e.g., "Analyze the issue in problem_summary").
  3. DURING execution: The subagent reads from and writes to
     shared context as part of its work.
  4. AFTER collecting: Read any keys the subagent wrote for
     structured findings. The collect result is a summary;
     shared context has the details.
```

---

## 7. Extensions

These are not part of the core spec but are anticipated needs.

### 7.1 Cancellation

```json
{
  "action": "cancel",
  "task_id": "t_01"
}
```

Terminates a running task early. Returns whatever partial result is available. Useful when the orchestrator determines the task is no longer needed (e.g., another agent already found the answer).

Not in core spec because it complicates the execution model. Implementations that support interruption can add this.

### 7.2 Streaming Progress

Expose intermediate outputs from the subagent as it works. Useful for long-running tasks where the orchestrator wants visibility into progress, not just the final result.

Adds significant complexity. Not recommended for initial implementations.

### 7.3 Agent Inheritance

Define a new agent by extending an existing one:

```json
{
  "action": "define",
  "name": "senior_researcher",
  "extends": "researcher",
  "system_prompt_append": "You are a senior researcher. Validate findings with at least two independent sources.",
  "max_turns": 15
}
```

Useful when multiple agents share a base config. Not in core spec — flat definitions are simpler.

### 7.4 Task Chaining

Declare dependencies between tasks:

```json
{
  "action": "spawn",
  "agent": "writer",
  "task": "Summarize findings",
  "depends_on": ["t_01", "t_02"]
}
```

The writer task starts only after both dependencies complete. Moves toward workflow orchestration, which is explicitly out of scope. The orchestrator can implement this logic with status polling.

### 7.5 Agent Versioning

Track changes to dynamically defined agents. Allow the orchestrator to redefine an agent with an updated config (overwrite semantics, with a version counter). Useful for iterative refinement of agents within a session.

### 7.6 Resource Budgets

Per-task token budgets (input + output) and per-session aggregate budgets. The orchestrator specifies cost constraints, and the implementation enforces them.

```json
{
  "action": "spawn",
  "agent": "researcher",
  "task": "...",
  "max_input_tokens": 50000,
  "max_output_tokens": 5000
}
```

Important for production but adds complexity to the core spec.

---

## 8. Implementation Guidance

### 8.1 Execution Backend

The subagent tool must run a full agent loop for each spawned task. Requirements:

- Support the model specified in the agent config
- Execute tool calls within the subagent's tool list
- Enforce `max_turns` by counting loop iterations
- Capture the final text response as the result
- Handle failures gracefully (model errors, tool errors, turn limit)

For implementations using the Anthropic API: each spawn creates a new `messages` conversation with the agent config's `system_prompt` and the task string as the first user message.

For implementations using the OpenAI API: each spawn creates a new chat completion loop with the agent config's `system` message and the task string as the first user message.

### 8.2 Concurrency Model

Spawned tasks run asynchronously. Implementation options:

- **Threading:** Each task runs in a separate thread. Simple. Suitable for I/O-bound agent loops (waiting on API calls).
- **Async:** Each task is an asyncio coroutine. Better for high concurrency but requires async-compatible tool implementations.
- **Process pool:** Each task in a subprocess. Maximum isolation but higher overhead.

Threading is recommended for initial implementations. Agent loops are I/O-bound (model API calls dominate), so the GIL is not a bottleneck.

### 8.3 Task ID Generation

Task IDs must be unique within a session. Format recommendation:

```
"t_{sequential_counter}"     e.g. "t_01", "t_02", "t_03"
```

Simple, readable, and deterministic. UUIDs are acceptable but less ergonomic for the orchestrator.

### 8.4 Subagent System Prompt Construction

The subagent's system prompt is assembled from:

1. The `system_prompt` from the agent config (primary instructions)
2. An implementation-appended suffix with constraints:

```
You are a subagent. Keep your final response concise (under 1000 tokens).
Write detailed findings to shared context rather than including them
in your response. Your response will be returned to the orchestrator
as a summary of your work.
```

The suffix is added by the implementation, not by the orchestrator. This ensures subagents respect result size limits regardless of the agent config.

### 8.5 Shared Context Integration

If `shared_context` is in the subagent's tool list, the subagent receives the same `SharedContextStore` instance as the orchestrator. This means:

- Writes by the subagent are immediately visible to the orchestrator (after the subagent completes) and to other subagents.
- The `written_by` field uses the subagent's participant identity (see §8.6).
- No special wiring is needed — the subagent calls `shared_context` like any other tool.

### 8.6 Participant Identity

Subagents are automatically assigned a participant identity for shared context:

```
"subagent:{agent_name}"              e.g. "subagent:researcher"
"subagent:{agent_name}:{task_id}"    e.g. "subagent:researcher:t_01"
```

This aligns with the participant identity convention in the Shared Context spec (§8.3). The orchestrator uses `"orchestrator"`.

### 8.7 Failure Modes

Tasks can fail for several reasons. Each produces a `"failed"` status with a descriptive error:

| Failure | Error message |
|---------|--------------|
| Turn limit | "Max turns exceeded without producing a final response" |
| Model API error | "Model API error: {details}" |
| Tool execution error | "Tool execution error in turn {n}: {details}" |
| Result too large (after truncation) | Should not fail — truncate and append notice |

Failed tasks are still collected via `collect`. The orchestrator receives the error and decides whether to retry, delegate to a different agent, or handle the failure.

### 8.8 Observability

Log all spawn, status, and collect operations with:
- session_id
- task_id
- agent name
- action
- timestamp
- turns_used (for collect)
- status

Log subagent tool calls at the same level as orchestrator tool calls, tagged with the task_id for correlation.

Do NOT log task strings or results by default (may contain sensitive content). Provide a debug mode that logs full payloads.

---

## 9. Anti-Patterns

### 9.1 Over-Delegation

Delegating trivial tasks that the orchestrator could handle in a single tool call. Each spawn incurs model inference cost and latency. Only delegate when the task requires multiple reasoning steps, specialized tools, or focused attention that would distract the orchestrator.

### 9.2 Context Duplication

Passing the same information in both the task string and shared context. The task string should reference shared context keys, not duplicate their contents. Duplication wastes tokens and creates drift risk.

### 9.3 Fire-and-Forget

Spawning tasks and never collecting results. Even if the orchestrator doesn't need the result text, it should collect to free resources and confirm completion. Uncollected tasks remain in active tracking and count toward the concurrent task limit until the session ends.

### 9.4 Mega-Agents

Defining agents with extremely broad system prompts and many tools. This recreates the orchestrator as a subagent. Agents should be narrow specialists — each with a focused system prompt and a small set of relevant tools.

### 9.5 Nesting Workarounds

Attempting to simulate nesting by having a subagent write a delegation request to shared context for the orchestrator to pick up. This creates implicit control flow that is hard to debug and reason about. If a task requires multi-level delegation, decompose it at the orchestrator level.

### 9.6 Polling Storms

Calling `status` in a tight loop. The orchestrator should do other useful work between status checks, or use a reasonable polling interval. Implementations may rate-limit status calls if abuse is detected.

---

## 10. Example: Full Interaction Cycle

An orchestrator investigates a production issue using two specialists, coordinating via shared context and the subagent tool.

```
ORCHESTRATOR:
  # Set up context for the investigation
  shared_context(action="write", key="problem_summary",
    value="Throughput dropped 30% after config change on Feb 18.")
  shared_context(action="write", key="scope",
    value="Identify root cause. Read-only access to production.")

  # Check available agents
  subagent(action="list_agents")
  → [researcher, writer]

  # Spawn the investigator
  subagent(action="spawn", agent="researcher",
    task="Investigate the problem described in problem_summary.
          Check connection pool settings and thread utilization.
          Write findings to shared context key findings_summary.")
  → {"task_id": "t_01", "status": "running"}

  # Orchestrator does other work while researcher runs...
  subagent(action="status", task_id="t_01")
  → {"status": "running", "turns_used": 4}

  subagent(action="status", task_id="t_01")
  → {"status": "completed", "turns_used": 7}

  # Collect the summary
  subagent(action="collect", task_id="t_01")
  → {"result": "Root cause identified: connection pool reduced from
      200 to 20 in Feb 18 config change. Thread starvation confirmed
      in staging. Details in shared context.", "turns_used": 7}

  # Read the detailed findings from shared context
  shared_context(action="read", key="findings_summary")
  → detailed structured findings written by the researcher

  # Surface question to user
  shared_context(action="read", key="open_questions")
  → "Was the pool size change intentional?"

USER: "No, that was accidental."

ORCHESTRATOR:
  shared_context(action="write", key="decisions_made",
    value="Config change was accidental. User approves revert.")
  shared_context(action="delete", key="open_questions")

  # Define a remediation agent on the fly
  subagent(action="define",
    name="remediator",
    description="Executes remediation steps in staging and production",
    system_prompt="You are a remediation specialist. Read the findings
      and decisions from shared context, then execute the approved fix.
      Verify the fix resolves the issue. Write results to shared context.",
    tools=["shared_context", "run_staging_command", "update_config"],
    max_turns=15)
  → {"defined": "remediator"}

  # Spawn remediation and report drafting in parallel
  subagent(action="spawn", agent="remediator",
    task="Execute the approved revert per decisions_made.
          Verify throughput recovery in staging before prod.")
  → {"task_id": "t_02", "status": "running"}

  subagent(action="spawn", agent="writer",
    task="Draft an incident summary for stakeholders based on
          findings_summary and decisions_made in shared context.")
  → {"task_id": "t_03", "status": "running"}

  # Poll both
  subagent(action="status", task_id="t_02") → {"status": "running"}
  subagent(action="status", task_id="t_03") → {"status": "completed"}

  subagent(action="collect", task_id="t_03")
  → {"result": "Incident summary drafted and written to shared context
      key incident_report.", "turns_used": 3}

  subagent(action="status", task_id="t_02") → {"status": "completed"}

  subagent(action="collect", task_id="t_02")
  → {"result": "Config reverted in staging. Throughput recovered to
      baseline. Ready for production deployment pending approval.",
      "turns_used": 8}

  # Read the structured outputs
  shared_context(action="read", key="incident_report")
  shared_context(action="read", key="remediation_status")

  → Presents incident report and remediation status to user
```

Key observations:
- The researcher subagent did the investigation work (7 turns) without the orchestrator needing to manage each step.
- The orchestrator defined a new agent (`remediator`) on the fly because no pre-registered agent matched the need.
- The writer and remediator ran in parallel — the orchestrator spawned both, then polled until done.
- Shared context was the coordination layer: the orchestrator wrote context before spawning, subagents wrote findings, and the orchestrator read results after collecting.
- The orchestrator remained the single point of coordination throughout.

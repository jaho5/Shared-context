"""Example: Multi-agent orchestration with shared context.

Shows the core pattern: orchestrator pre-populates context, launches
subagents sequentially, each reads what it needs and writes its output.
Subagent 2 picks up where subagent 1 left off — zero re-investigation.

This example uses OpenAI. Swap imports to use Anthropic instead.

Run with:
    export OPENAI_API_KEY=sk-...
    python examples/multi_agent.py
"""

from openai import OpenAI
from shared_context import SharedContextStore
from shared_context.openai import tool_definition, process_response

client = OpenAI()
store = SharedContextStore("multi-agent-demo", storage_path="./demo_session/multi.json")


def run_agent(task: str, participant: str, system: str) -> str:
    """Run a single agent to completion. Returns the final text response."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]

    while True:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=[tool_definition()],
        )
        new_messages, done = process_response(
            response, store, participant=participant
        )
        messages.extend(new_messages)
        if done:
            return new_messages[0].get("content", "")


AGENT_SYSTEM = """\
You have access to a shared_context tool (key-value working memory).
Always call list_keys first, then read keys relevant to your task.
Write your conclusions back to shared context when done.
Be concise. Store distilled findings, not raw data.
"""

# --- Orchestrator: set up the problem ---
print("=== Orchestrator: setting up context ===\n")
store.write("current_phase", "investigation", written_by="orchestrator")
store.write(
    "problem_summary",
    "Throughput dropped 30% after config change on Feb 18.",
    written_by="orchestrator",
)
store.write(
    "scope",
    "Identify which config parameter caused degradation. Do not modify production.",
    written_by="orchestrator",
)
store.write(
    "constraints",
    "Read-only access to prod. Staging available for experiments.",
    written_by="orchestrator",
)

# --- Subagent 1: investigation ---
print("=== Subagent 1: investigation ===\n")
result = run_agent(
    task=(
        "Read the shared context to understand the problem. "
        "Investigate and write your findings to shared context. "
        "If you have questions for the user, write them to open_questions."
    ),
    participant="subagent:investigation",
    system=AGENT_SYSTEM,
)
print(f"Investigation agent: {result}\n")

# --- Orchestrator: check findings, simulate user decision ---
print("=== Orchestrator: processing findings ===\n")
store.write(
    "decisions_made",
    "Config change was accidental. User approves revert recommendation.",
    written_by="orchestrator",
)
store.write("current_phase", "remediation", written_by="orchestrator")

# --- Subagent 2: remediation ---
print("=== Subagent 2: remediation ===\n")
result = run_agent(
    task=(
        "Read the shared context. A decision has been made. "
        "Draft a remediation plan and write it to shared context as remediation_plan."
    ),
    participant="subagent:remediation",
    system=AGENT_SYSTEM,
)
print(f"Remediation agent: {result}\n")

# --- Final state ---
print("=== Final shared context state ===\n")
for key_info in store.list_keys()["keys"]:
    entry = store.read(key_info["key"])
    print(f"[{entry['key']}] (v{entry['version']}, by {entry['written_by']})")
    print(f"  {entry['value'][:120]}")
    print()

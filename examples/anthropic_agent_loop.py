"""Example: Anthropic agent loop with shared context.

Run with:
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/anthropic_agent_loop.py
"""

from anthropic import Anthropic
from shared_context import SharedContextStore
from shared_context.anthropic import tool_definition, process_response

client = Anthropic()
store = SharedContextStore("demo", storage_path="./demo_session/context.json")

SYSTEM_PROMPT = """\
You are a helpful analyst. You have access to a shared_context tool — a
key-value working memory store.

Before doing any work, call shared_context with action "list_keys" to see
what context is already available. Read relevant keys before starting.
Write your conclusions back to shared context when done.

Shared context key conventions:
  problem_summary    - distilled statement of the problem
  findings_summary   - key findings (distilled, not raw)
  open_questions     - unresolved questions
  decisions_made     - user decisions with brief rationale
"""

# Pre-populate context (as an orchestrator would).
store.write("problem_summary", "API latency spiked 3x after the Feb 19 deploy.", written_by="orchestrator")
store.write("scope", "Identify which change caused the regression. Read-only investigation.", written_by="orchestrator")

messages = [
    {"role": "user", "content": "Check the shared context and summarize what you know so far."},
]

print("Starting agent loop...\n")

while True:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=[tool_definition()],
    )

    new_messages, done = process_response(response, store, participant="subagent:analyst")
    messages.extend(new_messages)

    # Print any text the model produced.
    for block in response.content:
        if hasattr(block, "text"):
            print(f"Assistant: {block.text}\n")

    if done:
        break

print("--- Final shared context state ---")
for key_info in store.list_keys()["keys"]:
    entry = store.read(key_info["key"])
    print(f"\n[{entry['key']}] (v{entry['version']}, by {entry['written_by']})")
    print(f"  {entry['value'][:200]}")

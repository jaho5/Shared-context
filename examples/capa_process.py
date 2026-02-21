"""Example: CAPA process agent configuration.

Configures specialist agents for a Corrective and Preventive Action
(CAPA) workflow — common in pharma, medical devices, and manufacturing.

Each agent maps to a distinct CAPA phase:

    investigator       →  Evidence gathering, record review
    root_cause_analyst →  Root cause analysis (5 Whys, fishbone)
    action_planner     →  Corrective/preventive action design
    verifier           →  Effectiveness verification
    report_writer      →  Final CAPA report for quality review

The orchestrator coordinates the phases, gates transitions on user
approval, and writes decisions to shared context between phases.

Run with:
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/capa_process.py
"""

from anthropic import Anthropic
from shared_context import SharedContextStore
from shared_context.schema import anthropic_tool as sc_tool_def
from subagent import AgentConfig, SubagentTool
from subagent.anthropic import create_runner

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

client = Anthropic()
store = SharedContextStore(
    "capa-demo",
    storage_path="./demo_session/capa.json",
)

runner = create_runner(
    client=client,
    tool_definitions={},
    shared_context_store=store,
)

tool = SubagentTool(
    runner=runner,
    available_tools={"shared_context"},
    max_concurrent=3,
)

# ---------------------------------------------------------------------------
# Agent configurations
# ---------------------------------------------------------------------------

tool.register(AgentConfig(
    name="investigator",
    description="Gathers evidence and reviews records for a CAPA investigation",
    system_prompt=(
        "You are a CAPA investigator in a regulated environment. "
        "Your job is to gather and organize evidence related to a quality event.\n\n"
        "Process:\n"
        "1. Read problem_summary and scope from shared context.\n"
        "2. Identify what records, logs, and observations are relevant.\n"
        "3. Organize findings into a structured evidence summary.\n"
        "4. Write your evidence summary to shared context key 'evidence_summary'.\n"
        "5. List any gaps or open questions in 'investigation_gaps'.\n\n"
        "Be factual. Distinguish observations from interpretations. "
        "Cite specific records, dates, and data points."
    ),
    tools=("shared_context",),
    model="claude-sonnet-4-20250514",
    max_turns=10,
))

tool.register(AgentConfig(
    name="root_cause_analyst",
    description="Performs root cause analysis using structured methods",
    system_prompt=(
        "You are a root cause analysis specialist. "
        "You use structured methods: 5 Whys, fishbone diagrams, "
        "fault tree analysis, and is/is-not analysis.\n\n"
        "Process:\n"
        "1. Read evidence_summary and investigation_gaps from shared context.\n"
        "2. Apply at least two root cause analysis methods.\n"
        "3. Identify the most probable root cause(s).\n"
        "4. Distinguish between root cause, contributing factors, "
        "and symptoms.\n"
        "5. Write analysis to shared context key 'root_cause_analysis'.\n"
        "6. Write the confirmed root cause to 'root_cause'.\n\n"
        "Be rigorous. Each 'why' must be supported by evidence. "
        "Flag assumptions explicitly."
    ),
    tools=("shared_context",),
    model="claude-sonnet-4-20250514",
    max_turns=10,
))

tool.register(AgentConfig(
    name="action_planner",
    description="Designs corrective and preventive actions with timelines",
    system_prompt=(
        "You are a CAPA action planner. You design corrective actions "
        "(fix the immediate problem) and preventive actions "
        "(prevent recurrence).\n\n"
        "Process:\n"
        "1. Read root_cause_analysis and decisions_made from shared context.\n"
        "2. Design corrective action(s) that address the root cause directly.\n"
        "3. Design preventive action(s) that address systemic gaps.\n"
        "4. For each action specify: description, owner role, "
        "target completion, success criteria.\n"
        "5. Write the plan to shared context key 'action_plan'.\n\n"
        "Actions must be specific, measurable, and verifiable. "
        "Avoid vague actions like 'improve training' — specify what, "
        "for whom, by when, and how you will know it worked."
    ),
    tools=("shared_context",),
    model="claude-sonnet-4-20250514",
    max_turns=10,
))

tool.register(AgentConfig(
    name="verifier",
    description="Designs effectiveness checks for CAPA actions",
    system_prompt=(
        "You are a CAPA effectiveness verifier. You design verification "
        "protocols to confirm that corrective and preventive actions "
        "actually work.\n\n"
        "Process:\n"
        "1. Read action_plan from shared context.\n"
        "2. For each action, define a verification method.\n"
        "3. Specify: what to measure, acceptance criteria, "
        "verification timeline, and who performs verification.\n"
        "4. Define what happens if verification fails (escalation path).\n"
        "5. Write the verification plan to 'verification_plan'.\n\n"
        "Verification must be independent of the action owner. "
        "Use objective, measurable criteria — not self-assessment."
    ),
    tools=("shared_context",),
    model="claude-sonnet-4-20250514",
    max_turns=8,
))

tool.register(AgentConfig(
    name="report_writer",
    description="Drafts the final CAPA report for quality review",
    system_prompt=(
        "You are a quality documentation specialist. You draft "
        "CAPA reports for regulatory review.\n\n"
        "Process:\n"
        "1. Read all keys from shared context (list_keys first, "
        "then read each).\n"
        "2. Compile into a structured CAPA report with sections:\n"
        "   - Event Description\n"
        "   - Investigation Summary\n"
        "   - Root Cause Analysis\n"
        "   - Corrective Actions\n"
        "   - Preventive Actions\n"
        "   - Effectiveness Verification Plan\n"
        "   - Decisions and Approvals\n"
        "3. Write the report to 'capa_report'.\n\n"
        "Use clear, precise language. Avoid jargon. "
        "Every claim must trace back to evidence. "
        "The report must be understandable by an auditor "
        "who has no prior context."
    ),
    tools=("shared_context",),
    model="claude-sonnet-4-20250514",
    max_turns=8,
))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_phase(agent: str, task: str) -> dict:
    """Spawn an agent, poll until done, collect result."""
    result = tool.handle({"action": "spawn", "agent": agent, "task": task})
    task_id = result["task_id"]
    print(f"  spawned {agent} → {task_id}")

    import time
    while True:
        status = tool.handle({"action": "status", "task_id": task_id})
        if status["status"] != "running":
            break
        print(f"  {task_id}: running (turns={status['turns_used']})")
        time.sleep(2)

    collected = tool.handle({"action": "collect", "task_id": task_id})
    print(f"  {task_id}: {collected['status']} (turns={collected['turns_used']})")
    return collected


def main() -> None:
    # --- Phase 0: Problem definition (orchestrator) ---
    print("\n=== Phase 0: Problem Definition ===\n")
    store.write(
        "problem_summary",
        "Lot 2024-0847 failed dissolution testing at the 30-minute time point. "
        "3 of 12 tablets fell below 75% (Q) specification. "
        "Lot was quarantined per SOP-QA-042. "
        "Affected product: Metformin HCl 500mg tablets, manufactured 2024-02-15.",
        written_by="orchestrator",
    )
    store.write(
        "scope",
        "Determine root cause of dissolution failure. "
        "Scope limited to Lot 2024-0847 and adjacent lots (0846, 0848). "
        "Manufacturing records, environmental data, and raw material COAs are available.",
        written_by="orchestrator",
    )
    store.write("capa_phase", "investigation", written_by="orchestrator")
    print("  Problem and scope written to shared context.\n")

    # --- Phase 1: Investigation ---
    print("=== Phase 1: Investigation ===\n")
    run_phase(
        "investigator",
        "Read problem_summary and scope from shared context. "
        "Gather and organize all relevant evidence. "
        "Write structured findings to evidence_summary. "
        "Note any gaps in investigation_gaps.",
    )

    # --- Phase 2: Root cause analysis ---
    print("\n=== Phase 2: Root Cause Analysis ===\n")
    store.write("capa_phase", "root_cause_analysis", written_by="orchestrator")
    run_phase(
        "root_cause_analyst",
        "Read evidence_summary from shared context. "
        "Perform root cause analysis using at least two structured methods. "
        "Write analysis to root_cause_analysis and confirmed root cause to root_cause.",
    )

    # --- Gate: user approves root cause before proceeding ---
    print("\n=== Gate: Root Cause Approval ===\n")
    root_cause = store.read("root_cause")
    print(f"  Root cause: {root_cause['value'][:200]}")
    print("  (In production, user would approve/reject here.)")
    store.write(
        "decisions_made",
        "Root cause approved by quality. Proceed to action planning.",
        written_by="orchestrator",
    )

    # --- Phase 3: Action planning ---
    print("\n=== Phase 3: Action Planning ===\n")
    store.write("capa_phase", "action_planning", written_by="orchestrator")
    run_phase(
        "action_planner",
        "Read root_cause_analysis and decisions_made from shared context. "
        "Design corrective and preventive actions. "
        "Write the action plan to action_plan.",
    )

    # --- Phase 4: Verification design (parallel with nothing — but could be) ---
    print("\n=== Phase 4: Verification Design ===\n")
    store.write("capa_phase", "verification", written_by="orchestrator")
    run_phase(
        "verifier",
        "Read action_plan from shared context. "
        "Design effectiveness verification for each action. "
        "Write the verification plan to verification_plan.",
    )

    # --- Phase 5: Report ---
    print("\n=== Phase 5: CAPA Report ===\n")
    store.write("capa_phase", "report", written_by="orchestrator")
    run_phase(
        "report_writer",
        "Read all shared context keys and compile the final CAPA report. "
        "Write the complete report to capa_report.",
    )

    # --- Final state ---
    print("\n=== Final Shared Context ===\n")
    for key_info in store.list_keys()["keys"]:
        entry = store.read(key_info["key"])
        print(f"  [{entry['key']}] v{entry['version']} by {entry['written_by']}")
        print(f"    {entry['value'][:100]}...")
        print()

    tool.shutdown()
    print("Done.\n")


if __name__ == "__main__":
    main()

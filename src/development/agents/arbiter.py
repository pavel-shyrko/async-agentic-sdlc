# Executor FSM — Arbiter agent. Runs only when a cycle is STUCK (repeated rejection); classifies the
# root cause and picks a routing target. Beyond the Developer/QA feedback channels it adds a THIRD route
# — `contract` — so a flawed TechLead contract (not an agent-fixable bug) is repaired via amendment
# instead of looping to the circuit breaker. See pipeline-fsm-loops + the Arbiter ADR.
from src.shared.core.observability import log, log_token_usage
from src.shared.core.config import ARBITER_MODEL
from src.shared.core.models import ArbiterVerdict, GlobalPipelineContext
from src.shared.core.prompts import get_system_prompt, build_agent_context
from src.shared.utils.llm import run_structured_llm


async def run_arbiter_node(
    ctx: GlobalPipelineContext,
    gate_output: str = "",
    prev_dev_trace: str = "",
    prev_qa_trace: str = "",
) -> None:
    """Triage a stuck cycle into an ArbiterVerdict (route + reasoning [+ amendment directive])."""
    model_name = ARBITER_MODEL
    log.info(f"⚖️  [ROLE] Arbiter Agent | [MODEL] {model_name}")

    production_code = "\n\n".join(
        f"=== FILE: {p} ===\n{c}" for p, c in ctx.production_code_snapshot.items()
    ) or "No production code captured."
    review = ctx.review_report.model_dump_json(indent=2) if ctx.review_report else "None"

    user_content = (
        "A pipeline cycle FAILED again after a prior fix attempt. Classify the root cause and route it.\n\n"
        f"=== ARCHITECT CONTRACT ===\n{ctx.contract.model_dump_json(indent=2)}\n\n"
        f"=== REVIEWER REPORT (this cycle) ===\n{review}\n\n"
        f"=== PRIOR DEVELOPER FIX INSTRUCTION (last cycle) ===\n{prev_dev_trace or 'None'}\n\n"
        f"=== PRIOR QA FIX INSTRUCTION (last cycle) ===\n{prev_qa_trace or 'None'}\n\n"
        f"=== GATE / RUNNER OUTPUT ===\n{gate_output or 'None'}\n\n"
        f"=== GENERATED PRODUCTION CODE ===\n{production_code}\n\n"
        f"=== GENERATED TEST SUITE ===\n{ctx.test_code_snapshot}\n\n"
        f"=== CONTRACT AMENDMENTS ALREADY APPLIED ===\n{ctx.contract_amendments}"
    )

    sys_prompt = get_system_prompt("arbiter") + "\n\n" + await build_agent_context("arbiter", ctx)

    verdict, raw_response = await run_structured_llm(
        "arbiter",
        ArbiterVerdict,
        [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    ctx.arbiter_verdict = verdict
    log_token_usage(ctx.telemetry, "Arbiter Agent", raw_response, ARBITER_MODEL)

    log.info(f"   [VERDICT] root_cause={verdict.root_cause_class} | route={verdict.route}")
    log.info(f"   [THOUGHT] {verdict.reasoning}")
    if verdict.contract_amendment_directive:
        log.info(f"   [AMENDMENT] {verdict.contract_amendment_directive}")
    log.debug(f"Arbiter Node Output: {verdict.model_dump_json(indent=2)}")

"""Render evaluation metrics from results.json into README.md and RESULTS.md.

Every number comes from results.json. A section with no data says "not measured yet".
"""

import json
import re
from pathlib import Path

START_MARKER = "<!-- RESULTS:START -->"
END_MARKER = "<!-- RESULTS:END -->"

NOT_MEASURED = "_Not measured yet. Put your PDFs in `data/corpus/`, configure an LLM provider, and run `make eval`._"


def status(value: float | None, op: str, target: float) -> str:
    if value is None:
        return "-"
    ok = value >= target if op == ">=" else value <= target
    return "PASS" if ok else "FAIL"


def fmt(value, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def verifier_section(stage_one: dict, two_stage: dict) -> list[str]:
    lines = ["### 1. Claim verifier (stage 1 deterministic checks, then LLM entailment)"]
    if two_stage:
        ci = two_stage.get("accuracy_ci_95") or two_stage.get("bootstrap_95_ci") or []
        ci_str = f"[{ci[0]:.4f}, {ci[1]:.4f}]" if len(ci) == 2 else "n/a"
        p, r, far = (two_stage.get(k) for k in ("precision", "recall", "false_acceptance_rate"))
        lines += [
            "| Metric | Value | Release target | Status |",
            "| :--- | :--- | :--- | :--- |",
            f"| Precision | {fmt(p)} | >= 0.9500 | {status(p, '>=', 0.95)} |",
            f"| Recall | {fmt(r)} | >= 0.8500 | {status(r, '>=', 0.85)} |",
            f"| F1 | {fmt(two_stage.get('f1'))} | - | - |",
            f"| False acceptance rate | {fmt(far)} | <= 0.0200 | {status(far, '<=', 0.02)} |",
            f"| False rejection rate | {fmt(two_stage.get('false_rejection_rate'))} | - | - |",
            f"| Accuracy 95% CI (bootstrap) | {ci_str} | - | - |",
        ]
    else:
        lines.append("_Two-stage verifier not run yet. Configure an LLM provider and run `make eval`._")
    if stage_one:
        # No targets here: stage 1 only rejects what it can prove wrong and leaves the rest to the LLM stage.
        lines += [
            "",
            "Stage 1 alone (numbers, units, dates, polarity, entities; no LLM):",
            "",
            "| Precision | Recall | False acceptance rate | False rejection rate |",
            "| :--- | :--- | :--- | :--- |",
            "| " + " | ".join(fmt(stage_one.get(k)) for k in ("precision", "recall", "false_acceptance_rate", "false_rejection_rate")) + " |",
        ]
    return lines


def ablation_section(ablations: dict) -> list[str]:
    if not ablations:
        return ["### 3. Retrieval and grounding ablations", NOT_MEASURED]
    lines = [
        "### 3. Retrieval and grounding ablations (dev split)",
        "| ID | Architecture | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | Citation precision | Abstention | p95 latency (ms) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for exp_id, a in ablations.items():
        lines.append(
            f"| {exp_id} | {a.get('description', exp_id)} | {fmt(a.get('recall_at_5'))} | {fmt(a.get('recall_at_10'))} | "
            f"{fmt(a.get('mrr_at_10'))} | {fmt(a.get('ndcg_at_10'))} | {fmt(a.get('citation_precision'))} | "
            f"{fmt(a.get('abstention_accuracy'))} | {fmt(a.get('p95_latency_ms'), 1)} |"
        )
    return lines


def agent_section(agent: dict) -> list[str]:
    if not agent:
        return ["### 4. Single-shot (E7) vs Report Agent (E8)", NOT_MEASURED]
    lines = [
        f"### 4. Single-shot (E7) vs Report Agent (E8), {agent.get('n_questions', 0)} multi-hop/comparative questions",
        "| System | Keyword coverage | Verified claim rate | Abstention | Avg steps | Budget-stop rate | p95 latency (ms) | Cost / answer ($) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for key in ("single_shot_e7", "report_agent_e8"):
        s = agent.get(key, {})
        lines.append(
            f"| {s.get('system', key)} | {fmt(s.get('answer_keyword_coverage'))} | {fmt(s.get('verified_claim_rate'))} | "
            f"{fmt(s.get('abstention_accuracy'))} | {fmt(s.get('avg_steps'), 1)} | {fmt(s.get('budget_stop_rate'))} | "
            f"{fmt(s.get('p95_latency_ms'), 1)} | {fmt(s.get('cost_per_answer_usd'), 6)} |"
        )
    return lines


MIN_QUESTIONS, MIN_PAIRS = 50, 175  # Project.txt section 7 dataset targets


def sample_warning(summary: dict) -> list[str]:
    q, p = summary.get("total_golden_questions", 0), summary.get("total_verifier_pairs", 0)
    if q >= MIN_QUESTIONS and p >= MIN_PAIRS:
        return []
    return [
        f"> **Small sample.** {q} golden questions (target {MIN_QUESTIONS}+) and {p} verifier pairs (target {MIN_PAIRS}+). "
        "Treat these numbers as a smoke test, not as evidence.",
        "",
    ]


def format_results_markdown(data: dict) -> str:
    summary = data.get("summary", {})
    lines = [
        START_MARKER,
        f"_Last updated: {data.get('timestamp', 'N/A')} (golden questions: {summary.get('total_golden_questions', 0)}, "
        f"verifier pairs: {summary.get('total_verifier_pairs', 0)})_",
        "",
        *sample_warning(summary),
        *verifier_section(data.get("verifier", {}), data.get("verifier_two_stage", {})),
        "",
        "### 2. Golden set category distribution",
        "| Category | Count |",
        "| :--- | :--- |",
        *[f"| {cat} | {count} |" for cat, count in data.get("categories", {}).items()],
        "",
        *ablation_section(data.get("ablations", {})),
        "",
        *agent_section(data.get("agent_benchmark", {})),
        END_MARKER,
    ]
    return "\n".join(lines)


def render_to_file(file_path: Path, rendered_block: str) -> bool:
    """Replace content between markers in the given file."""
    if not file_path.exists():
        return False
    content = file_path.read_text(encoding="utf-8")
    pattern = re.compile(f"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL)
    if not pattern.search(content):
        return False
    file_path.write_text(pattern.sub(lambda _: rendered_block, content), encoding="utf-8")
    return True


def main(results_path: str = "results/results.json", target_files: list[str] | None = None):
    res_file = Path(results_path)
    if not res_file.exists():
        raise FileNotFoundError(f"Results file not found at {results_path}. Run `make eval` first.")
    rendered = format_results_markdown(json.loads(res_file.read_text(encoding="utf-8")))
    for target in target_files or ["README.md", "RESULTS.md"]:
        if render_to_file(Path(target), rendered):
            print(f"Updated results block in {target}")
        else:
            print(f"Warning: markers not found or file missing: {target}")


if __name__ == "__main__":
    main()

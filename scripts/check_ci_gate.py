"""CI quality gate: fail the build when a measured metric misses its release target (Project.txt section 7).

The false-acceptance rate of the full two-stage verifier is required. CI has no LLM key, so the gate
reads the number `make eval` committed to results.json; stage 1 alone hands hard negatives to the LLM
stage by design and has no target. Retrieval and grounding metrics are checked only when results.json
contains them, and the gate says so when it skips one. It never passes a number it was not given.
"""

import json
import sys
from pathlib import Path

# (path into results.json, comparison, target, required in CI)
TARGETS = [
    ("verifier_two_stage.false_acceptance_rate", "<=", 0.02, True),
    ("ablations.E3.recall_at_10", ">=", 0.85, False),
    ("ablations.E7.citation_precision", ">=", 0.95, False),
    ("ablations.E7.p95_latency_ms", "<=", 12000.0, False),
]


def lookup(data: dict, dotted: str):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def check_ci_gate(results_path: str = "results/results.json") -> bool:
    path = Path(results_path)
    if not path.exists():
        print(f"CI Gate Error: results file not found at {results_path}. Run `make eval` first.")
        return False
    data = json.loads(path.read_text(encoding="utf-8"))

    passed = True
    for key, op, target, required in TARGETS:
        value = lookup(data, key)
        if value is None:
            if required:
                print(f"CI Gate FAILURE: {key} is missing from results.")
                passed = False
            else:
                print(f"CI Gate Skip: {key} not measured in this run.")
            continue
        ok = value <= target if op == "<=" else value >= target
        print(f"CI Gate {'PASS' if ok else 'FAILURE'}: {key} = {value} (target {op} {target})")
        passed = passed and ok

    print("\nCI Gate: all checked targets met." if passed else "\nCI Gate: release targets missed. Build rejected.")
    return passed


if __name__ == "__main__":
    sys.exit(0 if check_ci_gate() else 1)

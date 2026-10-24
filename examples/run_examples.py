#!/usr/bin/env python3
"""Run the public scenarios through validate_pandas.py and evaluator.py.

This demo does not call an LLM. It feeds each scenario's reference query
(standing in for what the agent would generate) through the same
deterministic validation and evaluation scripts the skill uses.

Usage:
    python examples/run_examples.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "open-pandas-solver-xuntla" / "scripts"
SCENARIOS = Path(__file__).resolve().parent / "public_scenarios.json"


def call(script: str, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), json.dumps(payload)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"errors": [{"code": "BAD_OUTPUT", "message": proc.stderr.strip()[-200:]}]}


def main() -> int:
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    print(f"{'task_id':<22} {'valid':<6} {'passed':<7} detail")
    print("-" * 78)
    for sc in scenarios:
        query = sc["reference_query"]
        validation = call("validate_pandas.py", {
            "task_id": sc["task_id"],
            "columns": sc["columns"],
            "rows": sc["rows"],
            "query": query,
            "answer_type": sc["answer_type"],
        })
        result = call("evaluator.py", {
            "task_id": sc["task_id"],
            "scenario": {k: sc[k] for k in ("question", "columns", "rows", "answer_type", "expected")},
            "submission": {"query": query, "answer": None},
            "compare": {"float_tolerance": 1e-6, "order_sensitive": True},
        })
        errors = result.get("errors") or validation.get("errors") or []
        detail = errors[0]["code"] if errors else f"actual={json.dumps(result.get('actual'))}"
        print(f"{sc['task_id']:<22} {str(validation.get('valid')):<6} {str(result.get('passed')):<7} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
open-pandas-solver skill — file-based final output wrapper.

Writes the final Open Track result JSON to the file path specified by
AIASE_RESULT_PATH, or to ./aiase_result.json when the environment variable is
not set. The write is atomic: output is first written to <path>.tmp and then
renamed into place with os.replace().

This script intentionally does not import aiase_contract. After Hermes installs
skills into ~/.hermes/skills/, repo-root modules may not be importable.

Input styles supported:
1. Preferred legacy-compatible style:
   python3 run.py '<JSON_PAYLOAD>'

   JSON payload fields:
   {task_id, query, answer, answer_type, validation, rationale, confidence}

2. Optional flag style:
   python3 run.py --task_id ... --query ... --answer_json ... \
       --answer_type ... --validation_json ... --rationale ... --confidence ...

Hermes is responsible for generating the pandas query and calling
validate_pandas.py before this wrapper. This script does not validate, execute,
repair, or score the pandas query. It only normalizes the final result object
and writes it to the agreed result file.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any


DEFAULT_ANSWER_TYPE = "string"


def resolve_result_path() -> str:
    """Return the result path required by the file-based grading contract."""
    return os.environ.get("AIASE_RESULT_PATH") or os.path.join(os.getcwd(), "aiase_result.json")


def _reject_json_constants(value: str) -> None:
    """Reject NaN/Infinity during json.loads."""
    raise ValueError(f"invalid JSON constant: {value}")


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe value. Non-finite numbers become null."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        safe_dict: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = key if isinstance(key, str) else str(key)
            safe_dict[safe_key] = _json_safe(item)
        return safe_dict
    return str(value)


def _summarize_validation(value: Any) -> dict[str, Any]:
    """Compress validate_pandas.py output into the final contract summary."""
    if not isinstance(value, dict):
        return {"valid": False, "error_count": 1}

    valid = bool(value.get("valid", False))
    errors = value.get("errors", [])

    if isinstance(errors, list):
        error_count = len(errors)
    elif errors:
        error_count = 1
    else:
        error_count = 0

    return {
        "valid": valid,
        "error_count": int(error_count),
    }


def build_contract(obj: dict[str, Any]) -> dict[str, Any]:
    """Build the final Open Track result object."""
    return {
        "task_id": str(obj.get("task_id", "")),
        "query": str(obj.get("query", "")).strip(),
        "answer": _json_safe(obj.get("answer", None)),
        "answer_type": str(obj.get("answer_type", DEFAULT_ANSWER_TYPE)),
        "validation": _summarize_validation(obj.get("validation")),
        "rationale": str(obj.get("rationale", "")),
        "confidence": _clamp_confidence(obj.get("confidence", 0.5)),
    }


def write_result(result: dict[str, Any]) -> str:
    """Atomically write result JSON and return the target path."""
    path = resolve_result_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, allow_nan=False)
    os.replace(tmp, path)
    return path


def _fallback(rationale: str) -> dict[str, Any]:
    return {
        "task_id": "",
        "query": "",
        "answer": None,
        "answer_type": DEFAULT_ANSWER_TYPE,
        "validation": {"valid": False, "errors": [{"code": "WRAPPER_ERROR", "message": rationale}]},
        "rationale": rationale,
        "confidence": 0.0,
    }


def _loads_json_object(raw: str) -> dict[str, Any]:
    payload = json.loads(raw, parse_constant=_reject_json_constants)
    if not isinstance(payload, dict):
        raise ValueError("payload not an object")
    return payload


def _parse_optional_json(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    return json.loads(raw, parse_constant=_reject_json_constants)


def _payload_from_flags(argv: list[str]) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Write Open Pandas Solver result JSON to the agreed result file.")
    parser.add_argument("--task_id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--answer", default=None, help="String answer fallback. Prefer --answer_json for non-string answers.")
    parser.add_argument("--answer_json", default=None, help="JSON-encoded answer value.")
    parser.add_argument("--answer_type", default=DEFAULT_ANSWER_TYPE)
    parser.add_argument("--validation_json", default=None, help="JSON-encoded validate_pandas.py output.")
    parser.add_argument("--rationale", default="")
    parser.add_argument("--confidence", type=float, default=0.5)
    args = parser.parse_args(argv)

    if args.answer_json is not None:
        answer = _parse_optional_json(args.answer_json, None)
    else:
        answer = args.answer

    validation = _parse_optional_json(args.validation_json, None)

    return {
        "task_id": args.task_id,
        "query": args.query,
        "answer": answer,
        "answer_type": args.answer_type,
        "validation": validation,
        "rationale": args.rationale,
        "confidence": args.confidence,
    }


def parse_payload(argv: list[str]) -> dict[str, Any]:
    if len(argv) < 2:
        return _fallback("run.py invoked without argv payload")

    # Legacy-compatible single JSON argv mode.
    if len(argv) == 2:
        raw = argv[1]
        if raw.lstrip().startswith("{"):
            try:
                return _loads_json_object(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                return _fallback(f"invalid argv JSON: {exc}")

    # Optional argparse mode for consistency with file-based starter examples.
    try:
        return _payload_from_flags(argv[1:])
    except SystemExit:
        # argparse already printed usage to stderr; still produce a result file.
        return _fallback("invalid command-line arguments")
    except (json.JSONDecodeError, ValueError) as exc:
        return _fallback(f"invalid command-line JSON argument: {exc}")


def main(argv: list[str]) -> int:
    payload = parse_payload(argv)
    result = build_contract(payload)
    path = write_result(result)
    print(f"written ok -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

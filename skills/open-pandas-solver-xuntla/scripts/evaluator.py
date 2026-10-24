#!/usr/bin/env python3
"""
evaluator.py

Deterministic scenario evaluator for the Open Track Pandas Solver skill.

Purpose:
- Accept exactly one JSON payload as argv[1].
- Read a scenario with {question, columns, rows, answer_type, expected}.
- Read a submission with {query, answer}.
- Validate the submitted pandas expression by reusing validate_pandas.py.
- Re-execute the validated query over the scenario DataFrame.
- Normalize the full actual result, normalize the expected result, and compare them.
- Print one plain JSON object to stdout.

This script is the Open Track metric implementation. It does not call Hermes,
repair queries, trust submission.answer, or print a fenced JSON block.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import pandas as pd
except Exception as exc:  # pragma: no cover - dependency should be installed
    pd = None  # type: ignore[assignment]
    _PANDAS_IMPORT_ERROR = exc
else:
    _PANDAS_IMPORT_ERROR = None

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is expected via requirements.txt
    np = None  # type: ignore[assignment]

try:
    import validate_pandas
except Exception as exc:  # pragma: no cover - same-directory import should work
    validate_pandas = None  # type: ignore[assignment]
    _VALIDATOR_IMPORT_ERROR = exc
else:
    _VALIDATOR_IMPORT_ERROR = None


ANSWER_TYPES = {"number", "string", "boolean", "list", "dict", "table"}
DEFAULT_FLOAT_TOLERANCE = 1e-6
DEFAULT_ORDER_SENSITIVE = True


Error = Dict[str, str]
JsonObject = Dict[str, Any]


def _reject_json_constants(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _error(code: str, message: str) -> Error:
    return {"code": code, "message": message}


def _print_json(obj: JsonObject) -> None:
    print(json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def _safe_json(value: Any) -> Any:
    """Convert values to JSON-safe objects. Non-finite numbers become null."""
    value = _to_python_scalar(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        return [_safe_json(item) for item in value]
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, dict):
        return {str(_safe_json(key)): _safe_json(item) for key, item in value.items()}
    if pd is not None and isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _base_output(
    task_id: Optional[str],
    passed: bool,
    score: float,
    validation: Optional[JsonObject],
    actual: Any,
    expected: Any,
    answer_type: Optional[str],
    errors: List[Error],
) -> JsonObject:
    return {
        "task_id": task_id,
        "passed": bool(passed),
        "score": float(score),
        "validation": _summarize_validation(validation),
        "actual": _safe_json(actual),
        "expected": _safe_json(expected),
        "answer_type": answer_type,
        "errors": errors,
    }


def _summarize_validation(validation: Optional[JsonObject]) -> JsonObject:
    if not isinstance(validation, dict):
        return {"valid": False, "errors": []}
    return {
        "valid": bool(validation.get("valid", False)),
        "errors": validation.get("errors", []) if isinstance(validation.get("errors", []), list) else [],
    }


def _parse_payload(argv: Sequence[str]) -> Tuple[Optional[JsonObject], Optional[JsonObject]]:
    if len(argv) < 2:
        return None, _base_output(
            None,
            False,
            0.0,
            None,
            None,
            None,
            None,
            [_error("MISSING_FIELD", "Expected one JSON payload as argv[1].")],
        )
    if len(argv) > 2:
        return None, _base_output(
            None,
            False,
            0.0,
            None,
            None,
            None,
            None,
            [_error("INVALID_JSON", "Expected exactly one JSON payload argument.")],
        )

    try:
        payload = json.loads(argv[1], parse_constant=_reject_json_constants)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, _base_output(
            None,
            False,
            0.0,
            None,
            None,
            None,
            None,
            [_error("INVALID_JSON", f"Invalid JSON payload: {exc}.")],
        )

    if not isinstance(payload, dict):
        return None, _base_output(
            None,
            False,
            0.0,
            None,
            None,
            None,
            None,
            [_error("INVALID_TOP_LEVEL", "Top-level JSON value must be an object.")],
        )
    return payload, None


def _validate_evaluator_schema(payload: JsonObject) -> Tuple[Optional[JsonObject], List[Error]]:
    errors: List[Error] = []

    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        errors.append(_error("INVALID_TASK_ID", "task_id must be a non-empty string."))

    scenario = payload.get("scenario")
    if not isinstance(scenario, dict):
        errors.append(_error("INVALID_SCENARIO", "scenario must be an object."))
        scenario = {}

    submission = payload.get("submission")
    if not isinstance(submission, dict):
        errors.append(_error("INVALID_SUBMISSION", "submission must be an object."))
        submission = {}

    compare = payload.get("compare", {})
    if compare is None:
        compare = {}
    if not isinstance(compare, dict):
        errors.append(_error("INVALID_COMPARE", "compare must be an object if provided."))
        compare = {}

    question = scenario.get("question")
    if not isinstance(question, str):
        errors.append(_error("INVALID_SCENARIO", "scenario.question must be a string."))

    columns = scenario.get("columns")
    if not isinstance(columns, list) or not all(isinstance(item, str) for item in columns):
        errors.append(_error("INVALID_SCENARIO", "scenario.columns must be an array of strings."))

    rows = scenario.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        errors.append(_error("INVALID_SCENARIO", "scenario.rows must be an array of arrays."))

    answer_type = scenario.get("answer_type")
    if not isinstance(answer_type, str) or answer_type not in ANSWER_TYPES:
        errors.append(
            _error(
                "INVALID_SCENARIO",
                "scenario.answer_type must be one of: " + ", ".join(sorted(ANSWER_TYPES)) + ".",
            )
        )

    if "expected" not in scenario:
        errors.append(_error("MISSING_FIELD", "scenario.expected is required."))

    query = submission.get("query")
    if not isinstance(query, str):
        errors.append(_error("INVALID_SUBMISSION", "submission.query must be a string."))

    float_tolerance = compare.get("float_tolerance", DEFAULT_FLOAT_TOLERANCE)
    try:
        float_tolerance = float(float_tolerance)
    except (TypeError, ValueError):
        errors.append(_error("INVALID_COMPARE", "compare.float_tolerance must be a finite non-negative number."))
        float_tolerance = DEFAULT_FLOAT_TOLERANCE
    if not math.isfinite(float_tolerance) or float_tolerance < 0:
        errors.append(_error("INVALID_COMPARE", "compare.float_tolerance must be a finite non-negative number."))
        float_tolerance = DEFAULT_FLOAT_TOLERANCE

    order_sensitive = compare.get("order_sensitive", DEFAULT_ORDER_SENSITIVE)
    if not isinstance(order_sensitive, bool):
        errors.append(_error("INVALID_COMPARE", "compare.order_sensitive must be a boolean if provided."))
        order_sensitive = DEFAULT_ORDER_SENSITIVE

    if errors:
        return None, errors

    assert isinstance(task_id, str)
    assert isinstance(columns, list)
    assert isinstance(rows, list)
    assert isinstance(answer_type, str)
    assert isinstance(query, str)

    return {
        "task_id": task_id,
        "question": question,
        "columns": columns,
        "rows": rows,
        "answer_type": answer_type,
        "expected": scenario.get("expected"),
        "query": query,
        "submission_answer": submission.get("answer"),
        "float_tolerance": float_tolerance,
        "order_sensitive": order_sensitive,
    }, []


def _to_python_scalar(value: Any) -> Any:
    if np is not None and isinstance(value, np.generic):
        return value.item()
    return value


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite number is not valid JSON.")


def _normalize_json_value(value: Any) -> Any:
    value = _to_python_scalar(value)

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        _reject_non_finite(value)
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(_normalize_json_value(key)): _normalize_json_value(item) for key, item in value.items()}
    if pd is not None and isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd is not None:
        try:
            if pd.isna(value):
                raise ValueError("NaN/NA value is not valid JSON.")
        except (TypeError, ValueError):
            raise
        except Exception:
            pass
    raise TypeError(f"Value is not JSON-serializable after normalization: {type(value).__name__}.")


def _normalize_result(value: Any, answer_type: str) -> Tuple[str, Any]:
    """Normalize a full actual or expected value according to answer_type."""
    value = _to_python_scalar(value)

    if pd is not None and isinstance(value, pd.DataFrame):
        if answer_type not in {"table", "list"}:
            raise TypeError(f"DataFrame result is not compatible with answer_type={answer_type}.")
        records = value.to_dict(orient="records")
        return "table", _normalize_json_value(records)

    if pd is not None and isinstance(value, pd.Series):
        if answer_type == "dict":
            return "dict", _normalize_json_value(value.to_dict())
        if answer_type == "list":
            return "list", _normalize_json_value(value.tolist())
        raise TypeError(f"Series result is not compatible with answer_type={answer_type}.")

    if pd is not None and isinstance(value, pd.Index):
        if answer_type != "list":
            raise TypeError(f"Index result is not compatible with answer_type={answer_type}.")
        return "list", _normalize_json_value(list(value))

    if isinstance(value, dict):
        if answer_type != "dict":
            raise TypeError(f"dict result is not compatible with answer_type={answer_type}.")
        return "dict", _normalize_json_value(value)

    if isinstance(value, (list, tuple)):
        if answer_type == "table":
            normalized = _normalize_json_value(list(value))
            if not all(isinstance(row, dict) for row in normalized):
                raise TypeError("table result must normalize to a list of records.")
            return "table", normalized
        if answer_type != "list":
            raise TypeError(f"list result is not compatible with answer_type={answer_type}.")
        return "list", _normalize_json_value(list(value))

    if isinstance(value, bool):
        if answer_type != "boolean":
            raise TypeError(f"boolean result is not compatible with answer_type={answer_type}.")
        return "boolean", value

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if answer_type != "number":
            raise TypeError(f"number result is not compatible with answer_type={answer_type}.")
        _reject_non_finite(value)
        return "number", value

    if isinstance(value, str):
        if answer_type != "string":
            raise TypeError(f"string result is not compatible with answer_type={answer_type}.")
        return "string", value

    if value is None:
        if answer_type not in {"number", "string", "boolean"}:
            raise TypeError(f"None result is not compatible with answer_type={answer_type}.")
        return answer_type, None

    raise TypeError(f"Unsupported result type: {type(value).__name__}.")


def _compare_values(actual: Any, expected: Any, answer_type: str, tolerance: float, order_sensitive: bool) -> bool:
    if answer_type == "number":
        if actual is None or expected is None:
            return actual is expected
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False
        if not isinstance(expected, (int, float)) or isinstance(expected, bool):
            return False
        if not math.isfinite(float(actual)) or not math.isfinite(float(expected)):
            return False
        return abs(float(actual) - float(expected)) <= tolerance

    if answer_type in {"string", "boolean"}:
        return actual == expected

    if answer_type == "dict":
        return _compare_dicts(actual, expected, tolerance)

    if answer_type == "list":
        return _compare_lists(actual, expected, tolerance, order_sensitive)

    if answer_type == "table":
        # First version keeps table comparison order-sensitive.
        return _compare_lists(actual, expected, tolerance, True)

    return actual == expected


def _compare_dicts(actual: Any, expected: Any, tolerance: float) -> bool:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False
    if set(actual.keys()) != set(expected.keys()):
        return False
    for key in actual:
        if not _compare_any(actual[key], expected[key], tolerance):
            return False
    return True


def _compare_lists(actual: Any, expected: Any, tolerance: float, order_sensitive: bool) -> bool:
    if not isinstance(actual, list) or not isinstance(expected, list):
        return False
    if len(actual) != len(expected):
        return False
    if order_sensitive:
        return all(_compare_any(a, e, tolerance) for a, e in zip(actual, expected))

    used = [False] * len(expected)
    for item in actual:
        matched = False
        for idx, candidate in enumerate(expected):
            if used[idx]:
                continue
            if _compare_any(item, candidate, tolerance):
                used[idx] = True
                matched = True
                break
        if not matched:
            return False
    return True


def _compare_any(actual: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        if not isinstance(expected, (int, float)) or isinstance(expected, bool):
            return False
        if not math.isfinite(float(actual)) or not math.isfinite(float(expected)):
            return False
        return abs(float(actual) - float(expected)) <= tolerance
    if isinstance(actual, dict) or isinstance(expected, dict):
        return _compare_dicts(actual, expected, tolerance)
    if isinstance(actual, list) or isinstance(expected, list):
        return _compare_lists(actual, expected, tolerance, True)
    return actual == expected


def _execute_query(data: JsonObject) -> Tuple[Optional[Any], List[Error]]:
    if pd is None:
        return None, [_error("EXECUTION_ERROR", f"Failed to import pandas: {_PANDAS_IMPORT_ERROR}")]
    if validate_pandas is None:
        return None, [_error("EXECUTION_ERROR", f"Failed to import validate_pandas.py: {_VALIDATOR_IMPORT_ERROR}")]

    try:
        collector = validate_pandas.ValidationErrorCollector()
        df = validate_pandas.build_dataframe(data["columns"], data["rows"], collector)
        if df is None or not collector.ok:
            return None, collector.errors or [_error("INVALID_SCENARIO", "Failed to build DataFrame.")]
        return validate_pandas.safe_eval(data["query"].strip(), df), []
    except KeyError as exc:
        return None, [_error("UNKNOWN_COLUMN", f"Unknown column at execution time: {exc}.")]
    except Exception as exc:
        return None, [_error("EXECUTION_ERROR", f"{type(exc).__name__}: {exc}")]


def evaluate(payload: JsonObject) -> JsonObject:
    data, schema_errors = _validate_evaluator_schema(payload)
    task_id = payload.get("task_id") if isinstance(payload.get("task_id"), str) else None

    if schema_errors or data is None:
        return _base_output(task_id, False, 0.0, None, None, None, None, schema_errors)

    task_id = data["task_id"]
    answer_type = data["answer_type"]

    if validate_pandas is None:
        return _base_output(
            task_id,
            False,
            0.0,
            None,
            None,
            data.get("expected"),
            answer_type,
            [_error("EXECUTION_ERROR", f"Failed to import validate_pandas.py: {_VALIDATOR_IMPORT_ERROR}")],
        )

    validation_payload = {
        "task_id": task_id,
        "columns": data["columns"],
        "rows": data["rows"],
        "query": data["query"],
        "answer_type": answer_type,
    }

    validation = validate_pandas.validate(validation_payload)
    if validation.get("valid") is not True:
        return _base_output(
            task_id,
            False,
            0.0,
            validation,
            None,
            data.get("expected"),
            answer_type,
            [_error("VALIDATION_FAILED", "Submitted query did not pass validate_pandas.py.")],
        )

    raw_actual, execution_errors = _execute_query(data)
    if execution_errors:
        return _base_output(
            task_id,
            False,
            0.0,
            validation,
            None,
            data.get("expected"),
            answer_type,
            execution_errors,
        )

    try:
        actual_type, actual = _normalize_result(raw_actual, answer_type)
    except ValueError as exc:
        return _base_output(
            task_id,
            False,
            0.0,
            validation,
            None,
            data.get("expected"),
            answer_type,
            [_error("NON_FINITE_NUMBER", str(exc))],
        )
    except Exception as exc:
        return _base_output(
            task_id,
            False,
            0.0,
            validation,
            None,
            data.get("expected"),
            answer_type,
            [_error("NORMALIZATION_ERROR", f"Actual result normalization failed: {type(exc).__name__}: {exc}")],
        )

    try:
        expected_type, expected = _normalize_result(data.get("expected"), answer_type)
    except ValueError as exc:
        return _base_output(
            task_id,
            False,
            0.0,
            validation,
            actual,
            data.get("expected"),
            answer_type,
            [_error("NON_FINITE_NUMBER", f"Expected result is invalid: {exc}")],
        )
    except Exception as exc:
        return _base_output(
            task_id,
            False,
            0.0,
            validation,
            actual,
            data.get("expected"),
            answer_type,
            [_error("INVALID_EXPECTED", f"Expected result normalization failed: {type(exc).__name__}: {exc}")],
        )

    if actual_type != expected_type:
        return _base_output(
            task_id,
            False,
            0.0,
            validation,
            actual,
            expected,
            answer_type,
            [_error("ANSWER_MISMATCH", f"Actual type {actual_type} does not match expected type {expected_type}.")],
        )

    passed = _compare_values(
        actual,
        expected,
        answer_type,
        data["float_tolerance"],
        data["order_sensitive"],
    )
    if not passed:
        return _base_output(
            task_id,
            False,
            0.0,
            validation,
            actual,
            expected,
            answer_type,
            [_error("ANSWER_MISMATCH", "Actual result does not match expected result.")],
        )

    return _base_output(task_id, True, 1.0, validation, actual, expected, answer_type, [])


def main(argv: Sequence[str]) -> int:
    payload, error_output = _parse_payload(argv)
    if error_output is not None:
        _print_json(error_output)
        return 1
    assert payload is not None

    output = evaluate(payload)
    _print_json(output)
    return 0 if output.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

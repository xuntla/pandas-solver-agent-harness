#!/usr/bin/env python3
"""
validate_pandas.py

Intermediate validator for the Open Track Pandas Solver skill.

Purpose:
- Accept exactly one JSON payload as argv[1].
- Validate that `query` is a safe, single-line pandas expression over `df`.
- Reject unsupported Python / pandas syntax before execution.
- Execute the expression in a restricted environment.
- Normalize the result into a JSON-safe preview.
- Print one plain JSON object to stdout.

This script does NOT judge whether the query answers the natural-language question.
It only validates syntax, safety, allowed pandas subset, executability, and result shape.
Scenario scoring belongs to evaluator.py.
"""

from __future__ import annotations

import ast
import json
import math
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is expected via requirements.txt
    np = None  # type: ignore[assignment]


MAX_QUERY_CHARS = 1000
MAX_PREVIEW_ITEMS = 20

ANSWER_TYPES = {"number", "string", "boolean", "list", "dict", "table"}

ALLOWED_METHODS = {
    "mean",
    "sum",
    "count",
    "min",
    "max",
    "nunique",
    "value_counts",
    "sort_values",
    "head",
    "tail",
    "groupby",
    "to_dict",
    "tolist",
    "reset_index",
}

# Attribute access that is not directly called as a method is rejected by default.
# Pandas helpers such as .str, .dt, .loc, .iloc, .shape, .size are intentionally unsupported.
UNSUPPORTED_OR_DANGEROUS_METHODS = {
    "apply",
    "map",
    "pipe",
    "agg",
    "aggregate",
    "transform",
    "merge",
    "join",
    "pivot_table",
    "read_csv",
    "to_csv",
    "assign",
    "insert",
    "drop",
    "rename",
    "set_index",
    "eval",
    "query",
    "sample",
}

ALLOWED_NAMES = {"df"}

DANGEROUS_NAMES = {
    "__import__",
    "eval",
    "exec",
    "open",
    "compile",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "input",
    "help",
    "os",
    "sys",
    "subprocess",
    "pathlib",
    "shutil",
    "socket",
    "requests",
    "pd",
    "np",
    "pandas",
    "numpy",
}

ALLOWED_AST_NODES = (
    ast.Expression,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Subscript,
    ast.Attribute,
    ast.Compare,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Slice,
    ast.keyword,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.BitAnd,
    ast.BitOr,
    ast.Invert,
)


class ValidationErrorCollector:
    def __init__(self) -> None:
        self.errors: List[Dict[str, str]] = []
        self.warnings: List[Dict[str, str]] = []

    def add_error(self, code: str, message: str) -> None:
        self.errors.append({"code": code, "message": message})

    def add_warning(self, code: str, message: str) -> None:
        self.warnings.append({"code": code, "message": message})

    @property
    def ok(self) -> bool:
        return not self.errors


def make_output(
    task_id: Optional[str],
    valid: bool,
    errors: List[Dict[str, str]],
    warnings: Optional[List[Dict[str, str]]] = None,
    result_type: Optional[str] = None,
    result_preview: Any = None,
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "valid": valid,
        "errors": errors,
        "warnings": warnings or [],
        "result_type": result_type,
        "result_preview": result_preview,
    }


def print_json(obj: Dict[str, Any]) -> None:
    # allow_nan=False prevents invalid JSON values such as NaN and Infinity.
    print(json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def fatal(code: str, message: str, task_id: Optional[str] = None) -> None:
    print_json(make_output(task_id, False, [{"code": code, "message": message}]))


def parse_payload(argv: Sequence[str]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if len(argv) < 2:
        return None, make_output(
            None,
            False,
            [{"code": "MISSING_FIELD", "message": "Expected one JSON payload as argv[1]."}],
        )
    if len(argv) > 2:
        return None, make_output(
            None,
            False,
            [{"code": "INVALID_JSON", "message": "Expected exactly one JSON payload argument."}],
        )

    try:
        payload = json.loads(argv[1])
    except json.JSONDecodeError as exc:
        return None, make_output(
            None,
            False,
            [{"code": "INVALID_JSON", "message": f"Invalid JSON payload: {exc.msg}."}],
        )

    if not isinstance(payload, dict):
        return None, make_output(
            None,
            False,
            [{"code": "INVALID_TOP_LEVEL", "message": "Top-level JSON value must be an object."}],
        )
    return payload, None


def validate_basic_schema(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], ValidationErrorCollector]:
    c = ValidationErrorCollector()

    required = ["task_id", "columns", "rows", "query", "answer_type"]
    for field in required:
        if field not in payload:
            c.add_error("MISSING_FIELD", f"Missing required field: {field}.")

    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        c.add_error("INVALID_TASK_ID", "task_id must be a non-empty string.")

    columns = payload.get("columns")
    if not isinstance(columns, list) or not all(isinstance(x, str) for x in columns):
        c.add_error("INVALID_COLUMNS", "columns must be an array of strings.")
    elif not columns:
        c.add_error("EMPTY_COLUMNS", "columns must not be empty.")
    elif len(set(columns)) != len(columns):
        c.add_error("DUPLICATE_COLUMNS", "columns must not contain duplicate names.")

    rows = payload.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        c.add_error("INVALID_ROWS", "rows must be an array of arrays.")
    elif isinstance(columns, list) and all(isinstance(x, str) for x in columns):
        expected_len = len(columns)
        for idx, row in enumerate(rows):
            if len(row) != expected_len:
                c.add_error(
                    "ROW_LENGTH_MISMATCH",
                    f"Row {idx} has length {len(row)}, expected {expected_len}.",
                )
                break

    query = payload.get("query")
    if not isinstance(query, str):
        c.add_error("QUERY_NOT_STRING", "query must be a string.")
    else:
        if not query.strip():
            c.add_error("EMPTY_QUERY", "query must not be empty.")
        if "\n" in query or "\r" in query:
            c.add_error("MULTILINE_QUERY", "query must be a single-line expression.")
        if len(query) > MAX_QUERY_CHARS:
            c.add_error("QUERY_TOO_LONG", f"query must be at most {MAX_QUERY_CHARS} characters.")

    answer_type = payload.get("answer_type")
    if not isinstance(answer_type, str) or answer_type not in ANSWER_TYPES:
        c.add_error(
            "INVALID_ANSWER_TYPE",
            f"answer_type must be one of: {', '.join(sorted(ANSWER_TYPES))}.",
        )

    if not c.ok:
        return None, c

    return {
        "task_id": task_id,
        "columns": columns,
        "rows": rows,
        "query": query,
        "answer_type": answer_type,
    }, c


def build_dataframe(columns: List[str], rows: List[List[Any]], c: ValidationErrorCollector) -> Optional[pd.DataFrame]:
    try:
        return pd.DataFrame(rows, columns=columns)
    except Exception as exc:
        c.add_error("INVALID_ROWS", f"Failed to build DataFrame: {type(exc).__name__}: {exc}")
        return None


def parse_query_ast(query: str, c: ValidationErrorCollector) -> Optional[ast.Expression]:
    if "__" in query:
        c.add_error("DUNDER_FORBIDDEN", "Double-underscore names are not allowed.")
        return None
    try:
        return ast.parse(query, mode="eval")
    except SyntaxError as exc:
        c.add_error("SYNTAX_ERROR", f"Query is not a valid Python expression: {exc.msg}.")
        return None


def is_method_call_attr(node: ast.Attribute, parents: Dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    return isinstance(parent, ast.Call) and parent.func is node


def validate_literal_value(node: ast.AST, c: ValidationErrorCollector, context: str) -> None:
    """Validate keyword values and literal containers used inside calls."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool)) or node.value is None:
            if isinstance(node.value, float) and not math.isfinite(node.value):
                c.add_error("NON_FINITE_NUMBER", f"Non-finite number is not allowed in {context}.")
            return
        c.add_error("UNSUPPORTED_AST_NODE", f"Unsupported constant type in {context}.")
        return
    if isinstance(node, (ast.List, ast.Tuple)):
        for elt in node.elts:
            validate_literal_value(elt, c, context)
        return
    # Expressions such as ascending=False are OK; expressions from function calls are not.
    c.add_error("UNSUPPORTED_AST_NODE", f"Only literal keyword values are allowed in {context}.")


def collect_parents(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    parents: Dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def validate_ast(tree: ast.Expression, c: ValidationErrorCollector) -> None:
    parents = collect_parents(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_AST_NODES):
            c.add_error(
                "UNSUPPORTED_AST_NODE",
                f"Unsupported syntax node: {type(node).__name__}.",
            )
            continue

        if isinstance(node, ast.Name):
            name = node.id
            if "__" in name:
                c.add_error("DUNDER_FORBIDDEN", f"Double-underscore name is not allowed: {name}.")
            elif name in DANGEROUS_NAMES:
                c.add_error("UNSAFE_NAME", f"The name '{name}' is not allowed.")
            elif name not in ALLOWED_NAMES:
                c.add_error("UNKNOWN_NAME", f"Only the DataFrame variable 'df' may be used; got '{name}'.")

        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if "__" in attr:
                c.add_error("DUNDER_FORBIDDEN", f"Double-underscore attribute is not allowed: {attr}.")
            elif attr in UNSUPPORTED_OR_DANGEROUS_METHODS:
                c.add_error("UNSUPPORTED_METHOD", f"The pandas method or attribute '{attr}' is not allowed.")
            elif is_method_call_attr(node, parents):
                if attr not in ALLOWED_METHODS:
                    c.add_error("UNSUPPORTED_METHOD", f"The pandas method '{attr}' is not allowed.")
            else:
                c.add_error(
                    "UNSUPPORTED_METHOD",
                    f"Direct attribute access '.{attr}' is not allowed; use allowed method calls only.",
                )

        elif isinstance(node, ast.Call):
            # Only method calls like obj.method(...) are allowed.
            if not isinstance(node.func, ast.Attribute):
                c.add_error("UNSUPPORTED_METHOD", "Only pandas method calls on df-derived objects are allowed.")
            for kw in node.keywords:
                if kw.arg is None:
                    c.add_error("UNSUPPORTED_AST_NODE", "Starred keyword arguments are not allowed.")
                else:
                    validate_literal_value(kw.value, c, f"keyword argument '{kw.arg}'")


def extract_static_column_refs(tree: ast.Expression) -> List[str]:
    """Conservatively extract string constants used in subscripts.

    This is intentionally partial. Runtime execution still catches KeyError for
    dynamically ambiguous cases.
    """
    refs: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        sl = node.slice
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            refs.append(sl.value)
        elif isinstance(sl, (ast.List, ast.Tuple)):
            for elt in sl.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    refs.append(elt.value)
    return refs


def validate_static_columns(tree: ast.Expression, columns: List[str], c: ValidationErrorCollector) -> None:
    column_set = set(columns)
    for ref in extract_static_column_refs(tree):
        if ref not in column_set:
            c.add_error("UNKNOWN_COLUMN", f"Unknown column referenced in query: {ref}.")


def safe_eval(query: str, df: pd.DataFrame) -> Any:
    safe_globals: Dict[str, Any] = {"__builtins__": {}}
    safe_locals: Dict[str, Any] = {"df": df}
    compiled = compile(query, "<pandas-query>", "eval")
    return eval(compiled, safe_globals, safe_locals)  # noqa: S307 - guarded by AST whitelist


def is_numpy_scalar(value: Any) -> bool:
    if np is None:
        return False
    return isinstance(value, np.generic)


def to_python_scalar(value: Any) -> Any:
    if is_numpy_scalar(value):
        return value.item()
    return value


def reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite number cannot be serialized as valid JSON.")


def normalize_value(value: Any, answer_type: str) -> Tuple[str, Any]:
    """Normalize result to a JSON-safe value compatible with answer_type."""
    value = to_python_scalar(value)

    if isinstance(value, pd.DataFrame):
        if answer_type not in {"table", "list"}:
            raise TypeError(f"DataFrame result is not compatible with answer_type={answer_type}.")
        records = value.head(MAX_PREVIEW_ITEMS).to_dict(orient="records")
        return "table", normalize_json_value(records)

    if isinstance(value, pd.Series):
        if answer_type == "dict":
            return "dict", normalize_json_value(_limited_ordered_dict(value.to_dict()))
        if answer_type == "list":
            return "list", normalize_json_value(value.head(MAX_PREVIEW_ITEMS).tolist())
        raise TypeError(f"Series result is not compatible with answer_type={answer_type}.")

    if isinstance(value, pd.Index):
        if answer_type != "list":
            raise TypeError(f"Index result is not compatible with answer_type={answer_type}.")
        return "list", normalize_json_value(list(value[:MAX_PREVIEW_ITEMS]))

    if isinstance(value, dict):
        if answer_type != "dict":
            raise TypeError(f"dict result is not compatible with answer_type={answer_type}.")
        return "dict", normalize_json_value(_limited_ordered_dict(value))

    if isinstance(value, (list, tuple)):
        if answer_type != "list":
            raise TypeError(f"list result is not compatible with answer_type={answer_type}.")
        return "list", normalize_json_value(list(value[:MAX_PREVIEW_ITEMS]))

    if isinstance(value, bool):
        if answer_type != "boolean":
            raise TypeError(f"boolean result is not compatible with answer_type={answer_type}.")
        return "boolean", value

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if answer_type != "number":
            raise TypeError(f"number result is not compatible with answer_type={answer_type}.")
        reject_non_finite(value)
        return "number", value

    if isinstance(value, str):
        if answer_type != "string":
            raise TypeError(f"string result is not compatible with answer_type={answer_type}.")
        return "string", value

    if value is None:
        # None is JSON-safe but only meaningful for nullable scalar scenarios.
        if answer_type not in {"string", "number", "boolean"}:
            raise TypeError(f"None result is not compatible with answer_type={answer_type}.")
        return answer_type, None

    raise TypeError(f"Unsupported result type: {type(value).__name__}.")


def _limited_ordered_dict(d: Dict[Any, Any]) -> Dict[str, Any]:
    limited: "OrderedDict[str, Any]" = OrderedDict()
    for idx, (key, value) in enumerate(d.items()):
        if idx >= MAX_PREVIEW_ITEMS:
            break
        # JSON object keys must be strings. Keep deterministic conversion.
        limited[str(to_python_scalar(key))] = value
    return dict(limited)


def normalize_json_value(value: Any) -> Any:
    value = to_python_scalar(value)

    if isinstance(value, float):
        reject_non_finite(value)
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return [normalize_json_value(x) for x in value]
    if isinstance(value, list):
        return [normalize_json_value(x) for x in value]
    if isinstance(value, dict):
        return {str(normalize_json_value(k)): normalize_json_value(v) for k, v in value.items()}
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        raise ValueError("NaN/NA result is not valid JSON.")
    raise TypeError(f"Value is not JSON-serializable after normalization: {type(value).__name__}.")


def validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    data, c = validate_basic_schema(payload)
    task_id = payload.get("task_id") if isinstance(payload.get("task_id"), str) else None

    if data is None:
        return make_output(task_id, False, c.errors, c.warnings)

    task_id = data["task_id"]
    columns = data["columns"]
    rows = data["rows"]
    query = data["query"].strip()
    answer_type = data["answer_type"]

    df = build_dataframe(columns, rows, c)
    if df is None:
        return make_output(task_id, False, c.errors, c.warnings)

    tree = parse_query_ast(query, c)
    if tree is None:
        return make_output(task_id, False, c.errors, c.warnings)

    validate_ast(tree, c)
    validate_static_columns(tree, columns, c)

    # Do not execute if static validation failed.
    if not c.ok:
        return make_output(task_id, False, c.errors, c.warnings)

    try:
        result = safe_eval(query, df)
    except KeyError as exc:
        return make_output(
            task_id,
            False,
            c.errors + [{"code": "UNKNOWN_COLUMN", "message": f"Unknown column at execution time: {exc}."}],
            c.warnings,
        )
    except Exception as exc:
        return make_output(
            task_id,
            False,
            c.errors + [{"code": "EXECUTION_ERROR", "message": f"{type(exc).__name__}: {exc}"}],
            c.warnings,
        )

    try:
        result_type, result_preview = normalize_value(result, answer_type)
        # Final serialization probe with allow_nan=False.
        json.dumps(result_preview, ensure_ascii=False, allow_nan=False)
    except ValueError as exc:
        return make_output(
            task_id,
            False,
            c.errors + [{"code": "NON_FINITE_NUMBER", "message": str(exc)}],
            c.warnings,
        )
    except Exception as exc:
        return make_output(
            task_id,
            False,
            c.errors + [{"code": "RESULT_NOT_SERIALIZABLE", "message": f"{type(exc).__name__}: {exc}"}],
            c.warnings,
        )

    return make_output(task_id, True, [], c.warnings, result_type, result_preview)


def main(argv: Sequence[str]) -> int:
    payload, error_output = parse_payload(argv)
    if error_output is not None:
        print_json(error_output)
        return 1
    assert payload is not None

    output = validate(payload)
    print_json(output)
    return 0 if output.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
validate
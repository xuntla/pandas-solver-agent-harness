---
name: open-pandas-solver-xuntla
description: Solve small tabular QA tasks by generating a safe pandas expression, validating it, and writing the final result via scripts/run.py.
version: 2.0.0
metadata:
  hermes:
    tags: [open-track, pandas, dataframe, tabular-qa]
    category: data
    requires_toolsets: [terminal]
---

# Open Pandas Solver Skill

## When to Use

Use this skill for Open Track tasks with `task_id`, `question`, `columns`, `rows`, and `answer_type`.
The task is to answer a small table question by generating one safe pandas expression over `df`.
Do not use this skill for SQL, arbitrary Python coding, plotting, file processing, web access, or external datasets.

## Input Contract

Input is one JSON object with this shape: `{task_id, question, columns, rows, answer_type, expected}`.

Rules:

- `task_id`: copy exactly.
- `question`: natural-language table question.
- `columns`: DataFrame column names.
- `rows`: table rows; each row length must match `columns`.
- `answer_type`: one of `number`, `string`, `boolean`, `list`, `dict`, `table`.

## Output Contract

Final result must be written to the result file by `scripts/run.py`.
Do not rely on the chat message as the graded output.
The result file must contain this JSON object:

```json
{
  "task_id": "...",
  "query": "df[df['department'] == 'CS']['salary'].mean()",
  "answer": 75000.0,
  "answer_type": "number",
  "validation": {"valid": true, "error_count": 0},
  "rationale": "...",
  "confidence": 0.9
}
```

Rules:

- `task_id` must exactly match input.
- `query` must be one single-line pandas expression using only `df`.
- `answer` must be JSON-safe; no `NaN`, `Infinity`, or `-Infinity`.
- `answer_type` must match input.
- `validation.valid` must reflect `validate_pandas.py` output.
- `confidence` must be a number from `0.0` to `1.0`.
- Do not add prose, Markdown fences, YAML, XML, or extra text to the result file.

## Procedure

1. Parse input JSON and copy `task_id` exactly.
2. Treat `columns` and `rows` as a DataFrame named exactly `df`.
3. Infer filters, aggregations, grouping, sorting, limits, and output type from `question`.
4. Generate exactly one single-line pandas expression.
5. Use only the allowed pandas subset below.
6. Validate with exactly one JSON argv argument:
   `python3 skills/open-pandas-solver-xuntla/scripts/validate_pandas.py '{"task_id":"<task_id>","columns":[...],"rows":[...],"query":"<candidate_query>","answer_type":"<answer_type>"}'`
   Inside all single JSON argv shell commands, never put raw single quotes inside the JSON string. 
   For pandas column or string literals, use double quotes in the pandas expression and escape them as JSON \". 
   Example: use df[df[\"department\"] == \"CS\"][\"salary\"].mean(), not df[df['department'] == 'CS']['salary'].mean().
7. If validation succeeds, use `result_preview` as the candidate answer when it matches the requested answer.
8. If validation fails, repair once using validator errors.
9. Run at most one more validation call after repair.
10. Do not continue retrying after two total validation calls.
11. Build the final result payload for `run.py`.
12. Execute `run.py` with exactly one JSON argv argument:
    `python3 skills/open-pandas-solver-xuntla/scripts/run.py '{"task_id":"<task_id>","query":"<final_query>","answer":<answer>,"answer_type":"<answer_type>","validation":<validation_json>,"rationale":"<brief_rationale>","confidence":0.0}'`
13. Do not print or return the final JSON in chat.
14. Grading reads only the result file written by `run.py`.

## Pandas Query Rules

Allowed expression shape:

- one expression only;
- one line only;
- use only `df` as the variable name;
- do not mutate `df`;
- return a JSON-normalizable value.
- 

Allowed methods:

- `mean`, `sum`, `count`, `min`, `max`, `nunique`
- `value_counts`, `sort_values`, `head`, `tail`
- `groupby`, `to_dict`, `tolist`, `reset_index`

Forbidden:

- imports, external modules, `pd`, `np`, `pandas`, `numpy`;
- file I/O, network access, shell access, `open`;
- `eval`, `exec`, `compile`, `__import__`;
- lambda, functions, classes, comprehensions;
- `apply`, `map`, `pipe`, `agg`, `transform`;
- `merge`, `join`, `pivot_table`;
- `assign`, `insert`, `drop`, `rename`, `set_index`;
- `read_csv`, `to_csv`, `df.query`;
- `.loc`, `.iloc`, `.str`, `.dt`, `.shape`, `.size`;
- dunder names or attributes.

## Answer Type Rules

Normalize outputs as: `number` scalar, `string` scalar, `boolean` scalar, `list` JSON array, `dict` JSON object with string keys, and `table` list of record objects.

Prefer aggregations for `number`, `.tolist()` for `list`, and `.to_dict()` for `dict`.
Prefer `number`, `list`, and `dict` unless the task explicitly asks for records.

## Verification

`validate_pandas.py` is the intermediate validator.
It checks syntax, safety, allowed pandas subset, executability, and result shape.
It does not judge whether the query answers the natural-language question.

`evaluator.py` is the deterministic Open Track metric script.  
It is not part of the normal final-answer procedure.  
It receives scenario.expected and the submitted query, re-executes the query, and checks actual vs expected.
Use it for public scenario checks and local verification, not as the normal final-answer step.
Example command format:
`python3 skills/open-pandas-solver-xuntla/scripts/evaluator.py '{"task_id":"<task_id>","scenario":{...},"submission":{"query":"<query>","answer":<answer>},"compare":{"float_tolerance":1e-6,"order_sensitive":true}}'`

`run.py` is only the final result-file writer.
It writes to `AIASE_RESULT_PATH`, or to `./aiase_result.json` when the environment variable is unset.
It does not validate, execute, repair, or score the pandas query.
Pass exactly one JSON string argument to each script.

## Pitfalls

Avoid:

- changing `task_id`;
- printing final JSON in chat instead of writing the result file;
- skipping `validate_pandas.py` before `run.py`;
- using unsupported pandas methods or multi-line queries;
- mutating `df`;
- using imports, files, `pd`, `np`, `open`, `eval`, `exec`, `apply`, lambda, or dunder names;
- relying only on `expected` or hardcoding from `task_id`;
- using external network, local absolute paths, or non-repo files;
- calling more than two validation attempts;
- using `evaluator.py` as the final output writer.

## Final Rule

Always finish by calling `skills/open-pandas-solver-xuntla/scripts/run.py` with one JSON argv argument.
If the best query is uncertain, still write a valid result JSON with low confidence.
Never end with only an apology, traceback, Markdown-only answer, or chat-only JSON.

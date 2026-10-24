## 1. Skill 簡介

本 Open Track skill 名為 `open-pandas-solver-xuntla`。它接收小型表格資料與自然語言問題，產生一行安全的 pandas expression，透過 `validate_pandas.py` 驗證後，再由 `run.py` 將最終 JSON 寫入結果檔。

此 skill 的核心目標不是執行任意 Python，而是把簡單、可驗證的 tabular QA 任務轉換成受限 pandas 查詢，並讓結果可由 deterministic evaluator 自動重跑與比對。

---

## 2. Skill 名稱與目錄

- Skill name：`open-pandas-solver-xuntla`
- Skill directory：`skills/open-pandas-solver-xuntla/`
- Script directory：`skills/open-pandas-solver-xuntla/scripts/`

主要 scripts：

```text
skills/open-pandas-solver-xuntla/scripts/validate_pandas.py
skills/open-pandas-solver-xuntla/scripts/run.py
skills/open-pandas-solver-xuntla/scripts/evaluator.py
skills/open-pandas-solver-xuntla/scripts/requirements.txt
```

各 script 的責任如下：

| 檔案 | 角色 |
|---|---|
| `validate_pandas.py` | 中途驗證器。檢查 query 是否為安全、單行、可執行、可序列化的 pandas expression。 |
| `run.py` | 最終結果檔寫入器。將 skill 的 final result JSON 寫入 `AIASE_RESULT_PATH`，未設定時寫入 `./aiase_result.json`。 |
| `evaluator.py` | Open Track scenario 評分器。重跑 query，將 actual result 與 expected ground truth 做 deterministic comparison。 |
| `requirements.txt` | 固定 pandas / numpy 版本，確保環境可重現。 |

`requirements.txt` 內容：

```text
numpy==2.0.2
pandas==2.2.3
```

---

## 3. 呼叫方式

### 3.1 Hermes skill 呼叫

正式呼叫需使用 `-Q`，並透過 Hermes 觸發此 skill：

```bash
hermes chat --toolsets skills,terminal --yolo -Q -q '/open-pandas-solver-xuntla {
  "task_id": "pd_public_001",
  "question": "What is the average salary of employees in CS?",
  "columns": ["name", "department", "salary"],
  "rows": [
    ["Alice", "CS", 70000],
    ["Bob", "EE", 65000],
    ["Carol", "CS", 80000]
  ],
  "answer_type": "number"
}'
```

### 3.2 Skill input schema

正常 skill input 不提供 `expected`。`expected` 只屬於 public / hidden scenario 的 evaluator ground truth，不是 Hermes 解題時應依賴的欄位。

```json
{
  "task_id": "string",
  "question": "string",
  "columns": ["string"],
  "rows": [["any JSON scalar"]],
  "answer_type": "number|string|boolean|list|dict|table"
}
```

欄位規則：

| 欄位 | 說明 |
|---|---|
| `task_id` | 必須原樣複製到最終結果。 |
| `question` | 表格問題的自然語言描述。 |
| `columns` | 欄位名稱，會被視為 DataFrame columns。 |
| `rows` | 表格資料，每列長度必須等於 `columns` 長度。 |
| `answer_type` | 指定答案正規化型態：`number`、`string`、`boolean`、`list`、`dict`、`table`。 |

### 3.3 Skill output schema

最終輸出不依賴 chat message。Skill 必須呼叫：

```bash
python3 skills/open-pandas-solver-xuntla/scripts/run.py '<ONE_JSON_PAYLOAD>'
```

`run.py` 會將結果寫入 `AIASE_RESULT_PATH` 指定的檔案；若環境變數未設定，則寫入目前工作目錄的 `./aiase_result.json`。

結果檔 JSON schema：

```json
{
  "task_id": "string",
  "query": "string",
  "answer": "any JSON-safe value",
  "answer_type": "number|string|boolean|list|dict|table",
  "validation": {
    "valid": true,
    "error_count": 0
  },
  "rationale": "string",
  "confidence": 0.0
}
```

欄位規則：

| 欄位 | 規則 |
|---|---|
| `task_id` | 必須與輸入完全一致。 |
| `query` | 必須是一行 pandas expression，只能使用 DataFrame 變數 `df`。 |
| `answer` | 必須是 JSON-safe value，不可出現 `NaN`、`Infinity`、`-Infinity`。 |
| `answer_type` | 必須與輸入一致。 |
| `validation.valid` | 必須反映 `validate_pandas.py` 的驗證結果。 |
| `validation.error_count` | 必須為 validator error 數量。 |
| `rationale` | 簡短說明 query 如何回答問題。 |
| `confidence` | 必須是 `0.0` 到 `1.0` 的 number。 |

### 3.4 Script command format

所有 scripts 都必須使用單一 JSON argv。不得使用多個 positional arguments，也不得依賴互動式輸入。

`validate_pandas.py` 驗證 query：

```bash
python3 skills/open-pandas-solver-xuntla/scripts/validate_pandas.py '{"task_id":"pd_public_001","columns":["name","department","salary"],"rows":[["Alice","CS",70000],["Bob","EE",65000],["Carol","CS",80000]],"query":"df[df[\"department\"] == \"CS\"][\"salary\"].mean()","answer_type":"number"}'
```

`run.py` 寫入結果檔：

```bash
python3 skills/open-pandas-solver-xuntla/scripts/run.py '{"task_id":"pd_public_001","query":"df[df[\"department\"] == \"CS\"][\"salary\"].mean()","answer":75000.0,"answer_type":"number","validation":{"valid":true,"errors":[]},"rationale":"Filter CS rows and compute mean salary.","confidence":0.9}'
```

`evaluator.py` 評估 scenario：

```bash
python3 skills/open-pandas-solver-xuntla/scripts/evaluator.py '{"task_id":"pd_public_001","scenario":{"question":"What is the average salary of employees in CS?","columns":["name","department","salary"],"rows":[["Alice","CS",70000],["Bob","EE",65000],["Carol","CS",80000]],"answer_type":"number","expected":75000.0},"submission":{"query":"df[df[\"department\"] == \"CS\"][\"salary\"].mean()","answer":75000.0},"compare":{"float_tolerance":1e-6,"order_sensitive":true}}'
```

---

## 4. 自定 Verifiable Scenario

本 Open Track 的驗證核心是：**不相信模型自稱的答案，而是重跑模型輸出的 pandas query。**

每個 scenario 都包含：

1. 給 Hermes skill 的表格問題 input。
2. evaluator 持有的 `expected` ground truth。
3. Hermes skill 寫入結果檔的 `query`。
4. `evaluator.py` 將 query 重新套用到相同 DataFrame 上，得到 actual result。
5. evaluator 依 `answer_type` 正規化 actual / expected，並做 deterministic comparison。

### 4.1 評分 metric

每個 scenario 使用 binary score：

```text
passed = true  -> score = 1.0
passed = false -> score = 0.0
```

多個 scenario 的總分為：

```text
overall_score = passed_scenarios / total_scenarios
```

單一 scenario 通過條件：

1. Hermes skill 必須成功呼叫 `run.py` 並寫出結果檔。
2. 結果檔必須是合法 JSON object。
3. `task_id` 必須與 scenario input 完全一致。
4. `query` 必須通過 `validate_pandas.py`。
5. `evaluator.py` 必須能重新執行 `query`。
6. 重新執行得到的 actual result 必須等於 scenario 的 expected ground truth。
7. `answer_type` normalization 後的型態必須一致。

### 4.2 為何 metric 不可 gameable

此 metric 不靠自然語言判斷，也不靠關鍵字比對，因此不容易被亂猜或 hardcode 取分。

具體理由：

1. **不信任 `answer` 欄位**  
   Hermes 寫出的 `answer` 只作為輔助資訊。`evaluator.py` 會重新執行 `query` 取得 actual result。因此即使模型把 `answer` 填成正確值，只要 `query` 算錯，scenario 仍會失敗。

2. **不以 query 字串做表面比對**  
   evaluator 不要求 query 字串完全等於 reference query。只要 query 通過安全限制，且實際執行結果正確，即可通過。這允許等價寫法，也避免把評分變成死背字串。

3. **有 ground truth**  
   每個 public scenario 都明確提供 `expected`，hidden / perturbed scenario 也可由同樣格式提供 ground truth。actual 與 expected 可由程式自動比對。

4. **有 validator gate**  
   `validate_pandas.py` 會阻擋 import、file I/O、危險名稱、unsupported pandas methods、多行 query、不可序列化結果等。這避免模型用任意 Python、讀檔、外部環境或副作用取得答案。

5. **可承受 perturbation**  
   Staff 可改 row order、數值、類別名稱、資料筆數，或加入 unrelated columns。若 skill 只根據 `task_id` 或 public example 的固定答案輸出，會在 perturbation 後失敗。

6. **輸出行為可重現**  
   `evaluator.py` 完全 deterministic，不呼叫 Hermes、不修 query、不使用外部網路、不依賴人工主觀判斷。

---

### Scenario 1：Filter + Mean

此 scenario 測試 skill 是否能根據條件篩選 rows，並對 numeric column 做平均值聚合。

Skill input：

```json
{
  "task_id": "pd_public_001",
  "question": "What is the average salary of employees in CS?",
  "columns": ["name", "department", "salary"],
  "rows": [
    ["Alice", "CS", 70000],
    ["Bob", "EE", 65000],
    ["Carol", "CS", 80000]
  ],
  "answer_type": "number"
}
```

Ground truth：

```json
{
  "expected": 75000.0
}
```

合理 query 範例：

```python
df[df["department"] == "CS"]["salary"].mean()
```

通過原因：

```text
CS rows are Alice and Carol.
Their salaries are 70000 and 80000.
Average = (70000 + 80000) / 2 = 75000.0
```

可接受 perturbation：

- 調換 row order。
- 新增其他 department。
- 改變薪資數值。
- 把 `CS` 換成其他部門名稱。
- 加入 unrelated column，例如 `age` 或 `location`。

此 scenario 防止的錯誤：

- 算成全體員工平均薪資。
- 忘記 `department == CS` filter。
- 寫出錯誤 boolean mask，例如 `df[df["department" == "CS"]]`。

---

### Scenario 2：Groupby + Sum

此 scenario 測試 skill 是否能找出 grouping key，並對 numeric column 做 group-wise sum。

Skill input：

```json
{
  "task_id": "pd_public_002",
  "question": "What is the total sales amount for each region?",
  "columns": ["region", "sales"],
  "rows": [
    ["North", 100],
    ["South", 250],
    ["North", 200]
  ],
  "answer_type": "dict"
}
```

Ground truth：

```json
{
  "expected": {
    "North": 300,
    "South": 250
  }
}
```

合理 query 範例：

```python
df.groupby("region")["sales"].sum().to_dict()
```

通過原因：

```text
North appears twice: 100 + 200 = 300.
South appears once: 250.
The expected output is a JSON object keyed by region.
```

可接受 perturbation：

- 調換 row order。
- 新增 `East` 或 `West` region。
- 改變 sales 數值。
- 加入 unrelated column，例如 `salesperson`。

此 scenario 防止的錯誤：

- 只計算總銷售額而沒有分區。
- 使用 `count` 取代 `sum`。
- 輸出 list 而非 dict。

---

### Scenario 3：Sort + Top-k

此 scenario 測試 skill 是否能處理排序、descending order、top-k selection，以及輸出指定欄位 list。

Skill input：

```json
{
  "task_id": "pd_public_003",
  "question": "Which two products have the highest revenue?",
  "columns": ["product", "revenue"],
  "rows": [
    ["Laptop", 5000],
    ["Mouse", 300],
    ["Phone", 4000],
    ["Keyboard", 800]
  ],
  "answer_type": "list"
}
```

Ground truth：

```json
{
  "expected": ["Laptop", "Phone"]
}
```

合理 query 範例：

```python
df.sort_values("revenue", ascending=False)["product"].head(2).tolist()
```

通過原因：

```text
Revenue order descending is Laptop 5000, Phone 4000, Keyboard 800, Mouse 300.
The top two product names are Laptop and Phone.
```

可接受 perturbation：

- 調換 row order。
- 改變 revenue 數值。
- 新增產品。
- 將 top 2 改成 top 3。

此 scenario 防止的錯誤：

- 升冪排序導致選到最低 revenue。
- 回傳 revenue 而非 product name。
- 忘記 `head(2)`。
- 輸出 dict 而非 list。

---

### Scenario 4：Value Counts

此 scenario 測試 skill 是否能對 categorical column 做 frequency counting。

Skill input：

```json
{
  "task_id": "pd_public_004",
  "question": "How many employees are in each department?",
  "columns": ["name", "department"],
  "rows": [
    ["Alice", "CS"],
    ["Bob", "EE"],
    ["Carol", "CS"],
    ["Dave", "Math"]
  ],
  "answer_type": "dict"
}
```

Ground truth：

```json
{
  "expected": {
    "CS": 2,
    "EE": 1,
    "Math": 1
  }
}
```

合理 query 範例：

```python
df["department"].value_counts().to_dict()
```

通過原因：

```text
CS appears twice.
EE appears once.
Math appears once.
```

可接受 perturbation：

- 調換 row order。
- 增加 department 類別。
- 改變各 department 的出現次數。
- 加入 unrelated numeric column。

此 scenario 防止的錯誤：

- 只回傳 unique department list，沒有 count。
- 回傳員工姓名而非 department counts。
- 用 `nunique()` 回傳類別數，而非每類別人數。

---

### Scenario 5：Filter + Nunique

此 scenario 測試 skill 是否能先篩選資料，再計算 distinct count。

Skill input：

```json
{
  "task_id": "pd_public_005",
  "question": "How many unique customers bought books?",
  "columns": ["customer", "category", "amount"],
  "rows": [
    ["Ann", "Books", 120],
    ["Ben", "Games", 300],
    ["Ann", "Books", 80],
    ["Cara", "Books", 200]
  ],
  "answer_type": "number"
}
```

Ground truth：

```json
{
  "expected": 2
}
```

合理 query 範例：

```python
df[df["category"] == "Books"]["customer"].nunique()
```

通過原因：

```text
Books rows are Ann, Ann, and Cara.
Unique customers are Ann and Cara.
The correct distinct count is 2.
```

可接受 perturbation：

- 同一 customer 多次購買。
- 改變 category 名稱。
- 新增其他 category。
- 調換 row order。
- 加入 unrelated column，例如 `date`。

此 scenario 防止的錯誤：

- 將 book purchase rows 數量 3 誤當 unique customer 數量。
- 忘記 category filter。
- 對 `amount` 而非 `customer` 做 `nunique()`。

---

### 4.3 Evaluator input format

每個 public scenario 可用以下格式交給 `evaluator.py`：

```json
{
  "task_id": "pd_public_001",
  "scenario": {
    "question": "What is the average salary of employees in CS?",
    "columns": ["name", "department", "salary"],
    "rows": [
      ["Alice", "CS", 70000],
      ["Bob", "EE", 65000],
      ["Carol", "CS", 80000]
    ],
    "answer_type": "number",
    "expected": 75000.0
  },
  "submission": {
    "query": "df[df[\"department\"] == \"CS\"][\"salary\"].mean()",
    "answer": 75000.0
  },
  "compare": {
    "float_tolerance": 1e-6,
    "order_sensitive": true
  }
}
```

`submission.query` 應從 skill 寫出的結果檔取得。`submission.answer` 不作為唯一評分依據；evaluator 會重跑 `query`。

---

### 4.4 Scenario 流程演示

以下以 Scenario 1 說明本 skill 的完整驗證流程。此 scenario 的目標是驗證 skill 是否能根據表格資料與自然語言問題，產生正確的 pandas expression，並透過 `evaluator.py` 重新執行 query 來判斷結果是否正確。

首先，使用 Hermes 執行 Open Track skill：

```bash
hermes chat --toolsets skills,terminal -Q --yolo -q '/open-pandas-solver-xuntla {
  "task_id": "pd_001",
  "question": "What is the average salary of employees in CS?",
  "columns": ["name", "department", "salary"],
  "rows": [
    ["Alice", "CS", 70000],
    ["Bob", "EE", 65000],
    ["Carol", "CS", 80000]
  ],
  "answer_type": "number"
}'
```

Hermes agent 透過 `skills/open-pandas-solver-xuntla/scripts/run.py` 將結果寫入 `AIASE_RESULT_PATH` 指定的結果檔；若環境變數未設定，則寫入 `./aiase_result.json`。

此 scenario 中，結果檔內容如下：

```json
{
  "task_id": "pd_001",
  "query": "df[df[\"department\"] == \"CS\"][\"salary\"].mean()",
  "answer": 75000.0,
  "answer_type": "number",
  "validation": {
    "valid": true,
    "error_count": 0
  },
  "rationale": "Filter the DataFrame for employees in the CS department and calculate the mean of their salaries.",
  "confidence": 1.0
}
```

接著，從結果檔取出 `query` 欄位：

```python
df[df[\"department\"] == \"CS\"][\"salary\"].mean()
```

此 query 會作為後續呼叫 `evaluator.py` 時的 `submission.query`。`evaluator.py` 不直接相信 result file 中的 `answer` 欄位，而是會重新建立 DataFrame、重新執行 `submission.query`，再將實際執行結果與 scenario 的 `expected` ground truth 進行比對。

呼叫 `evaluator.py` 的指令如下：

```bash
python3 skills/open-pandas-solver-xuntla/scripts/evaluator.py '{
  "task_id": "pd_public_001",
  "scenario": {
    "question": "What is the average salary of employees in CS?",
    "columns": ["name", "department", "salary"],
    "rows": [
      ["Alice", "CS", 70000],
      ["Bob", "EE", 65000],
      ["Carol", "CS", 80000]
    ],
    "answer_type": "number",
    "expected": 75000.0
  },
  "submission": {
    "query": "df[df[\"department\"] == \"CS\"][\"salary\"].mean()",
    "answer": 75000.0
  },
  "compare": {
    "float_tolerance": 1e-6,
    "order_sensitive": true
  }
}'
```

`evaluator.py` 的輸出如下：

```json
{
  "task_id": "pd_public_001",
  "passed": true,
  "score": 1.0,
  "validation": {
    "valid": true,
    "errors": []
  },
  "actual": 75000.0,
  "expected": 75000.0,
  "answer_type": "number",
  "errors": []
}
```

可以看到，此次驗證結果為 `passed: true`，且 `score` 為 `1.0`。這代表 skill 產生的 pandas expression 不只通過 `validate_pandas.py` 的安全與語法檢查，也能在 `evaluator.py` 中重新執行並得到與 ground truth 相同的結果。

---

## 5. 預期失敗模式

### 5.1 失敗模式一：pandas expression 語法或安全性不合法

可能情境：

```python
df[df["department" == "CS"]]["salary"].mean()
```

或：

```python
df["salary"].apply(lambda x: x * 2).tolist()
```

第一個例子是 boolean mask 寫錯，`"department" == "CS"` 會先被 Python 算成 `False`，導致 query 不符合預期。第二個例子使用 forbidden method `apply` 和 forbidden syntax `lambda`。

偵測方式：

- `validate_pandas.py` 會解析 AST。
- 它會檢查 query 是否為單行 expression。
- 它會拒絕 dangerous names、unsupported methods、unsupported AST nodes。
- 它會嘗試在 restricted environment 中執行 query。

處理方式：

- `SKILL.md` 要求 Hermes 第一次 validation 失敗後最多修正一次。
- 修正後再執行一次 `validate_pandas.py`。
- 兩次 validation 都失敗時，仍須呼叫 `run.py` 寫出合法結果檔，但 `validation.valid` 應為 `false`，confidence 應降低。

此失敗模式的意義：

- 它證明此 skill 不會直接相信 LLM 產生的 pandas expression。
- 錯誤 query 會被 deterministic validator 擋下，而不是直接進入最終結果。

---

### 5.2 失敗模式二：query 合法但語意錯誤

可能情境：

題目：

```text
What is the average salary of employees in CS?
```

錯誤 query：

```python
df["salary"].mean()
```

這個 query 是合法 pandas expression，也能通過安全檢查，但它算的是所有員工平均薪資，不是 CS 員工平均薪資。

偵測方式：

- `validate_pandas.py` 可能會通過，因為它只判斷語法、安全性、allowed subset 與 result shape。
- `evaluator.py` 會重跑 query，得到 actual result。
- actual result 會與 scenario.expected 比對。
- 若不同，回傳 `passed=false`、`score=0.0`、`ANSWER_MISMATCH`。

處理方式：

- 在 public scenario 開發階段，用 `evaluator.py` 測試 query 是否真的回答問題。
- 在 hidden / perturbed scenario 中，若模型只產生表面合法但語意錯誤的 query，會被 evaluator 判失敗。

此失敗模式的意義：

- 它說明為什麼 `validate_pandas.py` 不能取代 `evaluator.py`。
- validator 是合法性 gate；evaluator 才是語意正確性 metric。

---

### 5.3 失敗模式三：輸出檔不存在或格式錯誤

可能情境：

- Hermes 沒有呼叫 `run.py`。
- `run.py` 沒有成功寫入 `AIASE_RESULT_PATH`。
- 結果檔不是 JSON object。
- 結果檔缺少 `task_id`、`query`、`answer_type`、`validation`、`confidence` 等欄位。
- 結果檔含有 `NaN`、`Infinity`、Markdown fence 或自然語言段落。

偵測方式：

- file-based grader 會讀結果檔。
- 沒有結果檔代表該題無有效輸出。
- JSON parse 失敗或欄位缺漏會導致該 scenario 失敗。

處理方式：

- `SKILL.md` 明確規定最後一定要呼叫 `skills/open-pandas-solver-xuntla/scripts/run.py`。
- `run.py` 負責 JSON-safe normalization、confidence clamp，以及原子寫檔。
- 即使 query 不確定，也必須寫出合法 result JSON，不能只在 chat 中道歉或說明錯誤。

此失敗模式的意義：

- 它避免 Open Track 因輸出格式不穩而不可評分。
- 它符合 file-based output 的最新標準：評分器只看結果檔，不看 chat 裡說了什麼。

---

### 5.4 失敗模式四：hardcoding 或依賴 public scenario 固定答案

可能情境：

- query 或 answer 根據 `task_id` 固定輸出。
- 不解析 `question`、`columns`、`rows`，只記住 public scenario 的答案。
- 當 row order、數值、類別名稱或資料筆數改變時仍輸出原本答案。

偵測方式：

- Staff 可進行 perturbation，例如改 row order、改數值、加入 unrelated columns、改類別名稱。
- evaluator 使用 perturbed scenario 的 expected ground truth 重新評分。
- hardcoded output 在 public scenario 可能通過，但在 perturbed scenario 會失敗。

處理方式：

- Skill input 不提供 `expected`。
- `OPEN_TRACK.md` 明確說明 expected 只屬於 evaluator，不屬於正常 skill input。
- 評分以重跑 `query` 後的 actual result 為準，而不是以模型自填的 answer 為準。

此失敗模式的意義：

- 它直接對應 Open Track 的 anti-hardcoding 要求。
- 它確保 skill 展現的是一般化 tabular QA 能力，而不是記憶 public examples。

---

### 5.5 失敗模式五：answer_type 或輸出型態錯誤

可能情境：

- 題目要求 `dict`，但 query 輸出 list。
- 題目要求 `number`，但 query 輸出 Series。
- 題目要求 `list`，但 query 沒有 `.tolist()`。
- dict key 不是 JSON-safe string。

偵測方式：

- `validate_pandas.py` 會檢查 result shape 是否 compatible with `answer_type`。
- `evaluator.py` 會 normalize actual / expected 後比較型態與值。

處理方式：

- 若 answer_type 是 `number`，query 應回傳 scalar number。
- 若 answer_type 是 `list`，query 應回傳 JSON array，例如 `.tolist()`。
- 若 answer_type 是 `dict`，query 應回傳 JSON object，例如 `.to_dict()`。
- 若 answer_type 是 `table`，query 應回傳 list of records。

此失敗模式的意義：

- 它確保輸出不只是值正確，也要能被機器穩定解析與比對。

---

## 6. 互動對象

此 skill 的主要互動對象是需要快速處理小型表格問題的 Hermes 使用者。使用者通常已經有一份可直接放入 JSON 的表格資料，並希望用自然語言提出問題，不想手寫 pandas expression。

### 6.1 目標使用者

1. **資料分析初學者**  
   他們可能知道表格欄位和想問的問題，但不熟悉 pandas 語法。此 skill 可以把問題轉成受限且可驗證的 pandas expression。

2. **課程助教或評分者**  
   他們需要檢查 Hermes skill 是否能在 tabular QA scenario 中產生可重跑、可評分的輸出。此 skill 的結果檔與 evaluator 可直接支援自動評分流程。

3. **需要快速驗算小表格的人**  
   例如想從少量 rows 中計算平均、總和、類別次數、top-k 或 unique count 的使用者。這些任務不需要完整資料科學 pipeline，只需要安全的一行 pandas expression。

4. **Hermes skill 開發者**  
   他們可以參考此 skill 的設計，理解如何用 deterministic validator 和 evaluator 包住 LLM 產生的 query，避免只靠模型自然語言回答。

### 6.2 使用者需求

這些使用者需要：

- 用自然語言描述表格問題。
- 不手寫完整 Python 程式。
- 確保產生的 pandas expression 安全、受限、可執行。
- 確保最終結果可被自動評分器解析。
- 在 public / hidden scenario 中能用同一套 evaluator 比對結果。
- 避免外部檔案、網路、API key 或本機環境依賴。

### 6.3 互動流程

互動流程如下：

```text
User provides task_id, question, columns, rows, answer_type
-> Hermes loads open-pandas-solver-xuntla
-> Hermes generates one pandas expression over df
-> Hermes calls validate_pandas.py
-> Hermes repairs once if validation fails
-> Hermes calls run.py
-> run.py writes the result file
-> evaluator.py can later verify the query against scenario.expected
```

此版設計不需要使用者提供 external files，也不需要使用者手動啟動外部服務。使用者只需提供 JSON input；Hermes 與 skill scripts 負責完成驗證與寫檔。

---

## 7. Token Budget 估算

### 7.1 估算範圍

每個 scenario 的 token budget 主要包含：

1. `SKILL.md` instruction tokens。
2. 使用者輸入 JSON tokens。
3. Hermes 生成 query、rationale、final payload 的 tokens。
4. `validate_pandas.py` command tokens。
5. `validate_pandas.py` stdout tokens。
6. `run.py` command tokens。
7. `run.py` stdout tokens。
8. 若進行 public scenario verification，額外包含 `evaluator.py` input / output tokens。

`validate_pandas.py`、`run.py`、`evaluator.py` 的完整程式碼不會整份放入 prompt；Hermes 只會看到 `SKILL.md`、使用者 input、terminal command、stdout。因此主要 token 消耗來自 skill instruction、scenario JSON、工具呼叫與工具輸出。

### 7.2 單次正常執行估算

正常情況下，每個 scenario 只需一次 validation 與一次 run.py 寫檔。

| Scenario | Input JSON | Skill instruction | validate/run command + stdout | Model output / reasoning | Optional evaluator check | Estimated total |
|---|---:|---:|---:|---:|---:|---:|
| S1 filter + mean | 160–230 | 1,800–2,400 | 350–600 | 300–600 | 400–700 | 3,010–4,530 |
| S2 groupby + sum | 140–220 | 1,800–2,400 | 350–600 | 300–600 | 400–700 | 2,990–4,520 |
| S3 sort + top-k | 160–250 | 1,800–2,400 | 350–650 | 300–650 | 400–750 | 3,010–4,700 |
| S4 value_counts | 140–230 | 1,800–2,400 | 350–600 | 300–600 | 400–700 | 2,990–4,530 |
| S5 filter + nunique | 170–260 | 1,800–2,400 | 350–650 | 300–650 | 400–750 | 3,020–4,710 |

### 7.3 含一次 validation repair 的 worst-case 估算

`SKILL.md` 限制最多兩次 validation calls。如果第一次 query 驗證失敗，Hermes 會根據 validator error 修正一次，並再呼叫一次 `validate_pandas.py`。

額外 token 來源：

- 第二次 validate command：約 150–300 tokens。
- 第二次 validate stdout：約 50–200 tokens。
- 修正 reasoning：約 100–300 tokens。

因此 conservative worst-case：

```text
每個 scenario 約 4k–6k tokens。
極端保守估計低於 8k tokens / scenario。
```

### 7.4 Token budget 結論

此 Open Track skill 的 public scenarios 都是小型表格資料，rows 數量少、columns 數量少、輸出 schema 固定。即使包含一次 validation failure 與 repair，每個 scenario 預估仍低於 8k tokens，遠低於 50k tokens / scenario。

此設計符合 Open Track 的 token budget 要求，也避免將大量測資、長篇說明或完整 scripts 原始碼塞入 `SKILL.md`。主要驗證邏輯由 scripts 執行，而非消耗 context window 讓模型自行判斷。

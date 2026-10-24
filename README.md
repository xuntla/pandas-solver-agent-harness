# Pandas Solver Agent Harness

> 讓本地 LLM Agent 把「表格 + 自然語言問題」轉成一行安全的 pandas 查詢，並用 deterministic validation 與自動評估驗證答案正確性。

> 📚 本專案原為 **TAICA AIASE 2026 課程期末專題（Open Track）** 的作業，課後整理為個人作品集。  
> 作業說明：[TAICA AIASE 2026 Final Project — Open Track](https://ktchuang.github.io/TAICA_AIASE2026/homeworks/TAICA2026_FinalProject.html#2-4-open-track-%E5%BF%85%E5%81%9A-40)

---

## Demo

不需要 LLM 也能直接跑的驗證流程示範（5 個 public scenario + 2 個刻意設計的反例）：

```bash
python examples/run_examples.py
```

```text
task_id                valid  passed  detail
------------------------------------------------------------------------------
pd_public_001          True   True    actual=75000.0
pd_public_002          True   True    actual={"North": 300, "South": 250}
pd_public_003          True   True    actual=["Laptop", "Phone"]
pd_public_004          True   True    actual={"CS": 2, "EE": 1, "Math": 1}
pd_public_005          True   True    actual=2
neg_semantic_wrong     True   False   ANSWER_MISMATCH
neg_unsafe             False  False   VALIDATION_FAILED
```

- `neg_semantic_wrong`：query 語法合法但漏掉篩選條件 → validator 放行，**evaluator 抓出答案錯誤**。
- `neg_unsafe`：使用 `apply` + `lambda` → **validator 在執行前就擋下**。

透過 Hermes Agent 實際解題時，Agent 寫出的結果檔如下：

```json
{
  "task_id": "pd_001",
  "query": "df[df[\"department\"] == \"CS\"][\"salary\"].mean()",
  "answer": 75000.0,
  "answer_type": "number",
  "validation": {"valid": true, "error_count": 0},
  "rationale": "Filter the DataFrame for employees in the CS department and calculate the mean of their salaries.",
  "confidence": 1.0
}
```

---

## 使用技術

| 類別 | 技術 |
|---|---|
| 語言 / 資料處理 | Python 3、pandas 2.2、numpy 2.0 |
| Agent 框架 | [Hermes Agent](https://github.com/NousResearch/hermes-agent)（Skill = `SKILL.md` + `scripts/`） |
| 模型部署 | LM Studio 本地部署 Gemma，透過 OpenAI-compatible API 接入 Hermes |
| 安全檢查 | Python `ast` 白名單解析、受限執行環境 |

## 系統架構

```text
 表格 + 問題 (JSON)
        │
        ▼
 ┌──────────────┐   產生一行 pandas expression
 │ Hermes Agent │◄─────────── SKILL.md（任務規格、工具呼叫流程、禁止事項）
 │  + 本地 LLM   │
 └──────┬───────┘
        │ ① 驗證（最多 2 次，失敗可修正 1 次）
        ▼
 validate_pandas.py   語法 / 安全性 / 允許的 pandas 子集 / 可執行性 / 輸出型態
        │
        │ ② 寫出結果
        ▼
 run.py               JSON-safe 正規化、confidence 限制、原子寫檔
        │
        │ ③ 評估（不信任 Agent 自填的 answer）
        ▼
 evaluator.py         重新執行 query → 與 ground truth 做 deterministic 比對
```

## 主要功能

- **以 `SKILL.md` 定義 Agent 任務規格**：明確規範輸入/輸出 schema、執行步驟、工具呼叫格式、重試上限與常見陷阱，降低 LLM 行為的不確定性。
- **安全的程式生成**：只允許單行、只用 `df` 的 pandas expression；以 AST 白名單禁止 `import`、檔案 I/O、`eval`/`exec`、`lambda`、`apply`、dunder 屬性等。
- **Deterministic validation**：在寫出結果前檢查語法、欄位是否存在、方法是否在允許清單內、能否執行、結果能否依 `answer_type` 正規化。
- **Automated evaluation**：evaluator 不相信模型回報的答案，而是**重新執行 query** 並與 ground truth 比對，支援浮點容差與順序敏感設定，不易被 hardcode 取巧。
- **File-based 輸出契約**：最終結果一律由 `run.py` 寫入檔案，不依賴聊天訊息格式，讓評分可重現。

## 專案結構

```text
.
├── skills/open-pandas-solver-xuntla/
│   ├── SKILL.md                 # Agent 任務規格與執行流程
│   └── scripts/
│       ├── validate_pandas.py   # 中途驗證器（安全性 + 可執行性）
│       ├── run.py               # 最終結果檔寫入器
│       └── evaluator.py         # Deterministic 評估器
├── examples/
│   ├── public_scenarios.json    # 5 個 public scenario + 2 個反例
│   └── run_examples.py          # 免 LLM 的驗證流程示範
└── docs/
    ├── OPEN_TRACK.md            # 完整設計文件（scenario、metric、失敗模式、token 預算）
    └── hermes-config.example.yaml
```

## 執行方式

### 1. 安裝相依套件

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 跑驗證流程示範（不需要 LLM）

```bash
python examples/run_examples.py
```

### 3. 透過 Hermes Agent + 本地模型解題

1. 在 LM Studio 載入 Gemma 模型並啟動 Local Server（預設 `http://localhost:1234/v1`）。
2. 安裝 [Hermes Agent](https://github.com/NousResearch/hermes-agent)，參考 [`docs/hermes-config.example.yaml`](docs/hermes-config.example.yaml) 設定 `~/.hermes/config.yaml`，並依 [`.env.example`](.env.example) 建立 `~/.hermes/.env`。
3. 執行：

```bash
hermes chat --toolsets skills,terminal --yolo -Q -q '/open-pandas-solver-xuntla {
  "task_id": "pd_001",
  "question": "What is the average salary of employees in CS?",
  "columns": ["name", "department", "salary"],
  "rows": [["Alice", "CS", 70000], ["Bob", "EE", 65000], ["Carol", "CS", 80000]],
  "answer_type": "number"
}'
```

結果會寫入 `AIASE_RESULT_PATH` 指定的檔案（未設定時為 `./aiase_result.json`）。

## 我負責的部分

本專案為**個人獨立完成**，包含：

- Open Track 題目選定與 verifiable scenario 設計
- `SKILL.md` 撰寫與迭代（初版草稿有使用 ChatGPT 協助，後續規則與流程由本人修改完善）
- `validate_pandas.py`、`run.py`、`evaluator.py` 實作與測試
- 設計文件 [`docs/OPEN_TRACK.md`](docs/OPEN_TRACK.md)

## 遇到的困難與解法

| 困難 | 解法 |
|---|---|
| **LLM 產生的程式不可信**：可能夾帶 `import`、讀檔或任意 Python | 不讓 Agent 執行任意程式，改為只接受「一行 pandas expression」，並用 AST 白名單 + 受限執行環境驗證，危險語法在執行前就被拒絕。 |
| **語法正確 ≠ 答案正確**：query 可通過驗證但漏掉篩選條件 | 將「合法性」與「正確性」拆成兩層：validator 只負責安全與可執行，evaluator 重新執行 query 並與 ground truth 比對，抓出語意錯誤。 |
| **Shell quoting 破壞 JSON 參數**：pandas 字串用單引號，與 shell 外層的單引號衝突 | 在 `SKILL.md` 中明確規定 query 內一律使用雙引號並以 `\"` escape，並附上正反例。 |
| **Agent 陷入無限修正迴圈或沒有寫出結果** | 在 `SKILL.md` 限制最多 2 次驗證（失敗可修正 1 次），並要求無論信心高低都必須呼叫 `run.py` 寫出合法結果檔。 |
| **結果無法序列化**（`NaN`、`Infinity`、numpy 型別） | `run.py` 統一做 JSON-safe 正規化，confidence 限制在 0–1，並以原子寫檔避免產生半截檔案。 |
| **Agent 可能背答案而非真的解題** | Skill 輸入不提供 `expected`；評分只看重新執行 query 的結果，並可對 row 順序、數值、類別名稱做 perturbation 測試。 |

## 未來改進

- 逐步開放 `.loc`、`.str`、`.dt` 等可驗證的 pandas 子集，提升表達能力
- 改用檔案傳遞 payload，從根本避免 shell quoting 問題
- 增加缺失值、重複值、極端值等 perturbation scenario
- 加入分層 partial credit（query 合法 / 型別正確 / 答案正確）

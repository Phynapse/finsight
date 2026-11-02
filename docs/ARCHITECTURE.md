# FinSight Architecture

## The Core Decision: Why Deterministic Analytics + LLM Explanation?

The dominant pattern for AI-powered analytics is to give a language model access to a database and let it write SQL or Python. This approach has a fundamental flaw for financial data: **language models make arithmetic errors, confuse periods, drop sign conventions, and hallucinate numbers**. In a financial context these errors are not just wrong — they can be plausible-sounding and thus dangerous.

FinSight inverts this. Python/Pandas performs all arithmetic. The LLM receives only a bounded evidence package and explains what it contains. This separation has three consequences:

1. **Every number is reproducible.** Run the same plan against the same data: you get the same figures. No temperature, no sampling, no stochasticity in the numbers.

2. **Every number is testable.** `test_analytics.py` recomputes reference values independently (in plain Python, not via the analyser) and checks they agree. A test failure means the analytics are wrong, not the test harness.

3. **LLM failures degrade gracefully.** If the LLM is slow, unavailable, or returns an unparseable response, the rule-based explanation generator takes over. The answer is less fluent but numerically identical.

---

## Request Lifecycle

```
POST /api/v1/questions
      │
      ▼
 QuestionService
      │
      ├─ 1. QuestionInterpreter.interpret(question)
      │       └─ returns Interpretation (analysis_type, metric, period, confidence)
      │
      ├─ 2. AnalysisPlanner.plan(interpretation)
      │       └─ returns list[AnalysisPlan]  — only catalogued types
      │
      ├─ 3. PlanValidator.validate(plan)    ← security boundary
      │       └─ raises PlanValidationError if anything is outside the catalog
      │
      ├─ 4. For each plan:
      │       AnalysisService.execute(plan)
      │           └─ Analyzer.run(context)  ← Pandas, no I/O, no LLM
      │               └─ AnalyzerOutput (metrics, breakdown, series, methodology)
      │
      ├─ 5. AnalysisService.evidence_for(results)
      │       └─ EvidencePackage  — every item has source_dataset + calculation
      │
      └─ 6. ExplanationGenerator.explain(question, interpretation, evidence)
              └─ ExplanationDraft  — grounded_on: list of evidence IDs
```

---

## Layers and Their Boundaries

### Layer 1: Question Interpretation (`app/ai/`)

**Input:** raw natural-language string  
**Output:** `Interpretation` (Pydantic, frozen dataclass)

Phase 1 uses `DeterministicQuestionInterpreter` — a keyword/regex rule engine. It produces the same `Interpretation` schema that a Phase 2 LLM would produce. The boundary is `Interpretation`: the planner never sees the original question.

Phase 2 replaces the interpreter with an LLM that is prompted to return JSON matching the `Interpretation` schema. The JSON is parsed with Pydantic; a parse failure retries once then falls back to the rule-based interpreter. **The LLM output is treated as untrusted data**, not as a trusted computation.

### Layer 2: Analysis Planning (`app/ai/` + `app/analytics/validator.py`)

**Input:** `Interpretation`  
**Output:** `list[AnalysisPlan]`

`DeterministicAnalysisPlanner` converts an interpretation into one or more `AnalysisPlan` objects. The plan is a closed struct: `analysis_type` must be in `AnalysisType`, `metric` must be in `METRIC_CATALOG`, dimensions and filters must be in the analysis type's allow-lists.

`PlanValidator` is the security boundary. Any plan — whether from a human, a rule engine, or an LLM — passes through the validator before any data is read. This prevents:
- Arbitrary SQL or Python execution
- Access to fields outside the schema
- Comparison of a period with itself
- Dimensions not supported by the analysis type

### Layer 3: Analytics (`app/analytics/`)

**Input:** `AnalysisPlan` + read-only `DatasetRepository`  
**Output:** `AnalyzerOutput` (metrics, breakdown, series, methodology)

Eight deterministic analysers, each registering against one `AnalysisType`. All arithmetic is in Python/Pandas. The analysers receive a read-only `AnalysisContext`; they cannot write to the repository, make network calls, or access the filesystem.

Key invariants enforced here:
- `safe_percentage` returns `None` when the denominator is zero — never NaN, never infinity, never a silent divide
- `absolute_change` returns `None` for missing inputs
- Comparison period values are computed from the same source column, not trusted from a derived file column
- Net cash spend is computed from signed transaction rows, not from the statement total

### Layer 4: Evidence (`app/services/analysis_service.py`)

**Input:** `list[AnalysisResult]`  
**Output:** `EvidencePackage`

Every `EvidenceItem` carries:
- `value` — the computed figure
- `unit` — currency / percent / count / ratio
- `calculation` — the exact formula string
- `source_dataset` — the CSV the number came from
- `is_derived` — False for raw reads, True for computed values
- `comparison_value`, `change`, `percentage_change` — pre-computed, no LLM arithmetic

The explanation generator receives *only* this package. It cannot query the repository or construct its own metrics.

### Layer 5: Explanation (`app/ai/`)

**Input:** `question` + `Interpretation` + `EvidencePackage`  
**Output:** `ExplanationDraft` with `grounded_on: tuple[str, ...]`

Every sentence in `findings` cites one evidence item ID. The `TestExplanationGenerator.test_every_sentence_is_grounded_in_an_evidence_id` test enforces this.

Phase 1 uses `RuleBasedExplanationGenerator`, which assembles sentences by template. Phase 2 replaces this with an LLM prompt that explicitly forbids inventing numbers: "Use only the figures in the supplied evidence. Do not state a number unless it appears in an evidence item." The generated JSON is parsed into `ExplanationDraft`; any cited evidence ID not in the package is stripped before the response is returned.

---

## Security Model

| Threat | Control |
|---|---|
| Arbitrary code execution | AnalysisPlan is a closed struct; validator checks every field against an allow-list |
| Prompt injection | Injection text hits the interpreter first; if it maps to no metric, it returns `unsupported`. The evidence package is never shown to the LLM as instructions. |
| SQL injection | No SQL database. Filter values are applied as Pandas `.isin()` masks on in-memory DataFrames. |
| Oversized bodies | `BodySizeLimitMiddleware` checks `Content-Length` before buffering; streaming bodies are counted byte-by-byte |
| Information leakage | Validation errors do not echo submitted values. `AppError` strips tracebacks. `SecretStr` API keys cannot appear in `repr()` or `model_dump()`. |
| CORS | Explicit allow-list. Non-listed origins receive no `Access-Control-Allow-Origin`. |
| Secret logging | Settings is a Pydantic `BaseSettings` with `SecretStr` fields. Logger receives no settings objects. |

---

## Data Assumptions and Formulas

```python
# Income statement
gross_profit         = revenue - cogs
operating_income     = gross_profit - operating_expenses
gross_margin_pct     = gross_profit / revenue * 100
operating_margin_pct = operating_income / revenue * 100

# Cash flow
operating_expenses   = cash_operating_expenses + non_cash_operating_expenses
cash_balance         = cash_begin + operating_cash_flow + investing_cash_flow + financing_cash_flow
cash_begin[t]        = cash_balance[t-1]

# Ledger
net_spend            = Σ expense_amounts - Σ credit_amounts
# (amount is always positive; sign comes from transaction_type)

# Budget
budget_variance      = actual_amount - budget_amount   # positive = overspend
budget_utilisation   = actual_amount / budget_amount * 100

# Vendor
concentration_pct    = top_5_vendor_net_spend / total_vendor_net_spend * 100
```

All formulas are tested in `test_analytics.py` with independently computed reference values.

---

## Intentionally Out of Scope

- Hosted database (PostgreSQL, SQLite, etc.)
- Kubernetes, Docker Compose, message queues
- Authentication and multi-tenancy
- Real-time data feeds
- Agent frameworks (LangChain, CrewAI, etc.)
- Vector stores for RAG
- Streaming LLM output to the browser (Phase 2)

These exclusions keep the codebase inspectable in a single afternoon and the architecture legible without specialist infrastructure knowledge.
# FinSight Roadmap

## Current State — Phase 1

Phase 1 is complete. The system is fully functional without a language model.

**What works today:**

- Eight deterministic financial analysers (revenue, profitability, expense analysis, expense variance, budget variance, vendor spend, trend, metric snapshot)
- Rule-based question interpreter (keyword + regex)
- Rule-based explanation generator (template sentences grounded on evidence IDs)
- Full `POST /questions` pipeline: question → interpretation → plan → analytics → evidence → explanation
- 231 backend tests pass; 11 frontend tests pass
- React/TypeScript frontend with period selector, question input, and tabbed answer/evidence/analysis view
- Benchmark suite: 15 financial questions tested for planning accuracy, calculation correctness, grounding, and prompt-injection resilience

**Known limitations in Phase 1:**

- Questions without a named metric ("What were the largest expense categories?") return `unsupported` — the rule interpreter needs a metric keyword match
- Transaction ledger covers FY2024 only; 2023 budget/vendor comparisons have no actual-spend data
- Explanation prose is formulaic (template-generated, not model-generated)
- Analysis results are in-memory only; cleared on restart
- No authenticated multi-user sessions

---

## Phase 2 — LLM Interpreter and Explainer

**Goal:** replace the two rule-based AI components with a live LLM while keeping all financial arithmetic deterministic.

### 2.1 LLM Question Interpreter

Replace `DeterministicQuestionInterpreter` with `LLMQuestionInterpreter`.

The model is prompted to return JSON matching `INTERPRETATION_CONTRACT` (defined in `ai/base.py`). Parse failures retry once then fall back to the rule-based interpreter.

Acceptance criteria:
- All 15 benchmark planning cases pass with the LLM implementation
- Questions like "What were the largest expense categories in Q4?" now return `answered` instead of `unsupported`
- Prompt injection test suite still passes (6 injection cases)

### 2.2 LLM Explanation Generator

Replace `RuleBasedExplanationGenerator` with `LLMExplanationGenerator`.

The model receives the question, structured interpretation, and the evidence package. The prompt forbids inventing numbers. Post-processing cross-checks cited values against the evidence package.

Acceptance criteria:
- Every `grounded_on` ID in the response exists in the evidence package
- No number in the generated text is more than 0.5% different from its evidence value
- `test_every_sentence_is_grounded_in_an_evidence_id` passes

### 2.3 Expand metric alias table

Add "categories", "department", "by category", "by department" as aliases for `total_expense` with `EXPENSE_ANALYSIS` as the preferred analysis type.

### 2.4 FY2023 transaction ledger

Add FY2023 transaction rows to `transactions.csv` so year-over-year analyses have full ledger backing. Update integrity checks accordingly.

---

## Phase 3 — UI Enhancement

### 3.1 Analysis Detail page

A dedicated page for inspecting a saved analysis: full breakdown table, time series chart, methodology, warnings.

### 3.2 Dataset Overview page

Show all four datasets with row counts, schema, period coverage, and integrity check results.

### 3.3 Streaming question responses (SSE)

Stream the explanation tokens to the browser as they arrive from the LLM, so the user sees text appearing rather than waiting for the full response.

### 3.4 Chart components

Add a `<SparkLine>` component for trend series and a `<BarChart>` for top-N breakdowns. Use lightweight SVG, not a large charting library.

---

## Phase 4 — Persistence and Multi-session

### 4.1 Optional SQLite store

Replace the in-memory TTL store with an optional SQLite backend. Keep the in-memory default for the portfolio demo.

### 4.2 Session history

Allow the user to navigate back through previous questions in the current session.

### 4.3 Export

Export an analysis result as a PDF or JSON evidence package.

---

## Phase 5 — Evaluation and Hardening

### 5.1 Expand benchmark to 50 cases

Add cases covering:
- Edge cases (Q1 with no prior quarter, all-zero budget, vendor with no transactions)
- Ambiguous questions (multiple plausible interpretations)
- Multi-quarter range questions

### 5.2 Numerical consistency checker

Post-process LLM explanation text and flag any number that does not appear in the evidence package (within a configurable tolerance). Surface flagged explanations as `partially_grounded` in the API response.

### 5.3 Automated regression suite

Run the full benchmark on every pull request and post results as a PR comment.

---

## Out of Scope (Permanently)

- PostgreSQL, Redis, Celery, Kafka
- Kubernetes or Docker Compose
- Authentication and multi-tenancy (beyond the current single-user demo)
- Real-time market data feeds
- Agent frameworks (LangChain, CrewAI, AutoGPT)
- Vector stores for RAG
- ERP integration
- Investment or financial advice features
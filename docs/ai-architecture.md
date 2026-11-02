# FinSight AI Architecture

## The Boundary That Matters

Language models make arithmetic errors on financial data. They confuse periods, drop sign conventions, hallucinate transactions, and produce plausible-sounding figures that are simply wrong. In a financial context this is not just inaccurate — it is misleading.

FinSight draws a hard boundary:

```
WHAT THE LLM DOES              WHAT PYTHON/PANDAS DOES
─────────────────────          ─────────────────────────
Interpret the question         All arithmetic
Classify the intent            All aggregation
Choose a metric                All period comparison
Choose a period                All variance calculation
Choose analysis type           All budget reconciliation
Explain computed evidence      All concentration metrics
                               All data access
```

The LLM never sees a raw DataFrame. It never performs a calculation. It explains a bounded, pre-validated evidence package — and every sentence it produces must cite an evidence item ID from that package.

---

## Phase 1 Architecture (No LLM Required)

Phase 1 ships deterministic rule-based implementations of all three AI-layer interfaces. The system is fully functional without any API key.

```
POST /questions
     │
     ▼
DeterministicQuestionInterpreter    ← keyword/regex rules
     │  Interpretation (frozen dataclass)
     ▼
DeterministicAnalysisPlanner        ← catalog lookup + comparison mode logic
     │  list[AnalysisPlan]
     ▼
PlanValidator                       ← security boundary
     │  validated plan
     ▼
[8 deterministic analysers]         ← Pandas, no I/O, no model
     │  AnalyzerOutput
     ▼
AnalysisService.evidence_for()      ← builds bounded EvidencePackage
     │  EvidencePackage
     ▼
RuleBasedExplanationGenerator       ← template sentences grounded on evidence IDs
     │  ExplanationDraft
     ▼
QuestionService                     ← assembles Answer response
```

---

## Phase 2 Architecture (LLM Interpreter + Explainer)

Phase 2 replaces two components. Nothing else changes.

### Replacing the Interpreter

`DeterministicQuestionInterpreter` → `LLMQuestionInterpreter`

The LLM is prompted to return JSON matching the `Interpretation` schema (defined in `ai/base.py` as `INTERPRETATION_CONTRACT`). The response is:

1. Parsed with Pydantic — hard failure if unparseable
2. Retried once on parse failure
3. Fallen back to the rule-based interpreter on second failure
4. **Never executed directly** — the resulting `Interpretation` still passes through `DeterministicAnalysisPlanner` and `PlanValidator`

The LLM cannot produce an `Interpretation` that bypasses the validator. The validator runs regardless of how the interpretation was produced.

### Replacing the Explainer

`RuleBasedExplanationGenerator` → `LLMExplanationGenerator`

The LLM receives:
- The original question
- The `Interpretation` (structured, no raw text)
- The `EvidencePackage` (bounded set of pre-computed facts)

The prompt explicitly forbids:
- Inventing numbers not present in the evidence
- Stating causal explanations the data does not establish
- Referencing periods, departments or vendors not in the evidence

The response is parsed into `ExplanationDraft`. Any `grounded_on` IDs not present in the evidence package are stripped before the response is returned.

---

## Interface Contracts

Three `Protocol` classes in `app/ai/base.py` define the contract every implementation must satisfy:

```python
class QuestionInterpreter(Protocol):
    name: str
    def interpret(self, question: str) -> Interpretation: ...

class AnalysisPlanner(Protocol):
    name: str
    def plan(self, interpretation: Interpretation) -> list[AnalysisPlan]: ...

class ExplanationGenerator(Protocol):
    name: str
    model: str | None
    def explain(self, *, question, interpretation, evidence) -> ExplanationDraft: ...
```

Any component satisfying these protocols can be injected at startup via `build_pipeline(settings, repository)`.

---

## What the LLM Cannot Do

These constraints are enforced by the system, not by the prompt alone:

| Forbidden action | How it is prevented |
|---|---|
| Execute arbitrary Python | No code execution path exists anywhere in the system |
| Query a file or database | Analysers receive a read-only `DatasetRepository`; the LLM never touches it |
| Access the filesystem | Settings resolve paths at startup; no user-controlled path is ever opened |
| Produce an analysis type not in the catalog | `PlanValidator.validate()` raises `UnknownAnalysisTypeError` |
| Produce a metric not in the catalog | `PlanValidator.validate()` raises `UnknownMetricError` |
| Access a period not in the dataset | `PlanValidator._validate_periods()` rejects unknown periods |
| Invent a number in the explanation | `ExplanationDraft.grounded_on` is checked against evidence IDs; orphans are stripped |
| Inject a prompt through the question | The question is passed to the interpreter; if it maps to no metric, status = `unsupported` |

---

## LLM Configuration

```env
LLM_PROVIDER=disabled      # openai | anthropic | ollama | disabled
LLM_MODEL=
LLM_API_KEY=               # SecretStr — never logged
LLM_BASE_URL=              # Override for Ollama, Azure OpenAI, etc.
LLM_TIMEOUT_SECONDS=20
LLM_MAX_TOKENS=1200
```

When `LLM_PROVIDER=disabled` or no API key is set, `build_pipeline()` wires in the Phase 1 implementations. The API returns `"llm_enabled": false` in every response. All numbers are still deterministic and correct.

---

## Hallucination Controls

1. **Evidence grounding.** Every sentence in the explanation must cite an evidence ID. The test `test_every_sentence_is_grounded_in_an_evidence_id` enforces this for the rule-based implementation; the same test will apply to the LLM implementation.

2. **Bounded evidence.** The evidence package is capped at 200 items. The LLM cannot request more data.

3. **Source attribution.** Every `EvidenceItem` carries `source_dataset` and `calculation`. The explanation prompt will require citing these when stating a number.

4. **Numerical cross-checking.** Phase 2 will post-process the generated text and verify that any number it states (after stripping currency symbols and commas) appears in the evidence package values. Unverifiable numbers will be replaced with `[unverified]` before the response is sent.

5. **Retry and fallback.** One LLM retry on timeout or parse failure. Fallback to rule-based on second failure. The user always gets an answer; it may be less fluent.

---

## Financial Safety Disclaimer

FinSight describes observations about a **synthetic dataset**. It is not:

- An investment adviser
- A financial adviser
- An accounting system
- A source of audited financial statements

The system does not make predictions. It does not make recommendations. When the dataset does not establish causality, the explanation says so:

> "Software spending increased by 18%. The dataset does not establish the operational cause of that increase."

This framing is enforced in the explanation prompt and in the caveat system.
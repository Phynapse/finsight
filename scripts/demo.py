"""End-to-end demo: 'Why did operating expenses increase in Q3?'

This script runs the complete pipeline without mocking anything:
  Question → plan → deterministic calculation → evidence → grounded explanation

Run with:
    python scripts/demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make backend importable when run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def hr(char: str = "-", width: int = 72) -> None:
    print(char * width)


def main() -> None:
    settings = Settings(app_env="test", log_level="ERROR")
    with TestClient(create_app(settings)) as client:
        hr("═")
        print("  FinSight — End-to-end Demo")
        print("  Question: 'Why did operating expenses increase in Q3?'")
        hr("═")

        question = "Why did operating expenses increase in 2024-Q4?"
        response = client.post("/api/v1/questions", json={"question": question})
        assert response.status_code == 200, f"Unexpected status: {response.status_code}"
        body = response.json()

        # ── Step 1: Question interpretation ───────────────────────────────────
        interp = body["interpretation"]
        hr()
        print("STEP 1 — QUESTION INTERPRETATION")
        hr()
        print(f"  Restated   : {interp['restated_question']}")
        print(f"  Intent     : {interp['intent']}")
        print(f"  Analysis   : {interp['analysis_type']}")
        print(f"  Metric     : {interp['metric']}")
        print(f"  Period     : {interp['period']}")
        print(f"  Confidence : {interp['confidence'] * 100:.0f}%")
        print(f"  Strategy   : {interp['strategy']}")

        # ── Step 2: Analysis plan ──────────────────────────────────────────────
        plan = body["plan"]
        hr()
        print("STEP 2 — ANALYSIS PLAN (validated)")
        hr()
        print(f"  analysis_type    : {plan['analysis_type']}")
        print(f"  metric           : {plan['metric']}")
        print(f"  period           : {plan['period']}")
        print(f"  comparison_mode  : {plan['comparison_mode']}")

        # ── Step 3: Deterministic analytics ───────────────────────────────────
        hr()
        print("STEP 3 — DETERMINISTIC ANALYTICS (Python / Pandas)")
        hr()
        for analysis in body["analyses"]:
            print(f"  [{analysis['analysis_type']}]  {analysis['period']} vs {analysis.get('comparison_period','—')}")
            for metric in analysis["metrics"]:
                val = f"{metric['value']:>14,.2f} {metric['unit']:8}"
                cmp = f"(prior: {metric['comparison_value']:,.2f}, Δ{metric['percentage_change']:+.2f}%)" if metric.get("comparison_value") else ""
                print(f"    {metric['label']:35} {val} {cmp}")
            print(f"  Methodology:")
            for m in analysis["methodology"]:
                print(f"    • {m}")
            print(f"  Duration: {analysis['duration_ms']:.1f} ms")

        # ── Step 4: Evidence ───────────────────────────────────────────────────
        evidence = body["evidence"]
        hr()
        print("STEP 4 — EVIDENCE PACKAGE")
        hr()
        print(f"  {len(evidence['evidence'])} items  |  datasets: {evidence['datasets_used']}  |  periods: {evidence['periods_covered']}")
        for item in evidence["evidence"][:6]:
            cmp_s = f"  cmp={item['comparison_value']:.2f}" if item.get("comparison_value") else ""
            print(f"  {item['id']:7} {item['metric']:25} {item['value']:>14,.2f} {item['unit']:8}{cmp_s}  [{item['source_dataset']}]")
        if len(evidence["evidence"]) > 6:
            print(f"  … {len(evidence['evidence']) - 6} more items")

        # ── Step 5: Grounded explanation ───────────────────────────────────────
        expl = body["explanation"]
        hr()
        print("STEP 5 — GROUNDED EXPLANATION")
        hr()
        print(f"  Provider   : {expl['provider']}")
        print(f"  LLM used   : {body['llm_enabled']}")
        print()
        print(f"  Summary:")
        print(f"    {expl['summary']}")
        print()
        if expl["findings"]:
            print(f"  Key findings:")
            for f in expl["findings"]:
                print(f"    • {f}")
        print()
        print(f"  Grounded on evidence IDs: {expl['grounded_on']}")

        # ── Caveats ────────────────────────────────────────────────────────────
        if body["caveats"]:
            hr()
            print("CAVEATS")
            hr()
            for c in body["caveats"]:
                print(f"  ⚠  {c}")

        # ── Summary ────────────────────────────────────────────────────────────
        hr("═")
        print(f"  STATUS: {body['status'].upper()}")
        print(f"  Total duration: {body['duration_ms']:.1f} ms")
        print(f"  Answer ID: {body['answer_id']}")
        hr("═")

        # ── Numerical consistency check ────────────────────────────────────────
        evidence_values = {item["id"]: item["value"] for item in evidence["evidence"]}
        cited_ids = set(expl["grounded_on"])
        missing = cited_ids - set(evidence_values)
        if missing:
            print(f"\n  !! GROUNDING FAILURE: {missing} cited but not in evidence")
            sys.exit(1)
        else:
            print("  Grounding check PASSED — every cited ID is in the evidence package.")

        # Verify the headline number is in the summary — use the first evidence item's value.
        first_item = evidence["evidence"][0] if evidence["evidence"] else None
        if first_item and first_item.get("comparison_value"):
            val_digits = str(int(abs(first_item["value"]))).replace(",", "")
            summary_clean = body["explanation"]["summary"].replace(",", "").replace(".", "")
            assert val_digits in summary_clean, (
                f"Headline value {first_item['value']} not found in summary: {body['explanation']['summary']}"
            )
            print("  Numerical consistency check PASSED — headline value in explanation summary.")

        print()
        print("  Demo complete. All checks passed.")


if __name__ == "__main__":
    main()
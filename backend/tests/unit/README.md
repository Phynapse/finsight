# Test Organisation
#
# Currently all tests live flat in this directory. The planned organisation:
#
#   unit/         — Pure unit tests: numeric helpers, schemas, analytics primitives
#                   Corresponds to: test_numeric_helpers.py, test_plan_validator.py
#
#   integration/  — Tests that use the full application stack (TestClient, real datasets)
#                   Corresponds to: test_api.py, test_benchmark.py
#
#   fixtures/     — Shared pytest fixtures and synthetic test data
#                   Corresponds to: conftest.py, sample CSVs for edge-case testing
#
# Migration to the nested structure is planned for Phase 2 (see docs/roadmap.md).
# All 231 tests currently pass from this flat layout.

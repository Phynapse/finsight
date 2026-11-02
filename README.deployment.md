# FinSight - Deployment Guide

## Overview

FinSight is a financial intelligence demonstration that applies deterministic analytics with grounded AI explanations to synthetic financial data. The system consists of:

- **Backend**: FastAPI application (Python 3.12+) serving a deterministic analytics engine
- **Frontend**: React + Vite dashboard for API interaction
- **Data**: Synthetic CSV datasets representing FY2023-FY2024 financials

**Core principle**: The LLM never calculates financial values — it only interprets questions and explains validated evidence. All arithmetic lives in Python/Pandas.

---

## Prerequisites

- [Python 3.12+](https://www.python.org/downloads/release/python312/)
- [Node.js 18+](https://nodejs.org/) (for frontend)
- [Git](https://git-scm.com/downloads)

---

## Quick Start (Development)

### 1. Clone and enter

```bash
git clone <repo>
cd FinSight
```

### 2. Backend

```bash
python -m pip install -r backend/requirements.txt
cp .env.example .env  # review and adjust values if needed
python -m uvicorn app.main:app --app-dir backend --reload
# → http://localhost:8000  (API docs at /docs)
```

### 3. Frontend (separate terminal)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### 4. Generate synthetic data (if needed)

```bash
python scripts/generate_data.py
# Produces data/financial_data.csv, data/transactions.csv, data/budgets.csv, data/vendors.csv
```

### 5. Run tests

```bash
# Backend
python -m pytest backend/tests/  # 231 tests

# Frontend
cd frontend && npm test  # 11 tests
```

---

## Production Deployment

### Using Docker (recommended)

```bash
# Build
docker build -t finsight .

# Run
docker run -p 8000:8000 -p 5173:5173 finsight
```

*Dockerfile is configured to:*
- Install backend dependencies and run uvicorn on port 8000
- Install frontend dependencies and run Vite on port 5173
- Copy generated data from `data/` directory
- Use `.env` configuration

### Manual Production

```bash
# Backend
cd backend
python -m pip install -r requirements.txt --quiet
# Set production environment
set APP_ENV=production
set LOG_LEVEL=WARNING
# Start with production workers
python -m uvicorn app.main:app --app-dir backend --workers 4 --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm run build  # creates dist/
# Serve static files with your preferred web server
```

---

## Environment Configuration

Copy `.env.example` to `.env` and adjust as needed:

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Environment name |
| `DATA_DIR` | `data` | Path to CSV files |
| `API_PREFIX` | `/api/v1` | URL prefix |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins |
| `MAX_REQUEST_BYTES` | `16384` | Body size cap |
| `LLM_PROVIDER` | `disabled` | `openai`, `anthropic`, `ollama`, or `disabled` |
| `LLM_API_KEY` | _(none)_ | API key — never logged |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `LOG_JSON` | `false` | JSON lines output for log shippers |

**Important**: When `LLM_PROVIDER` is `disabled` (default), the system runs fully deterministically. All financial numbers are computed in Python/Pandas regardless of this setting.

---

## API Endpoints

```
GET  /api/v1/health                         Liveness + readiness
GET  /api/v1/capabilities                   Metric catalog, analysis types, periods
GET  /api/v1/datasets                       List bundled datasets
GET  /api/v1/datasets/{id}/summary          Metadata + integrity checks
POST /api/v1/analysis                       Execute a deterministic analysis plan
GET  /api/v1/analysis/{id}                  Retrieve a previous result
GET  /api/v1/analysis/{id}/evidence         Evidence package for a result
POST /api/v1/questions                      Full pipeline: question → answer
```

Interactive documentation: `http://localhost:8000/docs`

**Example question payload**:

```json
{
  "question": "Why did operating expenses increase in 2024-Q4?"
}
```

Response includes: status, interpretation, plan, analyses, explanation, caveats, llm_enabled, and answer_id.

---

## Data Management

- Datasets are stored in `data/` as CSV files
- Regenerate data: `python scripts/generate_data.py`
- Data is synthetic only — not real financial data
- All 11 integrity checks validate internal consistency at startup

---

## License

MIT. See `LICENSE`.

---

## Known Limitations

- Phase 1 uses rule-based interpretation; Phase 2 adds LLM with schema enforcement
- Ledger covers FY2024 only; 2023 budget/vendor data has no actual-spend
- In-memory store cleared on restart; analysis IDs are ephemeral
- Concentration metrics use `vendor_id` foreign key (one-to-one with vendor spend)
- Rule-based explanation generator produces formulaic narratives
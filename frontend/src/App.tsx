import { useState, useEffect, useCallback } from 'react';
import { api } from './lib/api';
import type { QuestionAnswer, AnalysisResult, FinancialMetric } from './lib/types';
import { formatValue, formatChange, analysisTypeLabel } from './lib/format';
import { MetricTile } from './components/MetricTile';
import { EvidenceTable } from './components/EvidenceTable';
import { DatasetsPage } from './pages/DatasetsPage';

const EXAMPLE_QUESTIONS = [
  'How did operating margin change in 2024-Q4?',
  'Why did operating expenses increase in 2024-Q4?',
  'Which vendors drive the most spend?',
  'What is the revenue trend?',
  'How much did expenses vary against budget in 2024-Q4?',
  'What was gross profit in 2024-Q3 vs 2024-Q2?',
];

const PERIODS = ['2023-Q1','2023-Q2','2023-Q3','2023-Q4','2024-Q1','2024-Q2','2024-Q3','2024-Q4'];

type Page = 'ask' | 'datasets';

// ── Breakdown table ─────────────────────────────────────────────────────────────
function BreakdownTable({ result }: { result: AnalysisResult }) {
  const rows = result.breakdown;
  if (!rows.length) return null;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead>
          <tr>
            <th>Dimension</th><th>Key</th>
            <th className="num">Value</th>
            <th className="num">Prior</th>
            <th className="num">Change</th>
            <th className="num">Δ%</th>
            <th className="num">Share</th>
            <th className="num">Contribution</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const chgClass = row.percentage_change == null ? '' :
              row.percentage_change > 0.01 ? 'up' : row.percentage_change < -0.01 ? 'down' : 'flat';
            return (
              <tr key={i}>
                <td className="mono">{row.dimension}</td>
                <td>{row.label}</td>
                <td className="num">{row.value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                <td className="num">
                  {row.comparison_value != null
                    ? row.comparison_value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
                    : '—'}
                </td>
                <td className={`num ${chgClass}`}>
                  {row.change != null ? formatChange(row.change) : '—'}
                </td>
                <td className={`num ${chgClass}`}>
                  {row.percentage_change != null ? `${row.percentage_change.toFixed(2)}%` : '—'}
                </td>
                <td className="num">
                  {row.share_of_total_pct != null ? `${row.share_of_total_pct.toFixed(1)}%` : '—'}
                </td>
                <td className="num">
                  {row.contribution_to_change_pct != null ? `${row.contribution_to_change_pct.toFixed(1)}%` : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Single analysis result ──────────────────────────────────────────────────────
function AnalysisCard({ result }: { result: AnalysisResult }) {
  const [tab, setTab] = useState<'metrics' | 'breakdown' | 'series' | 'methodology'>('metrics');
  return (
    <div className="card">
      <div className="card-header">
        <span className="badge badge-blue">{analysisTypeLabel(result.analysis_type)}</span>
        <span className="card-title">{result.metric}</span>
        {result.period && <span className="mono" style={{ fontSize: 12, marginLeft: 'auto', color: 'var(--muted)' }}>{result.period}{result.comparison_period ? ` vs ${result.comparison_period}` : ''}</span>}
        <span className="badge badge-green" style={{ marginLeft: result.period ? 0 : 'auto' }}>
          {result.status}
        </span>
      </div>
      <div className="card-body">
        {result.metrics.length > 0 && (
          <div className="metric-grid" style={{ marginBottom: 16 }}>
            {result.metrics.map(m => <MetricTile key={m.id} metric={m} />)}
          </div>
        )}
        <div className="tabs" style={{ marginBottom: 12 }}>
          {(['metrics','breakdown','series','methodology'] as const).map(t => (
            <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
              {t === 'breakdown' && result.breakdown.length ? ` (${result.breakdown.length})` : ''}
              {t === 'series' && result.series.length ? ` (${result.series.length})` : ''}
            </button>
          ))}
        </div>
        {tab === 'metrics' && (
          <table className="data-table">
            <thead><tr><th>Metric</th><th>Formula</th><th className="num">Value</th><th className="num">Prior</th><th className="num">Δ%</th></tr></thead>
            <tbody>
              {result.metrics.map(m => (
                <tr key={m.id}>
                  <td>{m.label}</td>
                  <td className="mono">{m.calculation}</td>
                  <td className="num">{formatValue(m.value, m.unit, m.currency)}</td>
                  <td className="num">{m.comparison_value != null ? formatValue(m.comparison_value, m.unit, m.currency) : '—'}</td>
                  <td className={`num ${m.percentage_change == null ? '' : m.percentage_change > 0 ? 'up' : m.percentage_change < 0 ? 'down' : 'flat'}`}>
                    {m.percentage_change != null ? `${m.percentage_change > 0 ? '+' : ''}${m.percentage_change.toFixed(2)}%` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {tab === 'breakdown' && <BreakdownTable result={result} />}
        {tab === 'series' && (
          result.series.length ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead><tr><th>Period</th><th className="num">Value</th><th className="num">Prior</th><th className="num">Δ%</th></tr></thead>
                <tbody>
                  {result.series.map((row, i) => (
                    <tr key={i}>
                      <td className="mono">{row.key}</td>
                      <td className="num">{row.value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className="num">{row.comparison_value != null ? row.comparison_value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</td>
                      <td className={`num ${row.percentage_change == null ? '' : row.percentage_change > 0 ? 'up' : row.percentage_change < 0 ? 'down' : 'flat'}`}>
                        {row.percentage_change != null ? `${row.percentage_change > 0 ? '+' : ''}${row.percentage_change.toFixed(2)}%` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p style={{ color: 'var(--muted)', fontSize: 13 }}>No series data.</p>
        )}
        {tab === 'methodology' && (
          <ul className="method-list">
            {result.methodology.map((m, i) => <li key={i}>{m}</li>)}
            {result.warnings.map((w, i) => (
              <li key={`w${i}`} style={{ color: 'var(--amber)', background: 'var(--amber-l)', padding: '4px 8px', borderRadius: 4 }}>⚠ {w}</li>
            ))}
          </ul>
        )}
        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--muted)' }}>
          {result.row_count} row(s) · {result.duration_ms.toFixed(1)} ms · {result.datasets_used.join(', ')}
        </div>
      </div>
    </div>
  );
}

// ── Answer panel ────────────────────────────────────────────────────────────────
function AnswerPanel({ answer, onClear }: { answer: QuestionAnswer; onClear: () => void }) {
  const [tab, setTab] = useState<'answer' | 'evidence' | 'analysis' | 'plan'>('answer');
  const statusBadge = answer.status === 'answered' ? 'badge-green' : answer.status === 'unsupported' ? 'badge-amber' : 'badge-red';

  return (
    <div className="card">
      <div className="card-header">
        <span className={`badge ${statusBadge}`}>{answer.status}</span>
        <span className="card-title" style={{ flex: 1, fontSize: 14, fontWeight: 500 }}>
          {answer.question}
        </span>
        <button onClick={onClear} style={{ border: 'none', background: 'none', color: 'var(--muted)', fontSize: 18, lineHeight: 1, cursor: 'pointer' }}>×</button>
      </div>
      <div className="card-body">
        <div className="tabs" style={{ marginBottom: 16 }}>
          {(['answer','evidence','analysis','plan'] as const).map(t => (
            <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
              {t === 'evidence' && answer.evidence.evidence.length ? ` (${answer.evidence.evidence.length})` : ''}
              {t === 'analysis' && answer.analyses.length ? ` (${answer.analyses.length})` : ''}
            </button>
          ))}
        </div>

        {tab === 'answer' && (
          <div>
            {answer.status === 'answered' && (
              <>
                <div className="answer-box">
                  <div className="answer-summary">{answer.explanation.summary}</div>
                  {answer.explanation.findings.length > 0 && (
                    <ul className="answer-findings">
                      {answer.explanation.findings.map((f, i) => <li key={i}>{f}</li>)}
                    </ul>
                  )}
                </div>
                <div style={{ marginTop: 12 }}>
                  <div className="section-label">Interpretation</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 4 }}>
                    {answer.interpretation.restated_question}
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
                    {answer.interpretation.metric && (
                      <span className="badge badge-blue">metric: {answer.interpretation.metric}</span>
                    )}
                    {answer.interpretation.analysis_type && (
                      <span className="badge badge-grey">type: {analysisTypeLabel(answer.interpretation.analysis_type)}</span>
                    )}
                    {answer.interpretation.period && (
                      <span className="badge badge-grey">period: {answer.interpretation.period}</span>
                    )}
                    <span className="badge badge-grey">confidence: {(answer.interpretation.confidence * 100).toFixed(0)}%</span>
                  </div>
                  {answer.interpretation.notes.length > 0 && (
                    <ul className="caveat-list" style={{ marginTop: 8 }}>
                      {answer.interpretation.notes.map((n, i) => <li key={i}>ℹ {n}</li>)}
                    </ul>
                  )}
                </div>
              </>
            )}
            {answer.status === 'unsupported' && (
              <div>
                <p style={{ color: 'var(--muted)', marginBottom: 8 }}>{answer.explanation.summary}</p>
                {answer.explanation.findings.map((f, i) => <p key={i} style={{ fontSize: 13 }}>{f}</p>)}
              </div>
            )}
            {answer.caveats.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div className="section-label">Caveats</div>
                <ul className="caveat-list">
                  {answer.caveats.map((c, i) => <li key={i}>{c}</li>)}
                </ul>
              </div>
            )}
            <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)' }}>
              {answer.llm_enabled ? '🤖 LLM explanation' : '⚙ Rule-based explanation'} ·
              {answer.explanation.provider} · {answer.duration_ms.toFixed(1)} ms
            </div>
          </div>
        )}

        {tab === 'evidence' && (
          <div>
            {answer.evidence.periods_covered.length > 0 && (
              <div style={{ marginBottom: 8, fontSize: 12, color: 'var(--muted)' }}>
                Periods: {answer.evidence.periods_covered.join(', ')} ·
                Datasets: {answer.evidence.datasets_used.join(', ')}
              </div>
            )}
            <EvidenceTable items={answer.evidence.evidence} />
          </div>
        )}

        {tab === 'analysis' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {answer.analyses.length === 0
              ? <p style={{ color: 'var(--muted)', fontSize: 13 }}>No analyses were executed.</p>
              : answer.analyses.map(a => <AnalysisCard key={a.analysis_id} result={a} />)
            }
          </div>
        )}

        {tab === 'plan' && answer.plan && (
          <div>
            <div className="section-label" style={{ marginBottom: 8 }}>Analysis Plan</div>
            <table className="data-table">
              <tbody>
                {Object.entries(answer.plan).map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ fontWeight: 600, width: 160 }}>{k}</td>
                    <td className="mono">{JSON.stringify(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Dashboard sidebar ───────────────────────────────────────────────────────────
function Dashboard({ selectedPeriod, onPeriodChange }: { selectedPeriod: string; onPeriodChange: (p: string) => void }) {
  const [metrics, setMetrics] = useState<FinancialMetric[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    api.ask(`What is the profitability summary for ${selectedPeriod} compared to the prior quarter?`)
      .then(answer => {
        const analyses = answer.analyses;
        if (analyses.length) setMetrics(analyses[0].metrics);
      })
      .catch(() => setMetrics(null))
      .finally(() => setLoading(false));
  }, [selectedPeriod]);

  return (
    <div className="sidebar">
      <div>
        <div className="section-label">Period</div>
        <div className="period-grid">
          {PERIODS.map(p => (
            <button
              key={p}
              className={`period-btn ${p === selectedPeriod ? 'selected' : ''}`}
              onClick={() => onPeriodChange(p)}
            >{p}</button>
          ))}
        </div>
      </div>
      <div>
        <div className="section-label">Key Metrics — {selectedPeriod}</div>
        {loading && <div style={{ display: 'flex', gap: 8, alignItems: 'center', color: 'var(--muted)', fontSize: 13 }}><span className="spinner" /> Loading…</div>}
        {metrics && !loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {metrics.map(m => <MetricTile key={m.id} metric={m} />)}
          </div>
        )}
      </div>
    </div>
  );
}

// ── App ─────────────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState<Page>('ask');
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<QuestionAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPeriod, setSelectedPeriod] = useState('2024-Q4');

  const ask = useCallback(async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const result = await api.ask(q);
      setAnswer(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Unexpected error.');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    ask(question);
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-logo">Fin<span>Sight</span></div>
        <div className="topbar-badge">Synthetic data · Not financial advice</div>
        <nav className="topbar-nav">
          <button className={`nav-btn ${page === 'ask' ? 'active' : ''}`} onClick={() => setPage('ask')}>
            Ask FinSight
          </button>
          <button className={`nav-btn ${page === 'datasets' ? 'active' : ''}`} onClick={() => setPage('datasets')}>
            Datasets
          </button>
          <a href="/docs" target="_blank" className="nav-btn">API Docs</a>
        </nav>
      </header>

      {page === 'datasets' ? (
        <DatasetsPage />
      ) : (
      <div className="main">
        <Dashboard selectedPeriod={selectedPeriod} onPeriodChange={setSelectedPeriod} />

        <main className="content">
          {/* Ask FinSight */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Ask FinSight</span>
              <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 8 }}>
                Every number is computed deterministically in Python — not by the AI.
              </span>
            </div>
            <div className="card-body">
              <form onSubmit={handleSubmit} className="question-form">
                <input
                  className="question-input"
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  placeholder="e.g. Why did operating expenses increase in 2024-Q4?"
                  maxLength={500}
                  disabled={loading}
                />
                <button className="submit-btn" type="submit" disabled={loading || !question.trim()}>
                  {loading ? <span className="spinner" /> : 'Analyse'}
                </button>
              </form>
              <div style={{ marginTop: 10 }}>
                {EXAMPLE_QUESTIONS.map(q => (
                  <button
                    key={q}
                    className="example-chip"
                    onClick={() => { setQuestion(q); ask(q); }}
                  >{q}</button>
                ))}
              </div>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div style={{ padding: '12px 16px', background: 'var(--red-l)', border: '1px solid #fca5a5', borderRadius: 'var(--radius)', color: 'var(--red)', fontSize: 13 }}>
              ⚠ {error}
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: 16, color: 'var(--muted)' }}>
              <span className="spinner" />
              <span>Running deterministic analytics…</span>
            </div>
          )}

          {/* Answer */}
          {answer && <AnswerPanel answer={answer} onClear={() => setAnswer(null)} />}

          {/* Empty state */}
          {!answer && !loading && !error && (
            <div style={{ textAlign: 'center', padding: '60px 24px', color: 'var(--muted)' }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>📊</div>
              <h3 style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>Ask a financial question</h3>
              <p style={{ fontSize: 13 }}>
                FinSight runs deterministic Python/Pandas analytics against the synthetic dataset,
                then explains the evidence without inventing numbers.
              </p>
              <p style={{ fontSize: 12, marginTop: 8 }}>
                All data is synthetic · Not financial advice
              </p>
            </div>
          )}
        </main>
      </div>
      )}
    </div>
  );
}
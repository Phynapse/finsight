import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import type { DatasetSummary } from '../lib/types';

export function DatasetsPage() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<DatasetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api.datasets()
      .then(r => setDatasets(r.datasets))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleSelect = async (id: string) => {
    if (selected === id) { setSelected(null); setDetail(null); return; }
    setSelected(id);
    try {
      const r = await fetch(`/api/v1/datasets/${id}/summary`);
      const body = await r.json() as DatasetSummary;
      setDetail(body);
    } catch (e) {
      setDetail(null);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 24, display: 'flex', gap: 8, alignItems: 'center', color: 'var(--muted)' }}>
        <span className="spinner" /> Loading datasets…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24, color: 'var(--red)', background: 'var(--red-l)', borderRadius: 6, margin: 24 }}>
        ⚠ {error}
      </div>
    );
  }

  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div>
        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Datasets</h2>
        <p style={{ color: 'var(--muted)', fontSize: 13 }}>
          Four synthetic CSV files bundled with the application. No real company data.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px,1fr))', gap: 12 }}>
        {datasets.map(ds => (
          <button
            key={ds.id}
            onClick={() => handleSelect(ds.id)}
            style={{
              textAlign: 'left', cursor: 'pointer',
              border: `1px solid ${selected === ds.id ? 'var(--accent)' : 'var(--border)'}`,
              borderRadius: 6, padding: 14, background: selected === ds.id ? 'var(--accent-l)' : 'var(--surface)',
              boxShadow: 'var(--shadow)',
            }}
          >
            <div style={{ fontWeight: 700, fontSize: 13, color: selected === ds.id ? 'var(--accent)' : 'var(--text)', marginBottom: 4 }}>
              {ds.id}
            </div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>{ds.label}</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <span className="badge badge-grey">{ds.row_count} rows</span>
              <span className="badge badge-grey">{ds.column_count} cols</span>
            </div>
          </button>
        ))}
      </div>

      {detail && selected && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">{detail.id}</span>
            <span style={{ fontSize: 12, color: 'var(--muted)', marginLeft: 8 }}>{detail.description}</span>
            <button
              onClick={() => { setSelected(null); setDetail(null); }}
              style={{ marginLeft: 'auto', border: 'none', background: 'none', color: 'var(--muted)', fontSize: 18, cursor: 'pointer', lineHeight: 1 }}
            >×</button>
          </div>
          <div className="card-body">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px,1fr))', gap: 12, marginBottom: 16 }}>
              {[
                ['Rows', detail.row_count],
                ['Columns', detail.column_count],
                ['Period start', detail.period_start ?? '—'],
                ['Period end', detail.period_end ?? '—'],
                ['Metrics', detail.metrics?.length ?? '—'],
              ].map(([label, value]) => (
                <div key={String(label)} style={{ padding: '10px 14px', border: '1px solid var(--border)', borderRadius: 6 }}>
                  <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '.5px', fontWeight: 600, marginBottom: 4 }}>{label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>{String(value)}</div>
                </div>
              ))}
            </div>

            {detail.integrity_checks?.length > 0 && (
              <div>
                <div className="section-label" style={{ marginBottom: 8 }}>Integrity Checks</div>
                <table className="data-table">
                  <thead>
                    <tr><th>ID</th><th>Description</th><th>Status</th><th>Observed</th></tr>
                  </thead>
                  <tbody>
                    {detail.integrity_checks.map(chk => (
                      <tr key={chk.id}>
                        <td className="mono">{chk.id}</td>
                        <td>{chk.description}</td>
                        <td>
                          <span className={`badge ${chk.passed ? 'badge-green' : 'badge-red'}`}>
                            {chk.passed ? 'pass' : 'fail'}
                          </span>
                        </td>
                        <td className="mono" style={{ fontSize: 12 }}>{chk.observed}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
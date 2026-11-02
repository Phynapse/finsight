import type { FinancialMetric } from '../lib/types';
import { formatValue } from '../lib/format';

interface Props {
  metric: FinancialMetric;
}

export function MetricTile({ metric }: Props) {
  const val = formatValue(metric.value, metric.unit, metric.currency);
  const chg = metric.percentage_change;
  const cls = chg == null ? 'flat' : chg > 0.01 ? 'up' : chg < -0.01 ? 'down' : 'flat';
  return (
    <div className="metric-tile">
      <div className="metric-tile-label">{metric.label}</div>
      <div className="metric-tile-value">{val}</div>
      {chg != null && metric.change != null && (
        <div className={`metric-tile-change ${cls}`}>
          {chg > 0 ? '▲' : chg < 0 ? '▼' : '–'} {Math.abs(chg).toFixed(2)}%
        </div>
      )}
      {metric.period && (
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{metric.period}</div>
      )}
    </div>
  );
}
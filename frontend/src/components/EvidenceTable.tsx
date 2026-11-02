import type { EvidenceItem } from '../lib/types';
import { formatValue } from '../lib/format';

interface Props {
  items: EvidenceItem[];
}

export function EvidenceTable({ items }: Props) {
  if (!items.length) {
    return <p style={{ color: 'var(--muted)', fontSize: 13 }}>No evidence items.</p>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Metric</th>
            <th>Label</th>
            <th className="num">Value</th>
            <th className="num">vs Prior</th>
            <th className="num">Δ%</th>
            <th>Direction</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {items.map(item => {
            const dirClass =
              item.direction === 'increase' ? 'up' :
              item.direction === 'decrease' ? 'down' : 'flat';
            return (
              <tr key={item.id}>
                <td className="mono">{item.id}</td>
                <td className="mono">{item.metric}</td>
                <td>{item.label}</td>
                <td className="num">{formatValue(item.value, item.unit, item.currency)}</td>
                <td className="num">
                  {item.comparison_value != null
                    ? formatValue(item.comparison_value, item.unit, item.currency)
                    : '—'}
                </td>
                <td className={`num ${dirClass}`}>
                  {item.percentage_change != null
                    ? `${item.percentage_change > 0 ? '+' : ''}${item.percentage_change.toFixed(2)}%`
                    : '—'}
                </td>
                <td>
                  <span className={`badge ${
                    item.direction === 'increase' ? 'badge-green' :
                    item.direction === 'decrease' ? 'badge-red' : 'badge-grey'
                  }`}>{item.direction}</span>
                </td>
                <td className="mono">{item.source_dataset}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
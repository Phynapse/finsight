/** Format a financial value with its unit. */
export function formatValue(
  value: number,
  unit: string,
  currency: string | null,
): string {
  if (unit === 'percent') return `${value.toFixed(2)}%`;
  if (unit === 'count') return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (unit === 'ratio') return value.toFixed(4);
  // currency
  const sym = currency ?? 'USD';
  return `${sym} ${value.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Format a signed change with a + or – prefix. */
export function formatChange(change: number): string {
  const abs = Math.abs(change).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return change >= 0 ? `+${abs}` : `–${abs}`;
}

/** Return a CSS colour token for a directional change. */
export function directionClass(direction: string): string {
  if (direction === 'increase') return 'text-emerald-600';
  if (direction === 'decrease') return 'text-rose-600';
  return 'text-slate-500';
}

/** Short label for an analysis type id. */
export function analysisTypeLabel(id: string): string {
  const map: Record<string, string> = {
    metric_snapshot: 'Metric Snapshot',
    revenue_performance: 'Revenue Performance',
    expense_analysis: 'Expense Analysis',
    expense_variance: 'Expense Variance',
    profitability: 'Profitability',
    budget_variance: 'Budget Variance',
    vendor_spend: 'Vendor Spend',
    trend: 'Trend',
  };
  return map[id] ?? id;
}
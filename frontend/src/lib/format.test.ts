import { describe, it, expect } from 'vitest';
import { formatValue, formatChange, directionClass, analysisTypeLabel } from '../lib/format';

describe('formatValue', () => {
  it('formats currency with symbol', () => {
    expect(formatValue(1234567.89, 'currency', 'USD')).toBe('USD 1,234,567.89');
  });
  it('formats percentage', () => {
    expect(formatValue(17.13, 'percent', null)).toBe('17.13%');
  });
  it('formats count without decimals', () => {
    expect(formatValue(233, 'count', null)).toBe('233');
  });
  it('falls back to USD when currency is null', () => {
    expect(formatValue(100, 'currency', null)).toBe('USD 100.00');
  });
});

describe('formatChange', () => {
  it('prefixes positive change with +', () => {
    expect(formatChange(1100000)).toContain('+');
  });
  it('prefixes negative change with –', () => {
    expect(formatChange(-102700)).toContain('–');
  });
});

describe('directionClass', () => {
  it('returns green class for increase', () => {
    expect(directionClass('increase')).toBe('text-emerald-600');
  });
  it('returns red class for decrease', () => {
    expect(directionClass('decrease')).toBe('text-rose-600');
  });
  it('returns neutral class for flat', () => {
    expect(directionClass('flat')).toBe('text-slate-500');
  });
});

describe('analysisTypeLabel', () => {
  it('maps known ids to readable labels', () => {
    expect(analysisTypeLabel('profitability')).toBe('Profitability');
    expect(analysisTypeLabel('expense_variance')).toBe('Expense Variance');
    expect(analysisTypeLabel('trend')).toBe('Trend');
  });
  it('returns the id as-is for unknown types', () => {
    expect(analysisTypeLabel('unknown_type')).toBe('unknown_type');
  });
});
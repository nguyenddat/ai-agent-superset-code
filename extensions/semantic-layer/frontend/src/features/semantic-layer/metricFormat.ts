import { format } from 'd3-format';

const integerFormat = format(',d');
const decimalFormat = format(',.2~f');

/**
 * Formats a metric value with the metric's Superset d3 format. Superset-only names such as SMART_NUMBER, or no format,
 * fall back to grouped digits with at most two decimals.
 */
export function formatMetricValue(value: unknown, d3Format: string | null): string {
  if (value === null || value === undefined || value === '') return '—';
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (d3Format) {
    try {
      return format(d3Format)(number);
    } catch {
      // Not a d3 specifier; use the fallback below.
    }
  }
  return Number.isInteger(number) ? integerFormat(number) : decimalFormat(number);
}

const NUMERIC_TYPE = /INT|FLOAT|DOUBLE|NUMERIC|DECIMAL|REAL|SERIAL|NUMBER/i;

export function isNumericColumnType(columnType: string | null): boolean {
  return NUMERIC_TYPE.test(columnType ?? '');
}

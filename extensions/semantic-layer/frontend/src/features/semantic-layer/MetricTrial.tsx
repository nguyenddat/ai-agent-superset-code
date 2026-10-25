import React, { useState } from 'react';
import { AlertCircle, LoaderCircle, Play, Plus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import { formatMetricValue, isNumericColumnType } from './metricFormat';
import type {
  MetricContractExecution, MetricFilterOperator, MetricQueryColumn, MetricQueryDataset, MetricQueryFilter,
  MetricReviewItem,
} from './types';

type FilterDraft = { key: number; column: string; operator: MetricFilterOperator; value: string };

const OPERATORS: Array<{ value: MetricFilterOperator; label: string }> = [
  { value: '==', label: '=' },
  { value: '!=', label: '≠' },
  { value: '>', label: '>' },
  { value: '>=', label: '≥' },
  { value: '<', label: '<' },
  { value: '<=', label: '≤' },
  { value: 'IN', label: 'thuộc' },
  { value: 'NOT IN', label: 'không thuộc' },
];

const columnLabel = (column: Pick<MetricQueryColumn, 'column_name' | 'verbose_name'>) => (
  column.verbose_name || column.column_name
);
const isListOperator = (operator: MetricFilterOperator) => operator === 'IN' || operator === 'NOT IN';

/** Turns the typed filter rows into the execute payload, converting values for numeric columns. */
function buildFilters(drafts: FilterDraft[], columns: MetricQueryColumn[]): MetricQueryFilter[] {
  return drafts.map(draft => {
    const column = columns.find(item => item.column_name === draft.column);
    if (!column) throw new Error('Chọn cột cho mọi bộ lọc.');
    const numeric = isNumericColumnType(column.type);
    const convert = (text: string) => {
      if (!numeric) return text;
      const number = Number(text);
      if (!Number.isFinite(number)) throw new Error(`Giá trị lọc của cột ${columnLabel(column)} phải là số.`);
      return number;
    };
    if (isListOperator(draft.operator)) {
      const parts = draft.value.split(',').map(part => part.trim()).filter(Boolean);
      if (parts.length === 0) throw new Error(`Nhập ít nhất một giá trị cho cột ${columnLabel(column)}.`);
      return { column: column.column_name, operator: draft.operator, value: parts.map(convert) };
    }
    if (!draft.value.trim()) throw new Error(`Nhập giá trị lọc cho cột ${columnLabel(column)}.`);
    return { column: column.column_name, operator: draft.operator, value: convert(draft.value.trim()) };
  });
}

type MetricTrialProps = { metric: MetricReviewItem; dataset: MetricQueryDataset | undefined };

/** Runs an approved metric through Superset with chosen dimensions and filters, and shows the formatted result. */
export function MetricTrial({ metric, dataset }: MetricTrialProps) {
  const groupableColumns = dataset?.columns.filter(column => column.groupby) ?? [];
  const filterableColumns = dataset?.columns.filter(column => column.filterable) ?? [];
  const [dimensions, setDimensions] = useState<string[]>([]);
  const [filterDrafts, setFilterDrafts] = useState<FilterDraft[]>([]);
  const [nextFilterKey, setNextFilterKey] = useState(1);
  const [result, setResult] = useState<MetricContractExecution | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState('');

  const toggleDimension = (columnName: string, checked: boolean) => {
    setDimensions(current => checked ? [...current, columnName] : current.filter(name => name !== columnName));
  };
  const addFilter = () => {
    const firstColumn = filterableColumns[0]?.column_name ?? '';
    setFilterDrafts(current => [...current, { key: nextFilterKey, column: firstColumn, operator: '==', value: '' }]);
    setNextFilterKey(key => key + 1);
  };
  const updateFilter = (key: number, change: Partial<FilterDraft>) => {
    setFilterDrafts(current => current.map(draft => draft.key === key ? { ...draft, ...change } : draft));
  };
  const removeFilter = (key: number) => setFilterDrafts(current => current.filter(draft => draft.key !== key));

  const run = async () => {
    setRunError('');
    try {
      const filters = buildFilters(filterDrafts, filterableColumns);
      setRunning(true);
      const endpoint = semanticLayerApi.metricContractExecute(metric.dataset_id, metric.metric_id);
      setResult(await requestJson<MetricContractExecution>(endpoint, 'POST', { dimensions, filters }));
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : 'Không chạy được metric.');
    } finally {
      setRunning(false);
    }
  };

  const columnByName = new Map(dataset?.columns.map(column => [column.column_name, column]) ?? []);
  const filterColumnItems = filterableColumns.map(column => (
    { value: column.column_name, label: columnLabel(column) }
  ));
  const headerLabel = (columnName: string) => (columnName === metric.metric_name
    ? metric.verbose_name || metric.metric_name
    : columnLabel(columnByName.get(columnName) ?? { column_name: columnName, verbose_name: null }));
  const cellText = (columnName: string, value: unknown) => (columnName === metric.metric_name
    ? formatMetricValue(value, metric.d3format)
    : String(value ?? '—'));

  return (
    <section className="sl-metric-trial" aria-label="Chạy thử metric">
      <h4>Chạy thử</h4>
      <div className="sl-metric-trial-group">
        <span className="sl-metric-trial-label">Chiều phân tích</span>
        {groupableColumns.length === 0 ? <p className="sl-metric-muted">Dataset không có cột nào để group by.</p> : (
          <div className="sl-metric-dimensions">
            {groupableColumns.map(column => (
              <label key={column.column_name} className="sl-metric-dimension">
                <Checkbox
                  checked={dimensions.includes(column.column_name)}
                  onCheckedChange={checked => toggleDimension(column.column_name, checked === true)}
                />
                {columnLabel(column)}
              </label>
            ))}
          </div>
        )}
      </div>
      <div className="sl-metric-trial-group">
        <span className="sl-metric-trial-label">Bộ lọc</span>
        {filterDrafts.map(draft => (
          <div key={draft.key} className="sl-metric-filter">
            <Select
              items={filterColumnItems}
              value={draft.column}
              onValueChange={value => updateFilter(draft.key, { column: String(value) })}
            >
              <SelectTrigger aria-label="Cột lọc" className="min-w-0"><SelectValue /></SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {filterColumnItems.map(item => (
                    <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              items={OPERATORS}
              value={draft.operator}
              onValueChange={value => updateFilter(draft.key, { operator: value as MetricFilterOperator })}
            >
              <SelectTrigger aria-label="Phép so sánh"><SelectValue /></SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {OPERATORS.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Input
              aria-label="Giá trị lọc"
              value={draft.value}
              placeholder={isListOperator(draft.operator) ? 'Giá trị 1, giá trị 2' : 'Giá trị'}
              onChange={event => updateFilter(draft.key, { value: event.target.value })}
            />
            <Button variant="ghost" size="icon" aria-label="Xoá bộ lọc" onClick={() => removeFilter(draft.key)}>
              <X />
            </Button>
          </div>
        ))}
        {filterableColumns.length === 0 ? <p className="sl-metric-muted">Dataset không có cột nào cho phép lọc.</p> : (
          <Button variant="outline" size="sm" className="self-start" onClick={addFilter}>
            <Plus data-icon="inline-start" /> Thêm bộ lọc
          </Button>
        )}
      </div>
      <Button className="self-start" disabled={running} onClick={() => void run()}>
        {running ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : <Play data-icon="inline-start" />}
        Chạy thử
      </Button>
      {runError ? <div className="sl-metric-error" role="alert"><AlertCircle /> {runError}</div> : null}
      {result ? (
        <div className="sl-metric-result" aria-live="polite">
          <span className="sl-metric-muted">
            {result.row_count} dòng{result.truncated ? ' (đã cắt bớt theo giới hạn số dòng)' : ''}
          </span>
          <div className="sl-metric-result-table">
            <table>
              <thead>
                <tr>
                  {result.columns.map(columnName => <th key={columnName} scope="col">{headerLabel(columnName)}</th>)}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {result.columns.map(columnName => (
                      <td key={columnName} className={columnName === metric.metric_name ? 'is-metric' : undefined}>
                        {cellText(columnName, row[columnName])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </section>
  );
}

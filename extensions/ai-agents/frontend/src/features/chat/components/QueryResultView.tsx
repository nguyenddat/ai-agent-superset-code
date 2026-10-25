import React, { useEffect, useRef, useState } from 'react';
import { BarChart3, ChevronRight, Code2, Table2 } from 'lucide-react';
import { FilterSource, QueryResult, ResultCell, ResultFilter } from '../../../shared/api/chat';

const SOURCE_LABELS: Record<FilterSource, string> = {
  expert_rule: 'Định nghĩa chung',
  user_definition: 'Cách hiểu của bạn',
  time: 'Thời gian',
  place: 'Địa điểm',
  question: 'Theo câu hỏi',
};
const OPERATOR_LABELS: Record<ResultFilter['operator'], string> = {
  '==': '=', '!=': '≠', '<': '<', '<=': '≤', '>': '>', '>=': '≥', IN: 'thuộc', 'NOT IN': 'không thuộc',
};
const CHART_HEIGHT = 200;
const MARGIN = { top: 22, right: 48, bottom: 28, left: 44 };
const MAX_BAR_WIDTH = 24;

const numberFormat = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 2 });
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

function shownCell(value: ResultCell, short = false): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') return numberFormat.format(value);
  const date = ISO_DATE.exec(value);
  if (date) return short ? `${date[3]}/${date[2]}` : `${date[3]}/${date[2]}/${date[1]}`;
  return value;
}

function withUnit(value: ResultCell, unit: string | null): string {
  return unit && typeof value === 'number' ? `${shownCell(value)} ${unit}` : shownCell(value);
}

function filterText(filter: ResultFilter): string {
  const value = Array.isArray(filter.shown_value)
    ? filter.shown_value.map(item => shownCell(item)).join(', ')
    : shownCell(filter.shown_value);
  // The chip already says "Thời gian" or "Địa điểm"; the column behind it means nothing to the reader.
  const subject = filter.source === 'time' || filter.source === 'place' ? '' : `${filter.label} `;
  const operator = filter.operator === '==' && subject === '' ? '' : `${OPERATOR_LABELS[filter.operator]} `;
  return `${subject}${operator}${value}`;
}

/** Round tick values covering [low, high], about four of them. */
function niceTicks(low: number, high: number): number[] {
  if (low === high) high = low + 1;
  const rough = (high - low) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map(factor => factor * magnitude).find(candidate => candidate >= rough) ?? rough;
  const ticks = [];
  for (let tick = Math.floor(low / step) * step; tick <= high + step * 0.001; tick += step) {
    ticks.push(Number(tick.toFixed(10)));
  }
  if (ticks[ticks.length - 1] < high) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

// Categorical colors go to series in this fixed order; a ninth series is never coloured, the table shows it instead.
const MAX_SERIES = 8;

type Series = { name: string; values: Array<number | null> };

function numericCell(value: ResultCell): number | null {
  return typeof value === 'number' ? value : null;
}

/**
 * A metric over time: one line (or columns) for one series, a line per group otherwise, with a legend. The latest
 * value of each line is labelled; the rest are read from the axis or on hover.
 */
function TimeChart({ kind, title, unit, labels, series }: {
  kind: 'bar' | 'line'; title: string; unit: string | null; labels: string[]; series: Series[];
}) {
  const { ref, width } = useWidth(560);
  const [hovered, setHovered] = useState<number | null>(null);
  const values = series.flatMap(item => item.values).filter((value): value is number => value !== null);
  if (values.length === 0) return null;
  const columns = kind === 'bar' && series.length === 1;
  // Columns are read by their length, so they start at zero; a line is read by its course, so it fits the values.
  const ticks = columns
    ? niceTicks(Math.min(0, ...values), Math.max(0, ...values))
    : niceTicks(Math.min(...values), Math.max(...values));
  const low = ticks[0];
  const high = ticks[ticks.length - 1];
  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;
  const band = plotWidth / labels.length;
  const x = (index: number) => MARGIN.left + band * (index + 0.5);
  const y = (value: number) => MARGIN.top + plotHeight * (1 - (value - low) / (high - low));
  const labelEvery = Math.max(1, Math.ceil(labels.length / Math.floor(plotWidth / 48)));
  const barWidth = Math.min(MAX_BAR_WIDTH, band - 2);
  const linePath = (item: Series) => item.values
    .map((value, index) => (value === null ? null : `${x(index)},${y(value)}`))
    .filter(Boolean)
    .map((coordinates, index) => `${index === 0 ? 'M' : 'L'}${coordinates}`)
    .join(' ');
  const column = (value: number, index: number) => {
    const left = x(index) - barWidth / 2;
    const base = y(Math.max(low, 0));
    const end = y(value);
    const radius = Math.min(4, Math.abs(base - end), barWidth / 2);
    const turn = end <= base ? radius : -radius;
    return `M${left},${base} V${end + turn} Q${left},${end} ${left + radius},${end} `
      + `H${left + barWidth - radius} Q${left + barWidth},${end} ${left + barWidth},${end + turn} V${base} Z`;
  };
  const lastIndex = (item: Series) => item.values.reduce<number>(
    (last, value, index) => (value === null ? last : index), -1,
  );
  const onMove = (event: React.MouseEvent<SVGRectElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const index = Math.floor(((event.clientX - bounds.left) / bounds.width) * labels.length);
    setHovered(Math.min(labels.length - 1, Math.max(0, index)));
  };
  const hoveredValues = hovered === null ? [] : series
    .map((item, order) => ({ item, order, value: item.values[hovered] }))
    .filter(entry => entry.value !== null);

  return (
    <figure className="ai-result-chart" ref={ref}>
      <figcaption>{title}{unit ? ` (${unit})` : ''}</figcaption>
      {series.length > 1 && (
        <ul className="ai-result-legend">
          {series.map((item, order) => (
            <li key={item.name}>
              <span className={`ai-result-key is-series-${order + 1}`} aria-hidden="true" />{item.name}
            </li>
          ))}
        </ul>
      )}
      <svg width={width} height={CHART_HEIGHT} role="img" aria-label={`${title}, ${labels.length} mốc`}>
        {ticks.map(tick => (
          <g key={tick} className="ai-result-grid">
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} />
            <text x={MARGIN.left - 6} y={y(tick)} dy="0.32em" textAnchor="end">{numberFormat.format(tick)}</text>
          </g>
        ))}
        {labels.map((label, index) => (index % labelEvery === 0 ? (
          <text key={label} className="ai-result-axis" x={x(index)} y={CHART_HEIGHT - 8} textAnchor="middle">
            {shownCell(label, true)}
          </text>
        ) : null))}
        {columns && series[0].values.map((value, index) => (value === null ? null : (
          <path
            key={labels[index]}
            className={`ai-result-bar${hovered !== null && hovered !== index ? ' is-dimmed' : ''}`}
            d={column(value, index)}
          />
        )))}
        {!columns && hovered !== null && (
          <line className="ai-result-crosshair" x1={x(hovered)} x2={x(hovered)} y1={MARGIN.top} y2={y(low)} />
        )}
        {!columns && series.map((item, order) => (
          <path key={item.name} className={`ai-result-line is-series-${order + 1}`} d={linePath(item)} />
        ))}
        {!columns && series.map((item, order) => {
          const index = hovered ?? lastIndex(item);
          const value = index >= 0 ? item.values[index] : null;
          return value === null || value === undefined ? null : (
            <circle
              key={item.name} className={`ai-result-dot is-series-${order + 1}`} cx={x(index)} cy={y(value)} r={4}
            />
          );
        })}
        {!columns && hovered === null && series.length <= 4 && series.map(item => {
          const index = lastIndex(item);
          const value = index >= 0 ? item.values[index] : null;
          return value === null ? null : (
            <text key={item.name} className="ai-result-value" x={x(index) + 8} y={y(value)} dy="0.32em">
              {numberFormat.format(value)}
            </text>
          );
        })}
        <rect
          className="ai-result-hit"
          x={MARGIN.left}
          y={MARGIN.top}
          width={plotWidth}
          height={plotHeight}
          onMouseMove={onMove}
          onMouseLeave={() => setHovered(null)}
        />
      </svg>
      {hovered !== null && hoveredValues.length > 0 && (
        <div
          className="ai-result-tooltip"
          style={{ left: Math.min(Math.max(x(hovered), 90), width - 90), top: MARGIN.top }}
        >
          <span>{shownCell(labels[hovered])}</span>
          {hoveredValues.map(entry => (
            <span key={entry.item.name} className="ai-result-tooltip-row">
              {series.length > 1 && <i className={`ai-result-key is-series-${entry.order + 1}`} aria-hidden="true" />}
              {series.length > 1 ? `${entry.item.name}: ` : ''}<strong>{withUnit(entry.value, unit)}</strong>
            </span>
          ))}
        </div>
      )}
    </figure>
  );
}

/** A metric compared across groups: horizontal bars, longest first, each labelled at its tip. */
function RankedBars({ title, unit, items }: {
  title: string; unit: string | null; items: Array<{ label: string; value: number | null }>;
}) {
  const ranked = items
    .filter((item): item is { label: string; value: number } => item.value !== null)
    .sort((left, right) => right.value - left.value);
  if (ranked.length === 0) return null;
  const largest = Math.max(...ranked.map(item => Math.abs(item.value))) || 1;
  return (
    <figure className="ai-result-chart">
      <figcaption>{title}{unit ? ` (${unit})` : ''}</figcaption>
      <ol className="ai-result-ranking">
        {ranked.map(item => (
          <li key={item.label} title={`${item.label}: ${withUnit(item.value, unit)}`}>
            <span className="ai-result-ranking-label">{item.label}</span>
            <span className="ai-result-ranking-track">
              <span className="ai-result-ranking-bar" style={{ width: `${(Math.abs(item.value) / largest) * 100}%` }} />
              <span className="ai-result-ranking-value">{numberFormat.format(item.value)}</span>
            </span>
          </li>
        ))}
      </ol>
    </figure>
  );
}


/** The queries behind the result, folded away until asked for: the SQL when shown, otherwise the governed request. */
function ResultQueries({ queries }: { queries: NonNullable<QueryResult['queries']> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="ai-result-queries">
      <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <Code2 aria-hidden="true" /> Xem truy vấn
        <ChevronRight className="ai-result-queries-chevron" aria-hidden="true" />
      </button>
      {open && queries.map(query => (
        <div key={query.metric_id} className="ai-result-query">
          <p>
            {query.metric} · dataset {query.dataset_id}, metric {query.metric_id}
            {query.sql ? '' : ' · yêu cầu gửi Semantic Layer'}
          </p>
          <pre>{query.sql ?? JSON.stringify(query.request, null, 2)}</pre>
        </div>
      ))}
    </div>
  );
}

function ResultTable({ result }: { result: QueryResult }) {
  return (
    <div className="ai-result-table-wrap">
      <table className="ai-result-table">
        <thead>
          <tr>
            {result.dimensions.map(dimension => <th key={dimension.name}>{dimension.label}</th>)}
            {result.metrics.map(metric => (
              <th key={metric.name} className="is-number">{metric.label}{metric.unit ? ` (${metric.unit})` : ''}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map(row => (
            <tr key={result.dimensions.map(dimension => String(row[dimension.name])).join('|') || 'total'}>
              {result.dimensions.map(dimension => <td key={dimension.name}>{shownCell(row[dimension.name])}</td>)}
              {result.metrics.map(metric => (
                <td key={metric.name} className="is-number">{shownCell(row[metric.name])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type ChartPlan =
  | { kind: 'time'; form: 'bar' | 'line'; time: string; group: string | null; labels: string[]; groups: string[] }
  | { kind: 'ranking'; group: string };

/**
 * How the rows can be drawn: over time when a dimension is a date (a line per group when there is a second one, up to
 * eight groups), as ranked bars when the only dimension is a group; anything else stays a table.
 */
function chartPlan(result: QueryResult): ChartPlan | null {
  if (result.rows.length < 2) return null;
  const time = result.dimensions.find(dimension => dimension.temporal);
  const others = result.dimensions.filter(dimension => dimension !== time);
  const distinct = (name: string) => Array.from(new Set(result.rows.map(row => String(row[name]))));
  if (time && others.length <= 1) {
    const group = others[0]?.name ?? null;
    const groups = group ? distinct(group).sort((left, right) => left.localeCompare(right, 'vi')) : [];
    if (groups.length > MAX_SERIES) return null;
    const form = result.presentation === 'bar' && !group ? 'bar' : 'line';
    return { kind: 'time', form, time: time.name, group, labels: distinct(time.name).sort(), groups };
  }
  if (!time && others.length === 1) return { kind: 'ranking', group: others[0].name };
  return null;
}

function MetricChart({ plan, result, metric }: {
  plan: ChartPlan; result: QueryResult; metric: QueryResult['metrics'][number];
}) {
  if (plan.kind === 'ranking') {
    const items = result.rows.map(row => ({ label: shownCell(row[plan.group]), value: numericCell(row[metric.name]) }));
    return <RankedBars title={metric.label} unit={metric.unit} items={items} />;
  }
  const valueAt = new Map(result.rows.map(row => [
    `${plan.group ? String(row[plan.group]) : ''}|${String(row[plan.time])}`, numericCell(row[metric.name]),
  ]));
  const series = (plan.group ? plan.groups : ['']).map(name => ({
    name: name || metric.label,
    values: plan.labels.map(label => valueAt.get(`${name}|${label}`) ?? null),
  }));
  return <TimeChart kind={plan.form} title={metric.label} unit={metric.unit} labels={plan.labels} series={series} />;
}

/** The data behind an answer: the conditions it used, then a number, a chart or a table of the metrics' rows. */
export function QueryResultView({ result }: { result: QueryResult }) {
  const [view, setView] = useState<'chart' | 'table'>('chart');
  const single = result.dimensions.length === 0 && result.rows.length <= 1;
  const plan = chartPlan(result);
  const showChart = plan !== null && view === 'chart';

  return (
    <section className="ai-result" aria-label="Số liệu truy vấn">
      <header className="ai-result-header">
        <div className="ai-result-heading">
          <strong>{result.scope || 'Số liệu'}</strong>
          <span>
            {result.row_count === 0 ? 'Không có dòng nào thoả điều kiện' : `${result.row_count} dòng`}
            {result.truncated ? ' · đã rút gọn' : ''}
          </span>
        </div>
        {plan && (
          <div className="ai-result-views" role="group" aria-label="Cách hiển thị">
            <button type="button" aria-pressed={view === 'chart'} onClick={() => setView('chart')}>
              <BarChart3 aria-hidden="true" /> Biểu đồ
            </button>
            <button type="button" aria-pressed={view === 'table'} onClick={() => setView('table')}>
              <Table2 aria-hidden="true" /> Bảng
            </button>
          </div>
        )}
      </header>
      {result.filters.length > 0 && (
        <ul className="ai-result-filters" aria-label="Điều kiện đã dùng">
          {result.filters.map(filter => (
            <li key={`${filter.column}${filter.operator}${String(filter.value)}`} className={`is-${filter.source}`}>
              <span className="ai-result-filter-source">{SOURCE_LABELS[filter.source]}</span>
              {filterText(filter)}
            </li>
          ))}
        </ul>
      )}
      {single && result.rows.length === 1 && (
        <div className="ai-result-tiles">
          {result.metrics.map(metric => (
            <div key={metric.name} className="ai-result-tile">
              <span>{metric.label}</span>
              <strong>{shownCell(result.rows[0][metric.name])}{metric.unit && <small> {metric.unit}</small>}</strong>
            </div>
          ))}
        </div>
      )}
      {showChart && result.metrics.map(metric => (
        <MetricChart key={metric.name} plan={plan} result={result} metric={metric} />
      ))}
      {!single && !showChart && result.rows.length > 0 && <ResultTable result={result} />}
      {result.notes.map(note => <p key={note} className="ai-result-note">{note}</p>)}
      {result.queries && result.queries.length > 0 && <ResultQueries queries={result.queries} />}
    </section>
  );
}

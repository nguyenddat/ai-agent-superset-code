import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, Circle, Play, X } from 'lucide-react';
import type { AnalysisTrace as Trace, GraphView, StageStatus } from '../../shared/api/schemaLink';
import { GraphHighlight, SchemaGraphView } from './SchemaGraphView';

type StageName = keyof Trace['stages'];

const STAGES: Array<{ name: StageName; title: string; hint: string }> = [
  { name: 'goal', title: 'Mục tiêu', hint: 'Đo gì, chia theo gì, lọc theo gì' },
  { name: 'nodes', title: 'Node', hint: 'Các bảng truy vấn phải có, và bảng gốc' },
  { name: 'graph', title: 'Đồ thị', hint: 'Base table và quan hệ đã duyệt bạn được thấy' },
  { name: 'path', title: 'Đường được chọn', hint: 'Cây join nhỏ nhất nối mọi bảng cần thiết' },
];
const ALGORITHM_LABELS = {
  dijkstra: 'Dijkstra từ bảng gốc',
  steiner: 'Cây Steiner (Dreyfus–Wagner)',
  steiner_heuristic: 'Cây Steiner (Takahashi–Matsuyama)',
} as const;
const STEP_MS = 900;

function StatusIcon({ status }: { status: StageStatus }) {
  if (status === 'done') return <Check aria-label="Xong" />;
  if (status === 'failed') return <X aria-label="Dừng" />;
  return <Circle aria-label="Chưa chạy" />;
}

function tableName(view: GraphView, id: number | undefined) {
  return view.tables.find(table => table.dataset_id === id)?.table ?? String(id);
}

function shownValue(value: unknown) {
  return Array.isArray(value) ? value.join(', ') : String(value);
}

/** The highlight the graph shows for a stage: needed tables from Node on, the chosen path at the last stage. */
function highlightFor(trace: Trace, stage: StageName): GraphHighlight {
  const nodes = trace.stages.nodes;
  const path = trace.stages.path;
  if (stage === 'goal') return {};
  const needed = { root: nodes.root, terminals: nodes.terminals };
  if (stage !== 'path' || !path.steps) return { ...needed, missing: path.unreachable };
  return {
    ...needed,
    pathEdges: path.steps.filter(step => !step.fanout).map(step => step.edge),
    fanoutEdges: path.steps.filter(step => step.fanout).map(step => step.edge),
    pathTables: path.tables,
  };
}

export function AnalysisTrace({ trace, fallbackGraph }: { trace: Trace; fallbackGraph: GraphView }) {
  // Kept the same object between renders, so the graph is laid out again only when the trace or graph changes.
  const view = useMemo<GraphView>(() => {
    const { tables, edges, excluded } = trace.stages.graph;
    return tables ? { tables, edges: edges ?? [], excluded: excluded ?? [] } : fallbackGraph;
  }, [trace, fallbackGraph]);
  const lastReached = [...STAGES].reverse()
    .find(stage => trace.stages[stage.name].status !== 'pending')?.name ?? 'goal';
  const [selected, setSelected] = useState<StageName>(lastReached);
  const highlight = useMemo(() => highlightFor(trace, selected), [trace, selected]);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => setSelected(lastReached), [trace]);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const play = () => {
    const reached = STAGES.filter(stage => trace.stages[stage.name].status !== 'pending');
    setPlaying(true);
    reached.forEach((stage, index) => {
      timer.current = window.setTimeout(() => {
        setSelected(stage.name);
        if (index === reached.length - 1) setPlaying(false);
      }, index * STEP_MS);
    });
  };

  const { goal, nodes, path } = trace.stages;
  const ambiguousTables = Object.keys(path.alternatives ?? {}).map(id => tableName(view, Number(id)));
  const details: Record<StageName, React.ReactNode> = {
    goal: goal.error ? null : (
      <dl className="ai-trace-goal">
        {goal.measures?.length ? <dt>Đo</dt> : null}
        {goal.measures?.map(item => (
          <dd key={`${item.dataset_id}.${item.column}`}>
            <strong>{item.aggregation} {item.label}</strong>
            {item.indicator?.unit ? <span> · {item.indicator.unit}</span> : null}
            <code>{item.table}.{item.column ?? '*'}</code><em>{item.source}</em>
          </dd>
        ))}
        {goal.group_by?.length ? <dt>Chia theo</dt> : null}
        {goal.group_by?.map(item => (
          <dd key={`${item.dataset_id}.${item.column}`}>
            <strong>{item.label}{item.time_grain ? ` (${item.time_grain})` : ''}</strong>
            <code>{item.table}.{item.column}</code>
          </dd>
        ))}
        {goal.filters?.length ? <dt>Lọc</dt> : null}
        {goal.filters?.map(item => (
          <dd key={`${item.dataset_id}.${item.column}.${item.operator}.${shownValue(item.value)}`}>
            <strong>{item.label}</strong>
            <code>{item.table}.{item.column} {item.operator} {shownValue(item.value)}</code><em>{item.source}</em>
          </dd>
        ))}
        {goal.row_kinds?.length ? <dt>Loại dòng</dt> : null}
        {goal.row_kinds?.map(item => (
          <dd key={`${item.dataset_id}.${item.value}`}>
            <strong>{item.label}</strong>
            <code>{item.table}.{item.column} = {item.value}</code><em>grain {item.grain}</em>
          </dd>
        ))}
      </dl>
    ),
    nodes: nodes.terminals ? (
      <ul className="ai-trace-nodes">
        {nodes.terminals.map(table => (
          <li key={table} className={table === nodes.root ? 'is-root' : undefined}>
            <code>{tableName(view, table)}</code>
            {table === nodes.root ? <span className="ai-trace-badge">bảng gốc</span> : null}
            <span>{(nodes.reasons?.[String(table)] ?? []).join(' · ')}</span>
          </li>
        ))}
      </ul>
    ) : null,
    graph: trace.stages.graph.tables ? (
      <p className="ai-trace-note">
        {view.tables.length} base table, {view.edges.length} quan hệ đã duyệt.
        {view.excluded.length ? ` Bỏ qua vì có luật RLS: ${view.excluded.map(item => item.table).join(', ')}.` : ''}
      </p>
    ) : null,
    path: path.steps ? (
      <div className="ai-trace-path">
        <p className="ai-trace-note">
          {path.algorithm ? ALGORITHM_LABELS[path.algorithm] : ''} · chi phí {path.cost} · {path.steps.length} phép join
          {path.fanout ? ' · có nhân dòng' : ''}
        </p>
        <ol>
          {path.steps.map(step => (
            <li key={step.edge} className={step.fanout ? 'is-fanout' : undefined}>
              <code>{step.on}</code>
              <span>
                {step.forward ? 'nhiều → một' : 'ngược chiều'} · chi phí {step.cost}{step.fanout ? ' · nhân dòng' : ''}
              </span>
            </li>
          ))}
        </ol>
        {ambiguousTables.length ? (
          <p className="ai-trace-warning">
            <AlertTriangle /> Có đường khác cùng chi phí tới {ambiguousTables.join(', ')};
            schema link sẽ hỏi lại người dùng khi không chọn được theo cột.
          </p>
        ) : null}
        {path.problems?.map(problem => (
          <p key={problem.message} className="ai-trace-warning"><AlertTriangle /> {problem.message}</p>
        ))}
      </div>
    ) : null,
  };

  return (
    <section className="ai-trace" aria-label="Quá trình phân tích">
      <div className="ai-trace-stages">
        <div className="ai-trace-head">
          <span className={`ai-trace-status is-${trace.status === 'ok' ? 'ok' : 'stopped'}`}>
            {trace.status === 'ok' ? 'Dựng được truy vấn' : `Dừng: ${trace.message}`}
          </span>
          <button type="button" className="ai-trace-play" disabled={playing} onClick={play}>
            <Play aria-hidden="true" /> Phát lại
          </button>
        </div>
        <ol>
          {STAGES.map((stage, index) => {
            const result = trace.stages[stage.name];
            return (
              <li
                key={stage.name}
                className={`ai-trace-stage is-${result.status}${selected === stage.name ? ' is-selected' : ''}`}
              >
                <button type="button" onClick={() => setSelected(stage.name)} aria-pressed={selected === stage.name}>
                  <span className="ai-trace-stage-icon"><StatusIcon status={result.status} /></span>
                  <span className="ai-trace-stage-title">{index + 1}. {stage.title}</span>
                  <span className="ai-trace-stage-ms">{result.ms !== null ? `${result.ms} ms` : ''}</span>
                </button>
                <p className="ai-trace-stage-hint">{stage.hint}</p>
                {result.error ? <p className="ai-trace-error">{result.error}</p> : null}
                {selected === stage.name ? details[stage.name] : null}
              </li>
            );
          })}
        </ol>
      </div>
      <div className="ai-trace-canvas">
        <SchemaGraphView
          view={view}
          highlight={highlight}
          caption={STAGES.find(stage => stage.name === selected)?.title
            + (trace.stages.nodes.root !== undefined ? ` · bảng gốc ${tableName(view, trace.stages.nodes.root)}` : '')}
        />
        {trace.sql ? (
          <details className="ai-trace-sql" open={selected === 'path'}>
            <summary>SQL đã dựng</summary>
            <pre>{trace.sql}</pre>
          </details>
        ) : null}
      </div>
    </section>
  );
}

import React, { useMemo } from 'react';
import type { GraphEdge, GraphView } from '../../shared/api/schemaLink';

/** What the graph shows on top of the plain schema: needed tables, the root, and the chosen join path. */
export type GraphHighlight = {
  root?: number;
  terminals?: number[];
  pathEdges?: number[];
  fanoutEdges?: number[];
  /** Tables joined by the path; the others fade when a path is shown. */
  pathTables?: number[];
  missing?: number[];
};

const NODE_WIDTH = 204;
const NODE_HEIGHT = 54;
const COLUMN_GAP = 64;
const ROW_GAP = 22;
const PADDING = 16;
// Edges skipping a column run in lanes above the tables, so none passes behind a table it does not join.
const LANE_GAP = 10;

const clipped = (value: string, length: number) => (value.length > length ? `${value.slice(0, length - 1)}…` : value);

/**
 * Columns by how far a table's keys point: a table no relationship leaves sits on the right, a table pointing at it
 * one column left, and so on, so joins read left to right the way the path walks them.
 */
function layout(view: GraphView) {
  const pointsTo = new Map<number, number[]>();
  for (const edge of view.edges) pointsTo.set(edge.from, [...(pointsTo.get(edge.from) ?? []), edge.to]);
  const rank = new Map<number, number>();
  const rankOf = (table: number, seen: Set<number>): number => {
    if (rank.has(table)) return rank.get(table)!;
    if (seen.has(table)) return 0;
    seen.add(table);
    const value = Math.max(-1, ...(pointsTo.get(table) ?? []).map(target => rankOf(target, seen))) + 1;
    rank.set(table, value);
    return value;
  };
  view.tables.forEach(table => rankOf(table.dataset_id, new Set()));
  const deepest = Math.max(0, ...rank.values());
  const columns = new Map<number, number[]>();
  for (const table of view.tables) {
    const column = deepest - (rank.get(table.dataset_id) ?? 0);
    columns.set(column, [...(columns.get(column) ?? []), table.dataset_id]);
  }
  const columnOf = (table: number) => deepest - (rank.get(table) ?? 0);
  const longEdges = view.edges.filter(edge => Math.abs(columnOf(edge.to) - columnOf(edge.from)) > 1);
  const lanes = new Map(longEdges.map((edge, index) => [edge.id, PADDING + index * LANE_GAP]));
  const top = PADDING + (longEdges.length ? longEdges.length * LANE_GAP + 8 : 0);
  const position = new Map<number, { x: number; y: number }>();
  let height = 0;
  for (const [column, tables] of columns) {
    tables.sort((left, right) => {
      const leftTable = view.tables.find(item => item.dataset_id === left)!;
      const rightTable = view.tables.find(item => item.dataset_id === right)!;
      return (leftTable.layer?.level ?? 9) - (rightTable.layer?.level ?? 9) || leftTable.table.localeCompare(rightTable.table);
    });
    tables.forEach((table, index) => {
      position.set(table, { x: PADDING + column * (NODE_WIDTH + COLUMN_GAP), y: top + index * (NODE_HEIGHT + ROW_GAP) });
    });
    height = Math.max(height, top + PADDING + tables.length * (NODE_HEIGHT + ROW_GAP) - ROW_GAP);
  }
  const width = PADDING * 2 + (deepest + 1) * (NODE_WIDTH + COLUMN_GAP) - COLUMN_GAP;
  return { position, width, height, lanes };
}

function edgePath(start: { x: number; y: number }, end: { x: number; y: number }, lane: number | undefined): string {
  const from = { x: start.x + NODE_WIDTH, y: start.y + NODE_HEIGHT / 2 };
  const to = { x: end.x, y: end.y + NODE_HEIGHT / 2 };
  if (to.x <= from.x) {
    // Tables in one column: a loop out to the right and back.
    const bend = from.x + 36;
    return `M${from.x},${from.y} C${bend},${from.y} ${bend},${to.y} ${end.x + NODE_WIDTH},${to.y}`;
  }
  if (lane !== undefined) {
    // Up into its lane over the columns in between, along it, and down into the target.
    const bend = COLUMN_GAP / 2;
    return `M${from.x},${from.y} C${from.x + bend},${from.y} ${from.x + bend},${lane} ${from.x + COLUMN_GAP},${lane} `
      + `L${to.x - COLUMN_GAP},${lane} C${to.x - bend},${lane} ${to.x - bend},${to.y} ${to.x},${to.y}`;
  }
  const middle = (from.x + to.x) / 2;
  return `M${from.x},${from.y} C${middle},${from.y} ${middle},${to.y} ${to.x},${to.y}`;
}

export function SchemaGraphView({ view, highlight = {}, caption }: { view: GraphView; highlight?: GraphHighlight; caption?: string }) {
  const { position, width, height, lanes } = useMemo(() => layout(view), [view]);
  const terminals = new Set(highlight.terminals ?? []);
  const pathEdges = new Set(highlight.pathEdges ?? []);
  const fanoutEdges = new Set(highlight.fanoutEdges ?? []);
  const pathTables = new Set(highlight.pathTables ?? []);
  const missing = new Set(highlight.missing ?? []);
  const showingPath = pathEdges.size > 0 || pathTables.size > 0;
  const focused = (table: number) => (showingPath ? pathTables.has(table) : terminals.size === 0 || terminals.has(table));

  const edgeClass = (edge: GraphEdge) => {
    if (fanoutEdges.has(edge.id)) return 'is-fanout';
    if (pathEdges.has(edge.id)) return 'is-path';
    return focused(edge.from) && focused(edge.to) && !showingPath ? '' : 'is-faded';
  };

  return (
    <figure className="ai-schema-graph">
      {caption ? <figcaption>{caption}</figcaption> : null}
      <div className="ai-schema-graph-scroll">
        <svg width={width} height={height} role="img" aria-label={`Đồ thị ${view.tables.length} bảng, ${view.edges.length} quan hệ`}>
          <defs>
            <marker id="ai-schema-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" className="ai-schema-arrowhead" />
            </marker>
          </defs>
          {view.edges.map(edge => {
            const start = position.get(edge.from);
            const end = position.get(edge.to);
            if (!start || !end) return null;
            return (
              <path
                key={edge.id}
                className={`ai-schema-edge ${edgeClass(edge)}`}
                d={edgePath(start, end, lanes.get(edge.id))}
                markerEnd="url(#ai-schema-arrow)"
              >
                <title>{`${edge.from_column} → ${edge.to_column} (${edge.cardinality === 'one_to_one' ? '1 : 1' : 'n : 1'})`}</title>
              </path>
            );
          })}
          {view.tables.map(table => {
            const point = position.get(table.dataset_id)!;
            const classes = [
              'ai-schema-node',
              highlight.root === table.dataset_id ? 'is-root' : '',
              terminals.has(table.dataset_id) ? 'is-terminal' : '',
              missing.has(table.dataset_id) ? 'is-missing' : '',
              focused(table.dataset_id) ? '' : 'is-faded',
            ].filter(Boolean).join(' ');
            return (
              <g key={table.dataset_id} className={classes} transform={`translate(${point.x},${point.y})`}>
                <title>{table.table}</title>
                <rect width={NODE_WIDTH} height={NODE_HEIGHT} rx={8} />
                <text x={12} y={21} className="ai-schema-node-label">{clipped(table.label ?? table.table, 27)}</text>
                <text x={12} y={40} className="ai-schema-node-table">{clipped(table.table, 22)}</text>
                <text x={NODE_WIDTH - 10} y={40} textAnchor="end" className={highlight.root === table.dataset_id ? 'ai-schema-node-badge' : 'ai-schema-node-layer'}>
                  {highlight.root === table.dataset_id ? 'bảng gốc' : table.layer?.name ?? ''}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </figure>
  );
}

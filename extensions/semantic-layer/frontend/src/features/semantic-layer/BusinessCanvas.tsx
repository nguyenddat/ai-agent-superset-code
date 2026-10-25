import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  ConnectionMode,
  Controls,
  Edge,
  EdgeLabelRenderer,
  EdgeProps,
  EdgeTypes,
  Handle,
  MarkerType,
  Node,
  NodeChange,
  NodeProps,
  NodeToolbar,
  NodeTypes,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  useStore,
} from '@xyflow/react';
import { ChevronDown, ChevronLeft, ChevronRight, GitBranch, GripHorizontal, Layers3, LoaderCircle, Network, Pencil, Plus, RotateCcw, Sigma, Table2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { requestJson, semanticLayerApi } from './api';
import { getDatasetName, groupDatasetsByLayer } from './datasets';
import { DOMAIN_COLORS, DomainDialog } from './DomainDialog';
import {
  DEFAULT_GEOMETRY,
  EDGE_STYLES,
  coordsFromRoute,
  edgePath,
  edgePoints,
  effectiveCoords,
  fromStoredLineage,
  midpoint,
  snapPoint,
  toStoredLineage,
  withStyle,
} from './edgeGeometry';
import type { EdgeGeometry, EdgeStyle, LineageLayout } from './edgeGeometry';
import {
  CARD_BORDER,
  CARD_HEADER,
  CARD_WIDTH,
  DETAIL_LEVELS,
  METRIC_HEIGHT,
  METRIC_WIDTH,
  cardHeight,
  handleId,
  METRIC_LEFT,
  metricColumn,
  metricSlots,
  metricSources,
  portY,
} from './lineageCard';
import type { CardColumn, CardContent, DetailLevel } from './lineageCard';
import { routeCrosses, routeOrthogonal } from './edgeRouter';
import type { Box, CardSide } from './edgeRouter';
import { LANE_HEADER, LANE_INSET, LEVEL_HEADER, layoutLineageWithElk } from './lineageElk';
import type { LineageLink } from './lineageElk';
import {
  GRID_CELL,
  UNASSIGNED_DOMAIN,
  cellKey,
  cellsConnected,
  datasetLaneKey,
  domainFrame,
  fromStoredCanvas,
  layoutDomainGroups,
  lineageLanes,
  UNCLASSIFIED_LANE,
  membershipChanges,
  reconcileGrid,
  selectLineageItems,
  stepCell,
  strayTables,
  tileCell,
  tilePosition,
  toStoredCanvas,
  validGrid,
} from './modelLayout';
import type { CanvasGrid, Cell, Direction, DomainGrid, MembershipChange, Point, Size } from './modelLayout';
import type { BusinessDomain, BusinessModel, DashboardDataset, DatasetDictionary, LineageEdge, ModelMetric, ThemeMode } from './types';

type ViewMode = 'business' | 'lineage';
/** Membership changes the canvas is waiting for the user to confirm, and the canvas to go back to otherwise. */
type PendingChanges = { changes: MembershipChange[]; before: CanvasGrid };

type DomainGroupData = {
  domain: BusinessDomain | null;
  count: number;
  selected: boolean;
  onToggle: (domainId: number) => void;
  onEdit: (domain: BusinessDomain) => void;
  gridKey: string;
  /** The domain's cells and its header cell, in canvas cells; `origin` is the top-left cell of the node. */
  cells: Cell[];
  header: Cell;
  origin: Cell;
  onGrow: (gridKey: string, cell: Cell, edge: Direction | null, event: React.PointerEvent) => void;
};
type TableData = {
  title: string;
  tableName: string;
  layerName: string | null;
  layerColor: string | null;
  sharedCount: number;
};
/** A lineage card: the table, its lane, the columns it lists (see lineageCard) and the dataset's metrics. */
type LineageCardData = TableData & {
  datasetId: number;
  lane: string;
  active: boolean;
  content: CardContent;
  metrics: ModelMetric[];
  /** Whether the metrics stand beside the card; set as the card is drawn. */
  metricsOpen?: boolean;
  onToggleMetrics?: (nodeId: string) => void;
};
/**
 * The arrow from a card to one of its metrics, in canvas coordinates: it leaves the card's right side (`start`) at
 * each of `sources`, runs down its own `lane` and enters the metric at `end`.
 */
type MetricArrowData = { start: number; sources: number[]; lane: number; end: Point; card: string };
/** A metric beside its card, and the shape of the arrow to it. */
type MetricData = { metric: ModelMetric; card: string; lane: string; dimmed?: boolean; arrow: Omit<MetricArrowData, 'card'> };
/** The metric being looked at, hovered itself or through one of its arrows: its card and the roles of its columns. */
type MetricFocus = { metricNodeId: string; card: string; roles: Map<string, 'measure' | 'filter'> };
const MetricFocusContext = createContext<{ focus: MetricFocus | null; hover: (metricNodeId: string | null) => void }>({
  focus: null,
  hover: () => undefined,
});
type LaneData = { key: string; level: number; label: string; hint: string; color: string | null };
type LevelData = { label: string; count: number; level: number };

const UNASSIGNED_COLOR = '#8c8c8c';
const METRIC_EDGE_COLOR = '#8b5cf6';

const CELL_SIDES: Array<[Direction, string]> = [['up', 't'], ['right', 'r'], ['down', 'b'], ['left', 'l']];

/**
 * A business domain drawn as its set of grid cells, outlined along the cells' outer sides. The header cell drags the
 * whole domain; pressing any other cell, or a cell's outer edge, and dragging grows the domain by single cells.
 */
function DomainGroupNode({ data }: NodeProps<Node<DomainGroupData>>) {
  const { domain, origin } = data;
  const members = new Set(data.cells.map(cellKey));
  const headerKey = cellKey(data.header);
  return (
    <div
      className={`sl-domain-group${data.selected ? ' is-selected' : ''}${domain ? '' : ' is-unassigned'}`}
      style={{ '--domain-color': domain?.color || UNASSIGNED_COLOR } as React.CSSProperties}
    >
      {data.cells.map(cell => {
        const key = cellKey(cell);
        const isHeader = key === headerKey;
        const outer = CELL_SIDES.filter(([direction]) => !members.has(cellKey(stepCell(cell, direction))));
        const sides = outer.map(([, side]) => side);
        const corners = ['tl', 'tr', 'br', 'bl'].filter(corner => sides.includes(corner[0]) && sides.includes(corner[1]));
        return (
          <div
            key={key}
            className={[
              'sl-domain-cell',
              isHeader ? 'is-header' : 'nodrag nopan',
              ...sides.map(side => `edge-${side}`),
              ...corners.map(corner => `round-${corner}`),
            ].join(' ')}
            style={{ left: (cell.col - origin.col) * GRID_CELL, top: (cell.row - origin.row) * GRID_CELL }}
            title={isHeader ? undefined : 'Kéo sang ô bên cạnh để mở rộng nghiệp vụ'}
            onPointerDown={isHeader ? undefined : event => data.onGrow(data.gridKey, cell, null, event)}
          >
            {isHeader ? (
              <div className="sl-domain-group-header">
                {domain ? (
                  <button className="sl-domain-group-label nodrag" type="button" aria-pressed={data.selected} title={`${domain.name}\nChọn nghiệp vụ để xem data lineage`} onClick={() => data.onToggle(domain.id)}>
                    {domain.name}
                  </button>
                ) : <span className="sl-domain-group-label">Chưa phân nghiệp vụ</span>}
                <span className="sl-domain-group-footer">
                  <span className="sl-domain-group-count">{data.count} bảng</span>
                  {domain ? (
                    <button className="sl-domain-group-edit nodrag" type="button" aria-label={`Sửa nghiệp vụ ${domain.name}`} onClick={() => data.onEdit(domain)}><Pencil /></button>
                  ) : null}
                </span>
              </div>
            ) : null}
            {outer.map(([direction, side]) => (
              <span
                key={side}
                className={`sl-domain-grip is-${side} nodrag nopan`}
                title="Kéo để mở rộng hoặc thu hẹp nghiệp vụ một ô"
                onPointerDown={event => data.onGrow(data.gridKey, cell, direction, event)}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

const HANDLE_SIDES: Array<[string, Position]> = [['t', Position.Top], ['b', Position.Bottom], ['l', Position.Left], ['r', Position.Right]];

/**
 * Lineage table card: a header naming the table, one fixed-height row per listed column with a hidden handle on each
 * side where edges attach, and a row that shows or hides the dataset's metrics in a column beside the card, with an
 * arrow from that row to each. The header handles start new edges, and carry the edges whose column the card does not
 * list.
 */
function LineageTableNode({ id, data }: NodeProps<Node<LineageCardData>>) {
  const { focus } = useContext(MetricFocusContext);
  const metricsOpen = data.metricsOpen === true;
  const { columns, hidden } = data.content;
  return (
    <div
      className={`sl-lineage-card${data.active ? '' : ' is-inactive'}`}
      style={{ height: cardHeight(data.content), ...(data.layerColor ? { '--layer-color': data.layerColor } : {}) } as React.CSSProperties}
    >
      {HANDLE_SIDES.map(([id, position]) => (
        <Handle
          key={id}
          id={id}
          type="source"
          position={position}
          className="sl-model-handle"
          style={position === Position.Left || position === Position.Right ? { top: CARD_BORDER + CARD_HEADER / 2 } : undefined}
        />
      ))}
      <div className="sl-lineage-card-header" title={`${data.title}\n${data.tableName} · ${data.layerName ?? 'Chưa phân tầng'}`}>
        <span className="sl-model-table-icon"><Table2 /></span>
        <span className="sl-model-table-copy">
          <strong>{data.title}</strong>
          <code>{data.tableName}</code>
        </span>
        {data.sharedCount > 1 ? <span className="sl-model-shared" title={`Dùng chung cho ${data.sharedCount} nghiệp vụ`}>×{data.sharedCount}</span> : null}
      </div>
      {columns.map(column => (
        <div
          key={column.name}
          className={`sl-lineage-column${focus?.card === id && focus.roles.has(column.name) ? ` is-${focus.roles.get(column.name)}` : ''}`}
          title={column.title}
        >
          <Handle id={`c:${column.name}:l`} type="source" position={Position.Left} isConnectable={false} className="sl-column-handle" />
          <span className="sl-lineage-column-keys">
            {column.pk ? <span className="sl-model-key is-pk">PK</span> : null}
            {column.fk ? <span className="sl-model-key is-fk">FK</span> : null}
            {column.metric && !(column.pk && column.fk) ? <span className="sl-model-key is-metric">Σ</span> : null}
          </span>
          <code>{column.name}</code>
          <span className="sl-lineage-column-type">{column.type}</span>
          <Handle id={`c:${column.name}:r`} type="source" position={Position.Right} isConnectable={false} className="sl-column-handle" />
        </div>
      ))}
      {hidden > 0 ? <div className="sl-lineage-more">+{hidden} cột khác</div> : null}
      {data.metrics.length > 0 ? (
        <div className="sl-lineage-metrics-row">
          <button
            type="button"
            className={`sl-lineage-metrics nodrag${metricsOpen ? ' is-open' : ''}`}
            aria-expanded={metricsOpen}
            title={metricsOpen ? 'Ẩn các chỉ số' : 'Hiện các chỉ số bên cạnh bảng'}
            onClick={event => {
              // Showing the metrics is not a click on the card, which would trace its lineage.
              event.stopPropagation();
              data.onToggleMetrics?.(id);
            }}
          >
            <Sigma />
            <span>{data.metrics.length} chỉ số</span>
            <ChevronRight />
          </button>
          <Handle id="metrics" type="source" position={Position.Right} isConnectable={false} className="sl-column-handle" />
        </div>
      ) : null}
    </div>
  );
}

/**
 * A metric beside its dataset's card. While it, or an arrow to it, is hovered, its formula shows above it and the
 * columns it uses light up on the card: strongly the values it aggregates, faintly those that pick its rows.
 */
function MetricNode({ id, data }: NodeProps<Node<MetricData>>) {
  const { focus, hover } = useContext(MetricFocusContext);
  const { metric } = data;
  return (
    <div
      className={`sl-lineage-metric-node${data.dimmed ? ' is-dimmed' : ''}${focus?.metricNodeId === id ? ' is-focused' : ''}`}
      onMouseEnter={() => hover(id)}
      onMouseLeave={() => hover(null)}
    >
      <Handle id="l" type="target" position={Position.Left} isConnectable={false} className="sl-column-handle" />
      <Sigma />
      <strong>{metric.verbose_name || metric.metric_name}</strong>
      <NodeToolbar
        isVisible={Boolean(metric.expression) && focus?.metricNodeId === id}
        // Above the metric: metrics usually stand at the right edge of the lineage, where a box beside them is cut off.
        // It opens rightwards from the metric's left edge, so it leaves the card's lit columns in view.
        position={Position.Top}
        align="start"
        offset={8}
        className="sl-lineage-formula"
      >
        <span>{metric.metric_name}</span>
        <code>{metric.expression}</code>
        {metric.description ? <small>{metric.description}</small> : null}
      </NodeToolbar>
    </div>
  );
}

/** A lineage lane band; its header is the handle that drags the band with all its cards. */
function LaneNode({ data }: NodeProps<Node<LaneData>>) {
  return (
    <div className="sl-model-lane" style={data.color ? { '--lane-color': data.color } as React.CSSProperties : undefined}>
      <span className="sl-model-lane-label" title={`${data.label}${data.hint ? `\n${data.hint}` : ''}\nKéo để di chuyển cả tầng`}>
        <strong>{data.label}<GripHorizontal className="sl-model-lane-grip" aria-hidden="true" /></strong>
        {data.hint ? <small>{data.hint}</small> : null}
      </span>
    </div>
  );
}

/** Header over a lineage column: the level, and how many layers share it. */
function LevelNode({ data }: NodeProps<Node<LevelData>>) {
  return (
    <div className="sl-lineage-level">
      <strong>{data.label}</strong>
      {data.count > 1 ? <span>{data.count} tầng cùng cấp</span> : null}
    </div>
  );
}

/** Business-view table: a square tile that fills one canvas grid cell. */
function TableTile({ data }: NodeProps<Node<TableData>>) {
  return (
    <div
      className="sl-model-tile"
      title={`${data.title}\n${data.tableName} · ${data.layerName ?? 'Chưa phân tầng'}`}
      style={data.layerColor ? { '--layer-color': data.layerColor } as React.CSSProperties : undefined}
    >
      <span className="sl-model-tile-top">
        <span className="sl-model-table-icon"><Table2 /></span>
        {data.sharedCount > 1 ? <span className="sl-model-shared" title={`Dùng chung cho ${data.sharedCount} nghiệp vụ`}>×{data.sharedCount}</span> : null}
      </span>
      <strong>{data.title}</strong>
      <code>{data.tableName}</code>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  domainGroup: DomainGroupNode,
  modelTable: LineageTableNode,
  tableTile: TableTile,
  lane: LaneNode,
  level: LevelNode,
  lineageMetric: MetricNode,
};

const tileId = (datasetId: number) => `tile-${datasetId}`;
const EMPTY_GRID: CanvasGrid = { domains: [], tables: new Map() };

/** Number of tables lying in a domain's cells. */
function tableCount(grid: CanvasGrid, domain: DomainGrid): number {
  const covered = new Set(domain.cells.map(cellKey));
  return [...grid.tables.values()].filter(cell => covered.has(cellKey(cell))).length;
}

/** Moves the domain nodes and table tiles to the cells of `grid`. */
function applyGrid(nodes: Node[], grid: CanvasGrid): Node[] {
  const domains = new Map(grid.domains.map(domain => [domain.key, domain]));
  return nodes.map(node => {
    const domain = node.type === 'domainGroup' ? domains.get(node.id) : undefined;
    if (domain) {
      const frame = domainFrame(domain);
      return {
        ...node,
        position: frame.position,
        style: { ...node.style, width: frame.size.width, height: frame.size.height },
        data: { ...node.data, cells: domain.cells, header: domain.header, origin: frame.origin, count: tableCount(grid, domain) },
      };
    }
    const cell = node.type === 'tableTile' ? grid.tables.get((node.data as { datasetId: number }).datasetId) : undefined;
    return cell ? { ...node, position: tilePosition(cell) } : node;
  });
}

/**
 * Cells a domain may not grow into: the unassigned area keeps clear of the domains, while a domain may overlap other
 * domains but not their headers or the unassigned area.
 */
function blockedCells(grid: CanvasGrid, key: string): Set<string> {
  const others = grid.domains.filter(domain => domain.key !== key);
  if (key === UNASSIGNED_DOMAIN) return new Set(others.flatMap(domain => domain.cells.map(cellKey)));
  return new Set(others.flatMap(domain => (domain.key === UNASSIGNED_DOMAIN ? domain.cells : [domain.header]).map(cellKey)));
}

/** Tables of a domain that no other domain covers: they move along when the domain is dragged. */
function ownTables(grid: CanvasGrid, key: string): number[] {
  const own = new Set(grid.domains.find(domain => domain.key === key)?.cells.map(cellKey));
  const others = new Set(grid.domains.filter(domain => domain.key !== key).flatMap(domain => domain.cells.map(cellKey)));
  return [...grid.tables].filter(([, cell]) => own.has(cellKey(cell)) && !others.has(cellKey(cell))).map(([id]) => id);
}

const shiftCell = (cell: Cell, shift: Cell) => ({ col: cell.col + shift.col, row: cell.row + shift.row });
const snapToUnit = (value: number, unit: number) => Math.round(value / unit) * unit;
/** Lineage cards snap to this step when dragged, and move down by it to clear a card they would cover. */
const LINEAGE_SNAP = 8;
/** Least room between two lineage cards stacked in one column. */
const CARD_GAP = 16;
/** Below this zoom the column rows are too small to read, so a fitted lineage does not zoom out further. */
const LINEAGE_MIN_FIT_ZOOM = 0.55;

const DETAIL_LEVEL_KEY = 'text-to-bi.semantic-layer.lineage-detail';
function readDetailLevel(): DetailLevel {
  try {
    const stored = window.localStorage.getItem(DETAIL_LEVEL_KEY);
    if (DETAIL_LEVELS.some(([level]) => level === stored)) return stored as DetailLevel;
  } catch { /* storage may be unavailable */ }
  return 'keys';
}

/** Where an edge meets one of its cards: the height on the card and the side. */
type EdgeAnchor = { y: number; side: CardSide };

const isCard = (node: Node) => node.type === 'modelTable';
const cardBox = (node: Node, position = node.position): Box => ({
  ...position,
  width: CARD_WIDTH,
  height: cardHeight((node.data as LineageCardData).content),
});
const overlap = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
/** The column of a card's metrics, while they stand beside it. */
const metricBox = (node: Node, position = node.position): Box | null => {
  const data = node.data as LineageCardData;
  return data.metricsOpen && data.metrics.length > 0 ? metricColumn(position, metricSlots(data.content, data.metrics)) : null;
};
/** What a card takes up on the canvas: the card, and its metrics beside it. */
const cardFootprint = (node: Node, position = node.position): Box => {
  const [card, metrics] = [cardBox(node, position), metricBox(node, position)];
  if (!metrics) return card;
  const bottom = Math.max(card.y + card.height, metrics.y + metrics.height);
  return { x: card.x, y: card.y, width: metrics.x + metrics.width - card.x, height: bottom - card.y };
};

/** The band of each lane around its cards, padded as ELK pads it, keyed by lane key; metrics may stand outside it. */
function laneBands(nodes: Node[]): Map<string, Box> {
  const bounds = new Map<string, { left: number; top: number; right: number; bottom: number }>();
  for (const node of nodes) {
    if (!isCard(node)) continue;
    const box = cardBox(node);
    const lane = (node.data as LineageCardData).lane;
    const current = bounds.get(lane);
    bounds.set(lane, {
      left: Math.min(current?.left ?? Infinity, box.x),
      top: Math.min(current?.top ?? Infinity, box.y),
      right: Math.max(current?.right ?? -Infinity, box.x + box.width),
      bottom: Math.max(current?.bottom ?? -Infinity, box.y + box.height),
    });
  }
  return new Map([...bounds].map(([lane, { left, top, right, bottom }]) => [lane, {
    x: left - LANE_INSET,
    y: top - LANE_HEADER,
    width: right - left + LANE_INSET * 2,
    height: bottom - top + LANE_HEADER + LANE_INSET,
  }]));
}

/** Pairs of lanes whose bands overlap, as "a|b" keys. */
function clashingBands(bands: Map<string, Box>): Set<string> {
  const entries = [...bands];
  const pairs = new Set<string>();
  entries.forEach(([a, boxA], index) => entries.slice(index + 1).forEach(([b, boxB]) => {
    if (overlap(boxA, boxB)) pairs.add([a, b].sort().join('|'));
  }));
  return pairs;
}

/** What lineage edges keep clear of: every card and metric column, and the header of every lane band. */
function edgeObstacles(nodes: Node[]): Box[] {
  return [
    ...nodes.filter(isCard).flatMap(node => [cardBox(node), metricBox(node)].filter((box): box is Box => box !== null)),
    ...[...laneBands(nodes).values()].map(band => ({ ...band, height: LANE_HEADER - 8 })),
  ];
}

/** Canvas point where an edge meets a card at `anchor`. */
const anchorPoint = (position: Point, anchor: EdgeAnchor): Point => ({
  x: position.x + (anchor.side === 'right' ? CARD_WIDTH : 0),
  y: position.y + anchor.y,
});

/** An orthogonal shape for an edge between cards at these positions that keeps clear of `obstacles`. */
function routedGeometry(source: Point, target: Point, anchors: [EdgeAnchor, EdgeAnchor], obstacles: Box[]): EdgeGeometry {
  const route = routeOrthogonal(anchorPoint(source, anchors[0]), anchors[0].side, anchorPoint(target, anchors[1]), anchors[1].side, obstacles);
  const coords = route ? coordsFromRoute(route) : null;
  return coords ? { ...DEFAULT_GEOMETRY, coords } : DEFAULT_GEOMETRY;
}

const sidePosition = (side: CardSide) => (side === 'right' ? Position.Right : Position.Left);

/** Whether an edge, drawn with its geometry between cards at these positions, runs through any of `boxes`. */
function edgeCrosses(geometry: EdgeGeometry, source: Point, target: Point, anchors: [EdgeAnchor, EdgeAnchor], boxes: Box[]): boolean {
  const [start, end] = [anchorPoint(source, anchors[0]), anchorPoint(target, anchors[1])];
  return routeCrosses(edgePoints(geometry, start, end, sidePosition(anchors[0].side), sidePosition(anchors[1].side)), boxes);
}

/** Lineage nodes and edges joined to `nodeId` through any chain of edges, read left to right along the layout. */
function tracedLineage(nodeId: string, edges: Edge[]): { nodes: Set<string>; edges: Set<string> } {
  const flows = edges.map(edge => ({ id: edge.id, flow: (edge.data as RoutedEdgeData | undefined)?.flow ?? [edge.source, edge.target] }));
  const nodes = new Set([nodeId]);
  const traced = new Set<string>();
  // Upstream follows edges backwards from the card, downstream forwards, so siblings of the card stay faded.
  for (const [from, to] of [[0, 1], [1, 0]] as const) {
    const queue = [nodeId];
    const seen = new Set(queue);
    while (queue.length > 0) {
      const current = queue.shift() as string;
      for (const edge of flows) {
        if (edge.flow[from] !== current) continue;
        traced.add(edge.id);
        nodes.add(edge.flow[to]);
        if (!seen.has(edge.flow[to])) {
          seen.add(edge.flow[to]);
          queue.push(edge.flow[to]);
        }
      }
    }
  }
  return { nodes, edges: traced };
}

/**
 * A lineage edge label, shown while the edge is hovered or selected: the cardinality, then each column pair it joins
 * read left to right like the layout, or the label of a manual edge.
 */
type EdgeLabel = Size & { lines: string[] };
/**
 * A lineage edge: its shape (see EdgeGeometry) and what it joins. `flow` is its left-to-right direction on the canvas;
 * `anchors` are where it meets its source and target cards, to route it again when a card moves.
 */
type RoutedEdgeData = {
  geometry: EdgeGeometry;
  label?: EdgeLabel;
  muted?: boolean;
  lineage?: LineageEdge;
  flow: [string, string];
  anchors: [EdgeAnchor, EdgeAnchor];
};

/** What lineage edges need from the canvas to be shaped in place. */
type EdgeEditing = {
  selectedId: string | null;
  hoveredId: string | null;
  select: (id: string) => void;
  /** Draws `geometry` on the edge; `commit` also stores it, once a drag ends. */
  update: (id: string, geometry: EdgeGeometry, commit: boolean) => void;
};
const EdgeEditingContext = createContext<EdgeEditing | null>(null);

const LABEL_CHAR_WIDTH = 6.6;
const LABEL_LINE_HEIGHT = 16;
const LABEL_PADDING = 8;
const LABEL_MAX_PAIRS = 3;

/** The label of a lineage edge; `reversed` is set when the edge's target sits on the left. */
function edgeLabel(edge: LineageEdge, reversed: boolean): EdgeLabel | undefined {
  const [left, right] = reversed
    ? [edge.target_cardinality, edge.source_cardinality]
    : [edge.source_cardinality, edge.target_cardinality];
  const pairs = (edge.column_links ?? []).map(pair => (reversed ? `${pair.target} → ${pair.source}` : `${pair.source} → ${pair.target}`));
  const lines = [
    ...(left && right ? [`${left} : ${right}`] : edge.label ? [edge.label] : []),
    ...pairs.slice(0, LABEL_MAX_PAIRS),
    ...(pairs.length > LABEL_MAX_PAIRS ? [`+${pairs.length - LABEL_MAX_PAIRS} cặp cột`] : []),
  ];
  if (lines.length === 0) return undefined;
  const width = Math.ceil(Math.max(...lines.map(line => line.length)) * LABEL_CHAR_WIDTH) + LABEL_PADDING * 2;
  return { lines, width, height: lines.length * LABEL_LINE_HEIGHT + 8 };
}

/** Edge-end notation: a crow's foot for the "n" side, a bar for the "1" side, an arrow for a manual edge's target. */
type MarkerKind = 'many' | 'one' | 'arrow';
const MARKER_PATHS: Record<MarkerKind, string> = {
  many: 'M2,7 L14,1 M2,7 L14,7 M2,7 L14,13',
  one: 'M8,1 L8,13',
  arrow: 'M1,2 L14,7 L1,12 Z',
};
const markerId = (kind: MarkerKind, stroke: string) => `sl-marker-${kind}-${stroke.replace(/[^a-z0-9]/gi, '')}`;
const cardinalityMarker = (cardinality: '1' | 'n' | undefined, stroke: string) => (
  cardinality ? markerId(cardinality === 'n' ? 'many' : 'one', stroke) : undefined
);

/** SVG markers for every stroke colour the edges use; edges reference them by markerId. */
function EdgeMarkers({ strokes }: { strokes: string[] }) {
  return (
    <svg className="sl-edge-markers" aria-hidden="true">
      <defs>
        {strokes.flatMap(stroke => (Object.keys(MARKER_PATHS) as MarkerKind[]).map(kind => (
          <marker
            key={markerId(kind, stroke)}
            id={markerId(kind, stroke)}
            viewBox="0 0 14 14"
            markerWidth="14"
            markerHeight="14"
            markerUnits="userSpaceOnUse"
            refX="14"
            refY="7"
            orient="auto-start-reverse"
          >
            <path d={MARKER_PATHS[kind]} style={kind === 'arrow' ? { fill: stroke, stroke: 'none' } : { fill: 'none', stroke, strokeWidth: 1.6 }} />
          </marker>
        )))}
      </defs>
    </svg>
  );
}

const snapValue = (value: number) => snapPoint({ x: value, y: 0 }).x;
const stopClick = (event: React.MouseEvent) => event.stopPropagation();

/**
 * An edge the user shapes as in draw.io. Selected, it shows handles: an orthogonal edge has a handle on each inner
 * segment that moves the segment across; a straight or curved edge has a dot on each waypoint (double-click removes
 * it) and a faint one between points that adds a waypoint. Its ends stay on the column rows it joins. The label shows
 * while the edge is hovered or selected, can be dragged anywhere and returns to the middle on double-click.
 */
function RoutedEdge({ id, data, style, markerStart, markerEnd, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition }: EdgeProps<Edge<RoutedEdgeData>>) {
  const editing = useContext(EdgeEditingContext);
  const { screenToFlowPosition } = useReactFlow();
  const geometry = data?.geometry ?? DEFAULT_GEOMETRY;
  const source = { x: sourceX, y: sourceY };
  const target = { x: targetX, y: targetY };
  const points = edgePoints(geometry, source, target, sourcePosition, targetPosition);
  const { path, trace } = edgePath(geometry, points, sourcePosition, targetPosition);
  const anchor = midpoint(trace);
  const selected = editing?.selectedId === id;
  const hovered = editing?.hoveredId === id;

  // Follows the pointer from a handle: `change` gives the geometry for the pointer's canvas position.
  const drag = (event: React.PointerEvent, change: (pointer: Point, start: Point) => EdgeGeometry) => {
    if (!editing || event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    editing.select(id);
    const start = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    let next = geometry;
    const move = (moveEvent: PointerEvent) => {
      next = change(screenToFlowPosition({ x: moveEvent.clientX, y: moveEvent.clientY }), start);
      editing.update(id, next, false);
    };
    const end = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      if (next !== geometry) editing.update(id, next, true);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
  };

  const handles: React.ReactNode[] = [];
  if (selected) {
    if (geometry.style === 'orthogonal') {
      const coords = effectiveCoords(geometry, source, target, sourcePosition, targetPosition);
      if (coords.length === 0) {
        // A level edge: pulling its middle up or down gives it a step.
        handles.push(
          <EdgeHandle
            key="step"
            at={anchor}
            kind="horizontal"
            title="Kéo lên xuống để uốn cạnh"
            onPointerDown={event => drag(event, pointer => {
              const quarter = (target.x - source.x) / 4;
              return { ...geometry, coords: [snapValue(source.x + quarter), snapValue(pointer.y), snapValue(target.x - quarter)] };
            })}
          />,
        );
      }
      coords.forEach((_, index) => {
        const [from, to] = [points[index + 1], points[index + 2]];
        const vertical = index % 2 === 0;
        handles.push(
          <EdgeHandle
            key={`segment-${index}`}
            at={{ x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 }}
            kind={vertical ? 'vertical' : 'horizontal'}
            title={vertical ? 'Kéo sang trái phải để dời đoạn cạnh' : 'Kéo lên xuống để dời đoạn cạnh'}
            onPointerDown={event => drag(event, pointer => {
              const next = [...coords];
              next[index] = snapValue(vertical ? pointer.x : pointer.y);
              return { ...geometry, coords: next };
            })}
          />,
        );
      });
    } else {
      geometry.waypoints.forEach((point, index) => handles.push(
        <EdgeHandle
          key={`point-${index}`}
          at={point}
          kind="point"
          title="Kéo để dời điểm uốn, nhấp đúp để bỏ"
          onPointerDown={event => drag(event, pointer => ({
            ...geometry,
            waypoints: geometry.waypoints.map((other, at) => (at === index ? snapPoint(pointer) : other)),
          }))}
          onDoubleClick={() => editing?.update(id, { ...geometry, waypoints: geometry.waypoints.filter((_, at) => at !== index) }, true)}
        />,
      ));
      points.slice(1).forEach((point, index) => {
        const from = points[index];
        handles.push(
          <EdgeHandle
            key={`add-${index}`}
            at={{ x: (from.x + point.x) / 2, y: (from.y + point.y) / 2 }}
            kind="add"
            title="Kéo để thêm điểm uốn"
            onPointerDown={event => drag(event, pointer => {
              const waypoints = [...geometry.waypoints];
              waypoints.splice(index, 0, snapPoint(pointer));
              return { ...geometry, waypoints };
            })}
          />,
        );
      });
    }
  }

  const label = data?.label;
  const offset = geometry.label ?? { x: 0, y: 0 };
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        style={selected ? { ...style, strokeWidth: Number(style?.strokeWidth ?? 1.5) + 1.5 } : style}
        markerStart={markerStart}
        markerEnd={markerEnd}
      />
      {label && (selected || hovered) ? (
        <EdgeLabelBox
          label={label}
          muted={data?.muted}
          selected={selected}
          at={{ x: anchor.x + offset.x - label.width / 2, y: anchor.y + offset.y - label.height / 2 }}
          onPointerDown={event => drag(event, (pointer, start) => ({
            ...geometry,
            label: { x: Math.round(offset.x + pointer.x - start.x), y: Math.round(offset.y + pointer.y - start.y) },
          }))}
          onDoubleClick={() => editing?.update(id, { ...geometry, label: null }, true)}
        />
      ) : null}
      {handles.length > 0 ? <EdgeLabelRenderer>{handles}</EdgeLabelRenderer> : null}
    </>
  );
}

type EdgeHandleProps = {
  at: Point;
  kind: 'vertical' | 'horizontal' | 'point' | 'add';
  title: string;
  onPointerDown: (event: React.PointerEvent) => void;
  onDoubleClick?: () => void;
};

function EdgeHandle({ at, kind, title, onPointerDown, onDoubleClick }: EdgeHandleProps) {
  return (
    <div
      className={`sl-edge-handle is-${kind} nodrag nopan`}
      style={{ transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)` }}
      title={title}
      onPointerDown={onPointerDown}
      onClick={stopClick}
      onDoubleClick={event => { event.stopPropagation(); onDoubleClick?.(); }}
    />
  );
}

type EdgeLabelBoxProps = {
  label: EdgeLabel;
  muted?: boolean;
  selected: boolean;
  at: Point;
  onPointerDown: (event: React.PointerEvent) => void;
  onDoubleClick: () => void;
};

function EdgeLabelBox({ label, muted, selected, at, onPointerDown, onDoubleClick }: EdgeLabelBoxProps) {
  return (
    <EdgeLabelRenderer>
      <div
        className={`sl-edge-label nodrag nopan${muted ? ' is-muted' : ''}${selected ? ' is-selected' : ''}`}
        style={{ transform: `translate(${at.x}px, ${at.y}px)`, width: label.width, height: label.height }}
        title="Kéo để dời nhãn, nhấp đúp để đưa về giữa cạnh"
        onPointerDown={onPointerDown}
        onClick={stopClick}
        onDoubleClick={event => { event.stopPropagation(); onDoubleClick(); }}
      >
        {label.lines.map((line, index) => <span key={index}>{line}</span>)}
      </div>
    </EdgeLabelRenderer>
  );
}

/**
 * An arrow from a card to one of its metrics: a short level line from each row the metric is computed from, joined by
 * one vertical run in the arrow's own lane, then a single arrowhead into the metric. A dot marks each row it leaves.
 * While a metric is looked at, its arrow stands out and the card's other arrows fade.
 */
function MetricArrow({ id, target, data, markerEnd, style }: EdgeProps<Edge<MetricArrowData>>) {
  const { focus } = useContext(MetricFocusContext);
  if (!data) return null;
  const { start, sources, lane, end } = data;
  const [top, bottom] = [Math.min(end.y, ...sources), Math.max(end.y, ...sources)];
  const path = [
    ...sources.map(y => `M ${start},${y} H ${lane}`),
    top < bottom ? `M ${lane},${top} V ${bottom}` : '',
    `M ${lane},${end.y} H ${end.x}`,
  ].join(' ');
  const focused = focus?.metricNodeId === target;
  const faded = Boolean(focus) && focus?.card === data.card && !focused;
  const shown = { ...style, strokeWidth: focused ? 2.5 : 1.5, opacity: faded ? 0.15 : 1 };
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={shown} interactionWidth={14} />
      {sources.map(y => <circle key={y} cx={start} cy={y} r={focused ? 3.5 : 2.5} fill={METRIC_EDGE_COLOR} opacity={shown.opacity} />)}
    </>
  );
}

const edgeTypes: EdgeTypes = { routed: RoutedEdge, metricArrow: MetricArrow };

type BusinessCanvasProps = {
  themeMode: ThemeMode;
  databaseId: number;
  datasets: DashboardDataset[];
  dictionaries: Record<number, DatasetDictionary>;
  focusDatasetId: number | null;
  /** Changes when data layers or dictionaries change, so the model is reloaded with the new classification. */
  revision: number;
};

function BusinessFlow({ themeMode, databaseId, datasets, dictionaries, focusDatasetId, revision }: BusinessCanvasProps) {
  const [model, setModel] = useState<BusinessModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<ViewMode>('business');
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const [selectedDomainIds, setSelectedDomainIds] = useState<number[]>([]);
  const [dialog, setDialog] = useState<{ open: boolean; domain: BusinessDomain | null }>({ open: false, domain: null });
  // Key of the lineage edge whose colour panel is open ("kind-source-target").
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { fitView, getEdges, getNode, getNodes, getZoom, screenToFlowPosition, setViewport } = useReactFlow();
  // Brings the whole diagram into view, clear of the lineage tools at the top right. A lineage too big to fit at a
  // readable zoom opens on its top-left corner at that zoom instead.
  const fitCanvas = useCallback(async () => {
    if (mode === 'business') {
      await fitView({ padding: 0.12, duration: 250, maxZoom: 1 });
      return;
    }
    await fitView({ padding: { top: '32px', bottom: '32px', left: '32px', right: '200px' }, duration: 250, maxZoom: 1 });
    if (getZoom() >= LINEAGE_MIN_FIT_ZOOM) return;
    const left = Math.min(...getNodes().map(node => node.position.x));
    await setViewport({ x: 32 - left * LINEAGE_MIN_FIT_ZOOM, y: 32, zoom: LINEAGE_MIN_FIT_ZOOM }, { duration: 250 });
  }, [mode, fitView, getZoom, getNodes, setViewport]);

  // Collapsing or opening the panel resizes the canvas; once React Flow has measured it, the diagram is centred again.
  const collapsedRef = useRef(panelCollapsed);
  useEffect(() => {
    if (collapsedRef.current === panelCollapsed) return undefined;
    collapsedRef.current = panelCollapsed;
    let frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(() => void fitCanvas());
    });
    return () => window.cancelAnimationFrame(frame);
  }, [panelCollapsed, fitCanvas]);
  // Where the dragged lineage cards started, to put them back when dropped onto another card.
  const lineageDragRef = useRef(new Map<string, Point>());
  // Cells of the business-view domains and tables, including the user's moves and growth, kept across re-layouts.
  const gridRef = useRef<CanvasGrid>(EMPTY_GRID);
  // Tables carried along by the domain being dragged.
  const followersRef = useRef<{ key: string; ids: number[] } | null>(null);
  // The canvas as last stored in the backend, serialized, so unchanged layouts are not sent again.
  const savedLayoutRef = useRef<string | null>(null);
  const [pending, setPending] = useState<PendingChanges | null>(null);
  // Lineage cards the user moved and edges the user shaped, kept across re-layouts and stored in the backend.
  const lineageLayoutRef = useRef<LineageLayout>({ nodes: new Map(), edges: new Map() });
  const lineageLoadedRef = useRef(false);
  const savedLineageRef = useRef<string | null>(null);
  // The shape each lineage edge takes when the user resets it: ELK's route while both cards stay where ELK put them.
  const autoGeometryRef = useRef(new Map<string, EdgeGeometry>());
  // Bumped to lay the lineage out again after the user's placements are cleared.
  const [lineageRevision, setLineageRevision] = useState(0);
  const [savingMembers, setSavingMembers] = useState(false);
  const [detailLevel, setDetailLevel] = useState<DetailLevel>(readDetailLevel);
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  // The lineage card whose upstream and downstream tables stay lit while the rest of the lineage fades.
  const [traceNodeId, setTraceNodeId] = useState<string | null>(null);
  // Cards whose metrics the user put away; every other card shows its metrics beside it.
  const [hiddenMetrics, setHiddenMetrics] = useState<Set<string>>(() => new Set());
  const [hoveredMetricId, setHoveredMetricId] = useState<string | null>(null);
  // Far out, cards drop their small print so the table names stay readable.
  const zoomedOut = useStore(state => state.transform[2] < 0.5);

  const loadModel = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const payload = await requestJson<BusinessModel>(semanticLayerApi.businessModel(databaseId), 'GET');
      setModel(payload);
      setSelectedDomainIds(current => current.filter(id => payload.domains.some(domain => domain.id === id)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được mô hình nghiệp vụ.');
    } finally {
      setLoading(false);
    }
  }, [databaseId]);

  // Another database has its own canvas.
  useEffect(() => {
    gridRef.current = EMPTY_GRID;
    savedLayoutRef.current = null;
    lineageLayoutRef.current = { nodes: new Map(), edges: new Map() };
    lineageLoadedRef.current = false;
    savedLineageRef.current = null;
    setModel(null);
  }, [databaseId]);
  useEffect(() => { void loadModel(); }, [loadModel, revision]);

  // Stores the business-view canvas so a reload draws domains and tables where the user left them.
  const saveGrid = useCallback((grid: CanvasGrid) => {
    const layout = JSON.stringify(toStoredCanvas(grid));
    if (layout === savedLayoutRef.current) return;
    savedLayoutRef.current = layout;
    requestJson(semanticLayerApi.businessCanvas(databaseId), 'PUT', JSON.parse(layout)).catch(reason => {
      savedLayoutRef.current = null;
      setError(reason instanceof Error ? reason.message : 'Không lưu được bố cục canvas.');
    });
  }, [databaseId]);

  // Stores the lineage cards and edges the user placed, so a reload keeps them.
  const saveLineage = useCallback(() => {
    const layout = JSON.stringify(toStoredLineage(lineageLayoutRef.current));
    if (layout === savedLineageRef.current) return;
    savedLineageRef.current = layout;
    requestJson(semanticLayerApi.lineageCanvas(databaseId), 'PUT', JSON.parse(layout)).catch(reason => {
      savedLineageRef.current = null;
      setError(reason instanceof Error ? reason.message : 'Không lưu được bố cục lineage.');
    });
  }, [databaseId]);

  const updateEdgeGeometry = useCallback((id: string, geometry: EdgeGeometry, commit: boolean) => {
    setEdges(current => current.map(edge => (edge.id === id ? { ...edge, data: { ...edge.data, geometry } } : edge)));
    if (!commit) return;
    lineageLayoutRef.current.edges.set(id, geometry);
    saveLineage();
  }, [setEdges, saveLineage]);
  const edgeEditing = useMemo<EdgeEditing>(
    () => ({ selectedId: selectedEdgeKey, hoveredId: hoveredEdgeId, select: setSelectedEdgeKey, update: updateEdgeGeometry }),
    [selectedEdgeKey, hoveredEdgeId, updateEdgeGeometry],
  );
  const chooseDetailLevel = (level: DetailLevel) => {
    setDetailLevel(level);
    try { window.localStorage.setItem(DETAIL_LEVEL_KEY, level); } catch { /* the choice just is not remembered */ }
  };

  const datasetById = useMemo(() => new Map(datasets.map(dataset => [dataset.id, dataset])), [datasets]);
  const domains = model?.domains ?? [];
  const layers = model?.layers ?? [];
  const layerIdOf = useCallback((datasetId: number) => model?.classifications[String(datasetId)]?.layer_id ?? null, [model]);
  // The business view groups base tables only; aggregate and not-yet-classified tables stay out of the domains.
  const baseDatasets = useMemo(
    () => datasets.filter(dataset => model?.classifications[String(dataset.id)]?.dataset_type === 'base'),
    [datasets, model],
  );
  const baseIds = useMemo(() => new Set(baseDatasets.map(dataset => dataset.id)), [baseDatasets]);
  const domainCountByDataset = useMemo(() => {
    const counts = new Map<number, number>();
    for (const domain of domains) for (const id of domain.dataset_ids) counts.set(id, (counts.get(id) ?? 0) + 1);
    return counts;
  }, [domains]);

  const metricsByDataset = useMemo(() => {
    const result = new Map<number, ModelMetric[]>();
    for (const metric of model?.metrics ?? []) result.set(metric.dataset_id, [...(result.get(metric.dataset_id) ?? []), metric]);
    return result;
  }, [model]);

  // What each lineage card lists at the chosen detail level, in dictionary order: no columns, the key columns (primary
  // keys, foreign keys and the columns other tables point at) or all of them. The tooltip of a column tells its display
  // name and what it references or is referenced by.
  const cardContents = useMemo(() => {
    const tableLabel = (datasetId: number) => datasetById.get(datasetId)?.table_name ?? `Dataset ${datasetId}`;
    const referencedBy = new Map<string, string[]>();
    for (const dictionary of Object.values(dictionaries)) {
      for (const column of dictionary.columns) {
        if (column.referenced_dataset_id == null || !column.referenced_column_name) continue;
        const key = `${column.referenced_dataset_id}.${column.referenced_column_name}`;
        referencedBy.set(key, [...(referencedBy.get(key) ?? []), `${tableLabel(dictionary.dataset_id)}.${column.column_name}`]);
      }
    }
    const result = new Map<number, CardContent>();
    for (const dataset of datasets) {
      const datasetMetrics = metricsByDataset.get(dataset.id) ?? [];
      const metrics = datasetMetrics.length;
      // Columns a metric arrow leaves from are listed with the keys, so the arrow has a row to leave.
      const feeds = new Map<string, string[]>();
      for (const metric of datasetMetrics) {
        for (const name of metricSources(metric)) feeds.set(name, [...(feeds.get(name) ?? []), metric.verbose_name || metric.metric_name]);
      }
      const metricNote = (name: string) => (feeds.has(name) ? `Σ ${(feeds.get(name) as string[]).join(', ')}` : null);
      const dictionaryColumns = dictionaries[dataset.id]?.columns;
      const all: Array<CardColumn & { key: boolean }> = dictionaryColumns
        ? dictionaryColumns.map(column => {
          const fk = column.is_fk || column.referenced_dataset_id != null;
          const sources = referencedBy.get(`${dataset.id}.${column.column_name}`) ?? [];
          const metric = feeds.has(column.column_name);
          const notes = [
            column.display_name && column.display_name !== column.column_name ? column.display_name : null,
            fk && column.referenced_dataset_id != null ? `→ ${tableLabel(column.referenced_dataset_id)}.${column.referenced_column_name}` : null,
            ...sources.map(source => `← ${source}`),
            metricNote(column.column_name),
          ].filter(Boolean);
          return {
            name: column.column_name,
            type: column.data_type,
            pk: column.is_pk,
            fk,
            metric,
            title: [column.column_name, ...notes].join('\n'),
            key: column.is_pk || fk || sources.length > 0 || metric,
          };
        })
        : (dataset.columns ?? []).map(column => {
          const metric = feeds.has(column.column_name);
          const title = [column.column_name, metricNote(column.column_name)].filter(Boolean).join('\n');
          return { name: column.column_name, type: column.type ?? '', pk: false, fk: false, metric, title, key: metric };
        });
      const listed = detailLevel === 'all' ? all : detailLevel === 'keys' ? all.filter(column => column.key) : [];
      // Name-only cards stay one header tall instead of counting the columns they leave out.
      const hidden = detailLevel === 'name' ? 0 : all.length - listed.length;
      result.set(dataset.id, { columns: listed.map(({ key: _key, ...column }) => column), hidden, metrics });
    }
    return result;
  }, [datasets, datasetById, dictionaries, metricsByDataset, detailLevel]);
  const contentOf = useCallback(
    (datasetId: number): CardContent => cardContents.get(datasetId) ?? { columns: [], hidden: 0, metrics: 0 },
    [cardContents],
  );

  const toggleDomain = useCallback((domainId: number) => {
    setSelectedDomainIds(current => current.includes(domainId) ? current.filter(id => id !== domainId) : [...current, domainId]);
  }, []);
  const editDomain = useCallback((domain: BusinessDomain | null) => setDialog({ open: true, domain }), []);

  const showGrid = useCallback((grid: CanvasGrid) => {
    gridRef.current = grid;
    setNodes(current => applyGrid(current, grid));
  }, [setNodes]);

  // A finished move or resize either puts tables into or out of domains, which the user confirms first, or only
  // reshapes the canvas. A move that stacks tables or headers in one cell, or leaves a table of no domain outside the
  // unassigned area, is undone.
  const settleGrid = useCallback((next: CanvasGrid, before: CanvasGrid) => {
    if (!model || !validGrid(next)) {
      showGrid(before);
      return;
    }
    const changes = membershipChanges(next);
    if (changes.length > 0) {
      showGrid(next);
      setPending({ changes, before });
      return;
    }
    if (strayTables(next).length > 0) {
      showGrid(before);
      return;
    }
    const settled = reconcileGrid(next, model.domains, baseDatasets.map(dataset => dataset.id));
    showGrid(validGrid(settled) ? settled : next);
    saveGrid(gridRef.current);
  }, [model, baseDatasets, showGrid, saveGrid]);

  // Dragging from a domain cell adds the cells after it, one at a time along its row or column, and dragging back
  // takes them away again. Dragging a cell's outer edge inwards removes that cell.
  const growDomain = useCallback((key: string, start: Cell, edge: Direction | null, event: React.PointerEvent) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const before = gridRef.current;
    let direction = edge;
    const added: Cell[] = [];
    let startRemoved = false;
    const update = (change: (domain: DomainGrid) => DomainGrid) => {
      const grid = gridRef.current;
      const domain = grid.domains.find(item => item.key === key);
      if (!domain) return;
      const next = change(domain);
      if (next !== domain) showGrid({ ...grid, domains: grid.domains.map(item => (item.key === key ? next : item)) });
    };
    const onMove = (move: PointerEvent) => {
      const point = screenToFlowPosition({ x: move.clientX, y: move.clientY });
      const offset = { x: point.x / GRID_CELL - start.col - 0.5, y: point.y / GRID_CELL - start.row - 0.5 };
      if (!direction) {
        if (Math.max(Math.abs(offset.x), Math.abs(offset.y)) < 0.6) return;
        direction = Math.abs(offset.x) >= Math.abs(offset.y) ? (offset.x > 0 ? 'right' : 'left') : (offset.y > 0 ? 'down' : 'up');
      }
      const heading = direction;
      const along = { left: -offset.x, right: offset.x, up: -offset.y, down: offset.y }[heading];
      // A neighbouring cell joins once the pointer is a quarter of the way into it.
      const steps = Math.max(0, Math.floor(along + 0.25));
      update(domain => {
        let cells = domain.cells;
        const members = new Set(cells.map(cellKey));
        const blocked = blockedCells(gridRef.current, key);
        while (added.length > steps) {
          const removed = cellKey(added.pop() as Cell);
          cells = cells.filter(cell => cellKey(cell) !== removed);
        }
        while (added.length < steps) {
          const next = stepCell(start, heading, added.length + 1);
          if (members.has(cellKey(next)) || blocked.has(cellKey(next))) break;
          added.push(next);
          members.add(cellKey(next));
          cells = [...cells, next];
        }
        // An edge dragged inwards past the middle of its cell takes that cell away.
        const shrink = edge !== null && along < 0;
        if (shrink && !startRemoved) {
          const rest = cells.filter(cell => cellKey(cell) !== cellKey(start));
          const isHeader = cellKey(domain.header) === cellKey(start);
          if (!isHeader && rest.length > 0 && cellsConnected(rest)) [cells, startRemoved] = [rest, true];
        } else if (!shrink && startRemoved) {
          [cells, startRemoved] = [[...cells, start], false];
        }
        return cells === domain.cells ? domain : { ...domain, cells };
      });
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      if (gridRef.current !== before) settleGrid(gridRef.current, before);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  }, [screenToFlowPosition, showGrid, settleGrid]);

  // Saves the confirmed membership changes, one update per domain, then reloads the model.
  const confirmPending = async () => {
    if (!pending) return;
    const updates = new Map<number, { domain: BusinessDomain; ids: Set<number> }>();
    for (const change of pending.changes) {
      const entry = updates.get(change.domain.id) ?? { domain: change.domain, ids: new Set(change.domain.dataset_ids) };
      if (change.add) entry.ids.add(change.datasetId);
      else entry.ids.delete(change.datasetId);
      updates.set(change.domain.id, entry);
    }
    setSavingMembers(true);
    try {
      await Promise.all([...updates.values()].map(({ domain, ids }) => requestJson(semanticLayerApi.businessDomain(domain.id), 'PUT', {
        name: domain.name,
        description: domain.description,
        color: domain.color,
        dataset_ids: [...ids],
      })));
      setPending(null);
      await loadModel();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không cập nhật được nghiệp vụ.');
      showGrid(pending.before);
      setPending(null);
    } finally {
      setSavingMembers(false);
    }
  };
  const cancelPending = () => {
    if (pending) showGrid(pending.before);
    setPending(null);
  };

  const tableData = (datasetId: number): TableData => {
    const dataset = datasetById.get(datasetId);
    const tableName = dataset ? getDatasetName(dataset) : `Dataset ${datasetId}`;
    const displayName = dictionaries[datasetId]?.display_name;
    const layer = layers.find(item => item.id === layerIdOf(datasetId));
    return {
      title: displayName && displayName !== dataset?.table_name ? displayName : (dataset?.table_name ?? tableName),
      tableName,
      layerName: layer?.name ?? null,
      layerColor: layer?.color ?? null,
      sharedCount: domainCountByDataset.get(datasetId) ?? 0,
    };
  };

  // Rebuild the diagram whenever the model, the view or the domain selection changes.
  useEffect(() => {
    if (!model) return;
    if (mode === 'business') {
      const ids = baseDatasets.map(dataset => dataset.id);
      // The canvas keeps the cells the user gave domains and tables, on screen or else as stored in the backend; a
      // first or inconsistent layout starts afresh.
      if (gridRef.current.domains.length === 0 && model.canvas) {
        gridRef.current = fromStoredCanvas(model.canvas);
        savedLayoutRef.current = JSON.stringify(model.canvas);
      }
      const kept = gridRef.current.domains.length > 0 ? reconcileGrid(gridRef.current, model.domains, ids) : null;
      const grid = kept && validGrid(kept) ? kept : reconcileGrid(layoutDomainGroups(model.domains, ids), model.domains, ids);
      gridRef.current = grid;
      saveGrid(grid);
      const nextNodes: Node[] = grid.domains.map(domain => {
        const frame = domainFrame(domain);
        return {
          id: domain.key,
          type: 'domainGroup',
          position: frame.position,
          style: { width: frame.size.width, height: frame.size.height },
          data: {
            domain: domain.domain,
            count: tableCount(grid, domain),
            selected: domain.domain ? selectedDomainIds.includes(domain.domain.id) : false,
            onToggle: toggleDomain,
            onEdit: editDomain,
            gridKey: domain.key,
            cells: domain.cells,
            header: domain.header,
            origin: frame.origin,
            onGrow: growDomain,
          },
          selectable: false,
          deletable: false,
          zIndex: 0,
        };
      });
      // Tiles stand on their own above the domains, so one tile can lie in several overlapping domains.
      for (const [datasetId, cell] of grid.tables) {
        nextNodes.push({
          id: tileId(datasetId),
          type: 'tableTile',
          position: tilePosition(cell),
          data: { ...tableData(datasetId), datasetId },
          className: datasetId === focusDatasetId ? 'is-focused' : undefined,
          deletable: false,
          zIndex: 10,
        });
      }
      setNodes(nextNodes);
      setEdges([]);
      window.requestAnimationFrame(() => void fitView({ padding: 0.12, duration: 250, maxZoom: 1 }));
      return undefined;
    }

    // Lineage: ELK computes card positions and edge routes asynchronously; a newer render cancels an older one.
    let cancelled = false;
    const lanes = lineageLanes(model.layers);
    const datasetLanes = new Map(datasets.map(dataset => [dataset.id, datasetLaneKey(layerIdOf(dataset.id))]));
    const items = selectLineageItems(datasetLanes, model.domains, selectedDomainIds, model.edges);
    const itemIds = new Set(items.map(item => item.id));
    const activeIds = new Set(items.filter(item => item.active).map(item => item.id));
    const contentByNode = new Map(items.map(item => [item.id, contentOf(item.datasetId)]));
    const heightOf = (nodeId: string) => cardHeight(contentByNode.get(nodeId) as CardContent);
    const tableEdges = model.edges.filter(edge => itemIds.has(`table-${edge.source}`) && itemIds.has(`table-${edge.target}`));
    // ELK places an edge's source left of its target. Relation edges run from the referencing ("n") table to the
    // referenced ("1") table, so they are laid out reversed to keep the "1" side on the left, as flow edges already do.
    const layoutReversed = (edge: LineageEdge) => edge.kind === 'relation';
    const edgeId = (edge: LineageEdge) => `${edge.kind}-${edge.source}-${edge.target}`;
    // Each end of an edge sits on the row of the first column pair it joins; ends whose column the card does not list
    // sit on the header.
    const ends = (edge: LineageEdge) => {
      const pair = edge.column_links?.[0];
      const source = { node: `table-${edge.source}`, column: pair?.source ?? null };
      const target = { node: `table-${edge.target}`, column: pair?.target ?? null };
      return layoutReversed(edge) ? { left: target, right: source } : { left: source, right: target };
    };
    const links: LineageLink[] = tableEdges.map(edge => {
      const { left, right } = ends(edge);
      return {
        id: edgeId(edge),
        source: left.node,
        target: right.node,
        sourceY: portY(contentByNode.get(left.node) as CardContent, left.column),
        targetY: portY(contentByNode.get(right.node) as CardContent, right.column),
      };
    });
    if (!lineageLoadedRef.current) {
      lineageLayoutRef.current = fromStoredLineage(model.lineage_canvas);
      savedLineageRef.current = JSON.stringify(toStoredLineage(lineageLayoutRef.current));
      lineageLoadedRef.current = true;
    }
    const saved = lineageLayoutRef.current;
    layoutLineageWithElk(lanes, items.map(item => ({ id: item.id, lane: item.lane, height: heightOf(item.id) })), links)
      .then(layout => {
        if (cancelled) return;
        // Cards the user moved start where they were left, the others where ELK put them. Cards are then settled from
        // the top down: one that would cover a card above it, or come closer than CARD_GAP under it, moves down. Cards
        // grow with the detail level while the stored positions stay, so the user's order holds at every level.
        const positions = new Map<string, Point>();
        const boxes: Box[] = [];
        const spaced = (box: Box) => ({ ...box, height: box.height + CARD_GAP });
        const starts = items
          .map(item => ({ item, start: saved.nodes.get(item.id) ?? layout.positions.get(item.id) ?? { x: 0, y: 0 } }))
          .sort((a, b) => a.start.y - b.start.y || a.start.x - b.start.x);
        for (const { item, start } of starts) {
          const box = { ...start, width: CARD_WIDTH, height: heightOf(item.id) };
          while (boxes.some(other => overlap(spaced(box), spaced(other)))) box.y += LINEAGE_SNAP;
          positions.set(item.id, { x: box.x, y: box.y });
          boxes.push(box);
        }
        const levelNames = new Map(lanes.map(lane => [lane.level, lane.key === UNCLASSIFIED_LANE ? null : `Cấp ${lane.level + 1}`]));
        const cardNodes: Node[] = items.map(item => ({
          id: item.id,
          type: 'modelTable',
          position: positions.get(item.id) ?? { x: 0, y: 0 },
          data: {
            ...tableData(item.datasetId),
            datasetId: item.datasetId,
            lane: item.lane,
            active: item.active,
            content: contentByNode.get(item.id) as CardContent,
            metrics: metricsByDataset.get(item.datasetId) ?? [],
            // Lets the first routes keep clear of the metrics shown beside the cards; drawing sets it from then on.
            metricsOpen: !hiddenMetrics.has(item.id),
          },
          className: item.datasetId === focusDatasetId ? 'is-focused' : undefined,
          deletable: false,
        }));
        // Lane bands and level headers are drawn around the cards as they lie (see shownNodes); these give their labels.
        const nextNodes: Node[] = [
          ...layout.levels.flatMap(level => {
            const label = levelNames.get(level.level);
            return label ? [{
              id: `level-${level.level}`,
              type: 'level',
              position: { x: level.left, y: 0 },
              style: { width: level.right - level.left },
              data: { label, count: layout.lanes.filter(lane => lane.level === level.level).length, level: level.level },
              draggable: false,
              selectable: false,
              deletable: false,
              zIndex: -1,
            }] : [];
          }),
          ...layout.lanes.map(lane => ({
            id: `lane-${lane.key}`,
            type: 'lane',
            position: { x: lane.x, y: lane.y },
            style: { width: lane.width, height: lane.height },
            data: { key: lane.key, level: lane.level, label: lane.label, hint: lane.hint, color: lane.color },
            dragHandle: '.sl-model-lane-label',
            selectable: false,
            deletable: false,
            zIndex: -1,
          })),
          ...cardNodes,
        ];
        // An edge keeps the shape the user gave it. Otherwise it follows ELK's route while both cards are where ELK put
        // them, and is routed around the cards once one of them moved.
        const obstacles = edgeObstacles(cardNodes);
        const autoGeometry = new Map<string, EdgeGeometry>();
        const geometryOf = (id: string, ends: [string, string], anchors: [EdgeAnchor, EdgeAnchor], reversed: boolean): EdgeGeometry => {
          const elkRoute = layout.routes.get(id);
          const route = elkRoute && reversed ? elkRoute.slice().reverse() : elkRoute;
          const unmoved = ends.every(nodeId => {
            const [now, elk] = [positions.get(nodeId), layout.positions.get(nodeId)];
            return now && elk && now.x === elk.x && now.y === elk.y;
          });
          const elkCoords = route && unmoved ? coordsFromRoute(route) : null;
          const auto = elkCoords
            ? { ...DEFAULT_GEOMETRY, coords: elkCoords }
            : routedGeometry(positions.get(ends[0]) as Point, positions.get(ends[1]) as Point, anchors, obstacles);
          autoGeometry.set(id, auto);
          return saved.edges.get(id) ?? auto;
        };
        const nextEdges: Edge[] = tableEdges.map(edge => {
          const id = edgeId(edge);
          const reversed = layoutReversed(edge);
          const { left, right } = ends(edge);
          const [sourceEnd, targetEnd] = reversed ? [right, left] : [left, right];
          const sideOf = (end: typeof left) => (end === left ? 'r' : 'l');
          const anchorOf = (end: typeof left): EdgeAnchor => ({
            y: portY(contentByNode.get(end.node) as CardContent, end.column),
            side: end === left ? 'right' : 'left',
          });
          const anchors: [EdgeAnchor, EdgeAnchor] = [anchorOf(sourceEnd), anchorOf(targetEnd)];
          const active = activeIds.has(`table-${edge.source}`) && activeIds.has(`table-${edge.target}`);
          // A user-chosen colour wins; edges outside the selected domains fade instead of turning grey.
          const stroke = edge.color ?? (active ? (edge.origin === 'manual' ? '#d97706' : 'var(--sl-accent)') : 'var(--sl-border)');
          // Crow's feet mark the "n" side of a relationship and bars the "1" side. Manual edges carry no cardinality and
          // keep a single arrow on their target.
          const manual = !edge.source_cardinality && !edge.target_cardinality;
          return {
            id,
            source: sourceEnd.node,
            target: targetEnd.node,
            sourceHandle: handleId(contentByNode.get(sourceEnd.node) as CardContent, sourceEnd.column, sideOf(sourceEnd)),
            targetHandle: handleId(contentByNode.get(targetEnd.node) as CardContent, targetEnd.column, sideOf(targetEnd)),
            type: 'routed',
            markerStart: cardinalityMarker(edge.source_cardinality, stroke),
            markerEnd: manual ? markerId('arrow', stroke) : cardinalityMarker(edge.target_cardinality, stroke),
            // Relations inside one level are dashed; flows between levels are solid.
            style: { stroke, strokeWidth: active ? 1.75 : 1.25, strokeDasharray: edge.kind === 'relation' ? '6 4' : undefined, opacity: active || !edge.color ? 1 : 0.4 },
            // A reversed route is turned back so its start stays at the edge's source and markers land correctly.
            data: {
              lineage: edge,
              geometry: geometryOf(id, [sourceEnd.node, targetEnd.node], anchors, reversed),
              label: edgeLabel(edge, reversed),
              muted: !active,
              flow: [left.node, right.node],
              anchors,
            },
            zIndex: active ? 2 : 1,
          };
        });
        autoGeometryRef.current = autoGeometry;
        setNodes(nextNodes);
        setEdges(nextEdges);
        window.requestAnimationFrame(() => { if (!cancelled) void fitCanvas(); });
      })
      .catch(reason => {
        if (!cancelled) setError(reason instanceof Error ? `Không dựng được sơ đồ lineage: ${reason.message}` : 'Không dựng được sơ đồ lineage.');
      });
    return () => { cancelled = true; };
  }, [model, mode, selectedDomainIds, datasets, dictionaries, domainCountByDataset, contentOf, metricsByDataset, lineageRevision]);

  // The header dataset picker highlights the dataset's cards and brings them into view.
  const previousFocusRef = useRef(focusDatasetId);
  useEffect(() => {
    if (previousFocusRef.current === focusDatasetId) return;
    previousFocusRef.current = focusDatasetId;
    const matches = (node: Node) => (node.data as { datasetId?: number }).datasetId === focusDatasetId;
    setNodes(current => current.map(node => node.type === 'modelTable' || node.type === 'tableTile' ? { ...node, className: matches(node) ? 'is-focused' : undefined } : node));
    const focused = nodes.filter(matches).map(node => ({ id: node.id }));
    if (focused.length > 0) void fitView({ nodes: focused, duration: 350, maxZoom: 1.1, padding: 0.4 });
  }, [focusDatasetId]);

  // Business-view dragging snaps domains and tiles to the canvas grid; a dragged domain carries the tables only it holds.
  const snapPosition = useCallback((node: Node | undefined, position: Point) => {
    if (node?.type === 'domainGroup') {
      return { x: Math.round(position.x / GRID_CELL) * GRID_CELL, y: Math.round(position.y / GRID_CELL) * GRID_CELL };
    }
    if (node?.type === 'modelTable') return { x: snapToUnit(position.x, LINEAGE_SNAP), y: snapToUnit(position.y, LINEAGE_SNAP) };
    return node?.type === 'tableTile' ? tilePosition(tileCell(position)) : position;
  }, []);
  const domainShift = (key: string, position: Point): Cell | null => {
    const domain = gridRef.current.domains.find(item => item.key === key);
    if (!domain) return null;
    const { origin } = domainFrame(domain);
    return { col: Math.round(position.x / GRID_CELL) - origin.col, row: Math.round(position.y / GRID_CELL) - origin.row };
  };
  // Routes again, around the cards at their current positions or at `moves`, every lineage edge `pick` chooses, and
  // returns the IDs of the edges it routed.
  const rerouteEdges = useCallback((moves: Map<string, Point>, pick: (edge: Edge, crosses: (boxes: Box[]) => boolean) => boolean) => {
    const cards = getNodes().filter(isCard).map(node => (moves.has(node.id) ? { ...node, position: moves.get(node.id) as Point } : node));
    const positionOf = new Map(cards.map(node => [node.id, node.position]));
    const obstacles = edgeObstacles(cards);
    const routed = new Set<string>();
    setEdges(current => current.map(edge => {
      const data = edge.data as RoutedEdgeData | undefined;
      const [source, target] = [positionOf.get(edge.source), positionOf.get(edge.target)];
      if (!data?.anchors || !source || !target) return edge;
      if (!pick(edge, boxes => edgeCrosses(data.geometry, source, target, data.anchors, boxes))) return edge;
      routed.add(edge.id);
      const geometry = routedGeometry(source, target, data.anchors, obstacles);
      autoGeometryRef.current.set(edge.id, geometry);
      return { ...edge, data: { ...data, geometry } };
    }));
    return routed;
  }, [getNodes, setEdges]);

  // While lineage cards are dragged, their edges are routed around the other cards once per frame.
  const dragFrameRef = useRef<number | null>(null);
  const dragMovesRef = useRef(new Map<string, Point>());
  const edgesBeforeDragRef = useRef<Edge[] | null>(null);
  // The lane band being dragged by its header, and where it started.
  const laneDragRef = useRef<{ id: string; start: Point } | null>(null);
  const followDrag = useCallback(() => {
    if (dragFrameRef.current !== null) return;
    dragFrameRef.current = window.requestAnimationFrame(() => {
      dragFrameRef.current = null;
      const moving = new Set(lineageDragRef.current.keys());
      if (moving.size > 0) rerouteEdges(dragMovesRef.current, edge => moving.has(edge.source) || moving.has(edge.target));
    });
  }, [rerouteEdges]);

  const handleNodesChange = useCallback((changes: NodeChange<Node>[]) => {
    const next: NodeChange<Node>[] = [];
    for (const change of changes) {
      if (change.type !== 'position' || !change.position) {
        next.push(change);
        continue;
      }
      const position = snapPosition(getNode(change.id), change.position);
      next.push({ ...change, position });
      if (mode === 'lineage' && lineageDragRef.current.has(change.id)) {
        dragMovesRef.current.set(change.id, position);
        followDrag();
      }
      // A dragged lane band carries its cards by the same snapped offset; the band itself is drawn around them.
      const laneDrag = laneDragRef.current;
      if (mode === 'lineage' && laneDrag?.id === change.id) {
        const shift = { x: snapToUnit(position.x - laneDrag.start.x, LINEAGE_SNAP), y: snapToUnit(position.y - laneDrag.start.y, LINEAGE_SNAP) };
        for (const [id, start] of lineageDragRef.current) {
          const moved = { x: start.x + shift.x, y: start.y + shift.y };
          next.push({ id, type: 'position', position: moved });
          dragMovesRef.current.set(id, moved);
        }
        followDrag();
      }
      const followers = followersRef.current;
      const shift = followers?.key === change.id ? domainShift(change.id, position) : null;
      if (!followers || !shift) continue;
      for (const id of followers.ids) {
        const cell = gridRef.current.tables.get(id);
        if (cell) next.push({ id: tileId(id), type: 'position', position: tilePosition(shiftCell(cell, shift)) });
      }
    }
    onNodesChange(next);
  }, [onNodesChange, snapPosition, getNode, mode, followDrag]);
  const handleDragStart = useCallback((dragged: Node[]) => {
    if (mode === 'lineage') {
      // Lineage cards return here, with their edges as they were, when the drop is refused. A dragged lane band moves
      // all its cards.
      const lane = dragged.find(node => node.type === 'lane');
      const laneKey = lane ? (lane.data as LaneData).key : null;
      const moving = getNodes().filter(node => isCard(node) && (dragged.some(item => item.id === node.id) || (node.data as LineageCardData).lane === laneKey));
      lineageDragRef.current = new Map(moving.map(node => [node.id, node.position]));
      laneDragRef.current = lane ? { id: lane.id, start: lane.position } : null;
      dragMovesRef.current = new Map();
      edgesBeforeDragRef.current = getEdges();
      return;
    }
    const domain = dragged.find(node => node.type === 'domainGroup');
    followersRef.current = domain ? { key: domain.id, ids: ownTables(gridRef.current, domain.id) } : null;
  }, [mode, getEdges, getNodes]);
  const handleDragStop = useCallback((dragged: Node[]) => {
    if (mode === 'lineage') {
      const starts = lineageDragRef.current;
      lineageDragRef.current = new Map();
      laneDragRef.current = null;
      if (dragFrameRef.current !== null) window.cancelAnimationFrame(dragFrameRef.current);
      dragFrameRef.current = null;
      const moves = new Map([...starts].map(([id, start]) => [id, dragMovesRef.current.get(id) ?? start]));
      const placed = (positions: Map<string, Point>) => getNodes().filter(isCard).map(node => (
        positions.has(node.id) ? { ...node, position: positions.get(node.id) as Point } : node
      ));
      const after = placed(moves);
      const movedBoxes = after.filter(node => moves.has(node.id)).map(node => cardFootprint(node));
      // A card may not land on another card, nor stretch its lane band over another band.
      const stacked = after.some(node => !moves.has(node.id) && movedBoxes.some(box => overlap(box, cardFootprint(node))));
      const clashesBefore = clashingBands(laneBands(placed(starts)));
      const clashes = [...clashingBands(laneBands(after))].some(pair => !clashesBefore.has(pair));
      if (stacked || clashes) {
        setNodes(current => current.map(node => (starts.has(node.id) ? { ...node, position: starts.get(node.id) as Point } : node)));
        if (edgesBeforeDragRef.current) setEdges(edgesBeforeDragRef.current);
        edgesBeforeDragRef.current = null;
        return;
      }
      edgesBeforeDragRef.current = null;
      for (const [id, position] of moves) lineageLayoutRef.current.nodes.set(id, position);
      // The moved cards' edges, and every edge they now lie across, are routed around the cards; the shape a user gave
      // such an edge no longer fits, so it is dropped.
      const routed = rerouteEdges(moves, (edge, crosses) => moves.has(edge.source) || moves.has(edge.target) || crosses(movedBoxes));
      for (const id of routed) lineageLayoutRef.current.edges.delete(id);
      saveLineage();
      return;
    }
    const before = gridRef.current;
    let domains = before.domains;
    const tables = new Map(before.tables);
    for (const node of dragged) {
      const position = snapPosition(node, node.position);
      if (node.type === 'domainGroup') {
        const shift = domainShift(node.id, position);
        if (!shift) continue;
        domains = domains.map(domain => (domain.key === node.id
          ? { ...domain, cells: domain.cells.map(cell => shiftCell(cell, shift)), header: shiftCell(domain.header, shift) }
          : domain));
        const followers = followersRef.current?.key === node.id ? followersRef.current.ids : [];
        for (const id of followers) tables.set(id, shiftCell(before.tables.get(id) as Cell, shift));
      } else if (node.type === 'tableTile') {
        tables.set((node.data as { datasetId: number }).datasetId, tileCell(position));
      }
    }
    followersRef.current = null;
    settleGrid({ domains, tables }, before);
  }, [mode, snapPosition, settleGrid, getNodes, setNodes, setEdges, saveLineage, rerouteEdges]);

  const datasetIdOf = (nodeId: string | null | undefined) => (nodeId?.startsWith('table-') ? Number(nodeId.slice('table-'.length)) : null);

  const addEdge = async (sourceNode: string, targetNode: string) => {
    const source = datasetIdOf(sourceNode);
    const target = datasetIdOf(targetNode);
    if (source === null || target === null || source === target) return;
    try {
      await requestJson(semanticLayerApi.lineageEdges, 'POST', { source, target, kind: 'flow' });
      await loadModel();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không thêm được cạnh lineage.');
    }
  };

  const selectedEdge = model?.edges.find(edge => `${edge.kind}-${edge.source}-${edge.target}` === selectedEdgeKey) ?? null;
  const selectedFlowEdge = edges.find(edge => edge.id === selectedEdgeKey) ?? null;
  const selectedGeometry = (selectedFlowEdge?.data as RoutedEdgeData | undefined)?.geometry ?? null;
  const nodeLabel = (nodeId: string) => {
    const data = nodes.find(node => node.id === nodeId)?.data as { tableName?: string; title?: string } | undefined;
    return data?.tableName ?? data?.title ?? nodeId;
  };
  const setEdgeStyle = (style: EdgeStyle) => {
    if (selectedFlowEdge && selectedGeometry) updateEdgeGeometry(selectedFlowEdge.id, withStyle(selectedGeometry, style), true);
  };
  const resetEdgeShape = () => {
    if (!selectedFlowEdge) return;
    lineageLayoutRef.current.edges.delete(selectedFlowEdge.id);
    const geometry = autoGeometryRef.current.get(selectedFlowEdge.id) ?? DEFAULT_GEOMETRY;
    setEdges(current => current.map(edge => (edge.id === selectedFlowEdge.id ? { ...edge, data: { ...edge.data, geometry } } : edge)));
    saveLineage();
  };
  // Drops every card position and edge shape the user set, and lays the lineage out afresh.
  const resetLineageLayout = () => {
    if (!window.confirm('Bỏ mọi vị trí bảng và hình dạng cạnh đã chỉnh tay, sắp xếp lại lineage tự động?')) return;
    lineageLayoutRef.current = { nodes: new Map(), edges: new Map() };
    saveLineage();
    setLineageRevision(revision => revision + 1);
  };
  useEffect(() => {
    if (mode === 'lineage') return;
    setSelectedEdgeKey(null);
    setHoveredEdgeId(null);
    setTraceNodeId(null);
  }, [mode]);

  // A traced card lights its upstream and downstream tables and the edges between them; the rest of the lineage fades.
  const traced = useMemo(
    () => (mode === 'lineage' && traceNodeId && nodes.some(node => node.id === traceNodeId) ? tracedLineage(traceNodeId, edges) : null),
    [mode, traceNodeId, nodes, edges],
  );
  const toggleMetrics = useCallback((nodeId: string) => {
    setHiddenMetrics(current => {
      const next = new Set(current);
      if (!next.delete(nodeId)) next.add(nodeId);
      return next;
    });
  }, []);
  // Cards as drawn: each knows whether its metrics stand beside it. Metric nodes and their arrows follow the cards.
  const cards = useMemo(() => nodes.filter(isCard).map(node => ({
    ...node,
    data: { ...node.data, metricsOpen: !hiddenMetrics.has(node.id), onToggleMetrics: toggleMetrics },
  })), [nodes, hiddenMetrics, toggleMetrics]);
  const metricNodes = useMemo(() => cards.flatMap(card => {
    const data = card.data as LineageCardData;
    if (!data.metricsOpen) return [];
    const dimmed = traced ? !traced.nodes.has(card.id) : false;
    return metricSlots(data.content, data.metrics).map(({ metric, y, sources, lane }): Node => ({
      id: `metric-${metric.id}`,
      type: 'lineageMetric',
      position: { x: card.position.x + METRIC_LEFT, y: card.position.y + y },
      // These nodes are made afresh on every draw, so they carry their fixed size: React Flow hides a node it has not
      // measured yet, which made them flicker and vanish on hover.
      width: METRIC_WIDTH,
      height: METRIC_HEIGHT,
      measured: { width: METRIC_WIDTH, height: METRIC_HEIGHT },
      data: {
        metric,
        card: card.id,
        lane: data.lane,
        dimmed,
        arrow: {
          start: card.position.x + CARD_WIDTH,
          sources: sources.map(source => card.position.y + source),
          lane: card.position.x + lane,
          end: { x: card.position.x + METRIC_LEFT, y: card.position.y + y + METRIC_HEIGHT / 2 },
        },
      },
      draggable: false,
      selectable: false,
      deletable: false,
    }));
  }), [cards, traced]);
  // Lane bands follow their cards, so a dragged card stretches its own band, which turns red where it would cover
  // another band; level headers span the bands of their level, above the topmost band.
  const shownNodes = useMemo(() => {
    if (mode !== 'lineage') return nodes;
    const bands = laneBands(cards);
    const clashing = new Set([...clashingBands(bands)].flatMap(pair => pair.split('|')));
    const laneLevels = new Map(nodes.filter(node => node.type === 'lane').map(node => [(node.data as LaneData).key, (node.data as LaneData).level]));
    const top = Math.min(...[...bands.values()].map(band => band.y)) - LEVEL_HEADER;
    const cardById = new Map(cards.map(card => [card.id, card]));
    return [...nodes.map(node => {
      if (node.type === 'lane') {
        const band = bands.get((node.data as LaneData).key);
        if (!band) return { ...node, hidden: true };
        return {
          ...node,
          hidden: false,
          position: { x: band.x, y: band.y },
          style: { ...node.style, width: band.width, height: band.height },
          className: clashing.has((node.data as LaneData).key) ? 'is-clashing' : undefined,
        };
      }
      if (node.type === 'level') {
        const spans = [...bands].filter(([key]) => laneLevels.get(key) === (node.data as LevelData).level).map(([, band]) => band);
        if (spans.length === 0) return { ...node, hidden: true };
        const left = Math.min(...spans.map(band => band.x));
        const right = Math.max(...spans.map(band => band.x + band.width));
        return { ...node, hidden: false, position: { x: left, y: top }, style: { ...node.style, width: right - left } };
      }
      const card = cardById.get(node.id);
      if (!card) return node;
      if (!traced) return card;
      return { ...card, className: [card.className, traced.nodes.has(card.id) ? 'is-traced' : 'is-dimmed'].filter(Boolean).join(' ') };
    }), ...metricNodes];
  }, [mode, nodes, cards, metricNodes, traced]);
  const shownEdges = useMemo(() => {
    const lineage = traced ? edges.map(edge => ({ ...edge, className: traced.edges.has(edge.id) ? 'is-traced' : 'is-dimmed' })) : edges;
    if (mode !== 'lineage') return lineage;
    // One arrow to each metric, drawn from the shape its slot gives it (see MetricArrow).
    const arrows = metricNodes.map((node): Edge => {
      const data = node.data as MetricData;
      return {
        id: `metric-edge-${data.metric.id}`,
        source: data.card,
        target: node.id,
        sourceHandle: 'metrics',
        targetHandle: 'l',
        type: 'metricArrow',
        markerEnd: markerId('arrow', METRIC_EDGE_COLOR),
        style: { stroke: METRIC_EDGE_COLOR },
        data: { ...data.arrow, card: data.card },
        className: data.dimmed ? 'is-dimmed' : undefined,
        selectable: false,
        deletable: false,
        zIndex: 1,
      };
    });
    return [...lineage, ...arrows];
  }, [mode, edges, traced, metricNodes]);
  const markerStrokes = useMemo(() => [...new Set(shownEdges.map(edge => String(edge.style?.stroke ?? '')).filter(Boolean))], [shownEdges]);
  const metricFocus = useMemo(() => {
    const arrowTarget = hoveredEdgeId?.startsWith('metric-edge-') ? shownEdges.find(edge => edge.id === hoveredEdgeId)?.target : undefined;
    const node = metricNodes.find(item => item.id === (hoveredMetricId ?? arrowTarget));
    if (!node) return null;
    const data = node.data as MetricData;
    return { metricNodeId: node.id, card: data.card, roles: new Map((data.metric.columns ?? []).map(column => [column.name, column.role])) };
  }, [hoveredEdgeId, hoveredMetricId, shownEdges, metricNodes]);
  const metricFocusValue = useMemo(() => ({ focus: metricFocus, hover: setHoveredMetricId }), [metricFocus]);
  // Metrics shown beside a card may now lie across other edges; once drawn, those edges are routed around them.
  const shownMetricsRef = useRef(hiddenMetrics);
  useEffect(() => {
    if (shownMetricsRef.current === hiddenMetrics) return undefined;
    shownMetricsRef.current = hiddenMetrics;
    const frame = window.requestAnimationFrame(() => {
      const columns = getNodes().filter(isCard).map(node => metricBox(node)).filter((box): box is Box => box !== null);
      if (columns.length > 0) rerouteEdges(new Map(), (_, crosses) => crosses(columns));
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hiddenMetrics, getNodes, rerouteEdges]);

  const setEdgeColor = async (edge: LineageEdge, color: string | null) => {
    try {
      await requestJson(semanticLayerApi.lineageEdgeColor, 'PUT', { source: edge.source, target: edge.target, kind: edge.kind, color });
      await loadModel();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không đổi được màu cạnh.');
    }
  };

  const removeEdges = async (removed: Edge[]) => {
    const byKey = new Map<string, LineageEdge>();
    for (const edge of removed) {
      const lineage = (edge.data as { lineage?: LineageEdge } | undefined)?.lineage;
      if (lineage) byKey.set(`${lineage.kind}-${lineage.source}-${lineage.target}`, lineage);
    }
    const lineage = [...byKey.values()];
    try {
      await Promise.all(lineage.map(edge => requestJson(semanticLayerApi.lineageEdges, 'DELETE', { source: edge.source, target: edge.target, kind: edge.kind })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không xóa được cạnh lineage.');
    }
    await loadModel();
  };

  const selectedDomains = domains.filter(domain => selectedDomainIds.includes(domain.id));
  const assignedIds = new Set(domains.flatMap(domain => domain.dataset_ids));
  const unassignedCount = baseDatasets.filter(dataset => !assignedIds.has(dataset.id)).length;
  const aggregateCount = datasets.filter(dataset => model?.classifications[String(dataset.id)]?.dataset_type === 'aggregate').length;
  const unclassifiedCount = datasets.length - baseDatasets.length - aggregateCount;

  return (
    <div className={`sl-model-workspace${panelCollapsed ? ' is-panel-collapsed' : ''}`}>
      <aside className="sl-model-panel" aria-label="Nghiệp vụ">
        <div className="sl-model-panel-heading">
          {panelCollapsed ? (
            <Button size="icon-sm" variant="ghost" aria-label="Mở rộng thanh Nghiệp vụ" title="Mở rộng thanh Nghiệp vụ" onClick={() => setPanelCollapsed(false)}>
              <ChevronRight />
            </Button>
          ) : (
            <>
              <span><Layers3 /> Nghiệp vụ <Badge variant="secondary">{domains.length}</Badge></span>
              <div className="sl-model-panel-actions">
                <Button size="sm" variant="outline" onClick={() => editDomain(null)}><Plus data-icon="inline-start" /> Thêm</Button>
                <Button size="icon-sm" variant="ghost" aria-label="Thu gọn thanh Nghiệp vụ" title="Thu gọn thanh Nghiệp vụ" onClick={() => setPanelCollapsed(true)}>
                  <ChevronLeft />
                </Button>
              </div>
            </>
          )}
        </div>
        {!panelCollapsed ? <>
        <p className="sl-palette-hint">Chọn một hoặc nhiều nghiệp vụ để xem dữ liệu đi qua các bảng.</p>
        <div className="sl-model-domain-list">
          {domains.map(domain => (
            <div key={domain.id} className={`sl-model-domain${selectedDomainIds.includes(domain.id) ? ' is-selected' : ''}`}>
              <Checkbox aria-label={`Chọn ${domain.name}`} checked={selectedDomainIds.includes(domain.id)} onCheckedChange={() => toggleDomain(domain.id)} />
              <span className="sl-model-domain-dot" style={{ background: domain.color || UNASSIGNED_COLOR }} />
              <button type="button" className="sl-model-domain-name" title={domain.description ?? domain.name} onClick={() => toggleDomain(domain.id)}>{domain.name}</button>
              <span className="sl-model-domain-count">{domain.dataset_ids.filter(id => baseIds.has(id)).length}</span>
              <Button size="icon-xs" variant="ghost" aria-label={`Sửa ${domain.name}`} onClick={() => editDomain(domain)}><Pencil /></Button>
            </div>
          ))}
          {!loading && domains.length === 0 ? <p className="sl-empty">Chưa có nghiệp vụ. Bấm Thêm để gom các bảng theo nghiệp vụ.</p> : null}
        </div>
        {unassignedCount > 0 ? <p className="sl-model-unassigned">{unassignedCount} bảng base chưa thuộc nghiệp vụ nào</p> : null}
        {model && (aggregateCount > 0 || unclassifiedCount > 0) ? (
          <p className="sl-model-unassigned">
            View nghiệp vụ chỉ hiện bảng Base. Đang ẩn
            {aggregateCount > 0 ? ` ${aggregateCount} bảng Aggregate` : ''}
            {aggregateCount > 0 && unclassifiedCount > 0 ? ' và' : ''}
            {unclassifiedCount > 0 ? ` ${unclassifiedCount} bảng chưa phân loại Classification trong Data Dictionary` : ''}.
          </p>
        ) : null}
        <div className="sl-model-panel-footer">
          <Button className="w-full" variant={mode === 'lineage' ? 'outline' : 'default'} onClick={() => setMode(mode === 'lineage' ? 'business' : 'lineage')}>
            {mode === 'lineage' ? <Network data-icon="inline-start" /> : <GitBranch data-icon="inline-start" />}
            {mode === 'lineage' ? 'Quay lại view nghiệp vụ' : selectedDomains.length > 0 ? `Xem lineage (${selectedDomains.length} nghiệp vụ)` : 'Xem lineage toàn bộ'}
          </Button>
        </div>
        </> : null}
      </aside>

      <section className={`sl-canvas sl-model-canvas${mode === 'lineage' && zoomedOut ? ' is-zoomed-out' : ''}`} aria-label="Canvas semantic layer">
        <EdgeMarkers strokes={markerStrokes} />
        <EdgeEditingContext.Provider value={edgeEditing}>
        <MetricFocusContext.Provider value={metricFocusValue}>
        <ReactFlow
          nodes={shownNodes}
          edges={shownEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={handleNodesChange}
          onNodeDragStart={(_, __, dragged) => handleDragStart(dragged)}
          onNodeDragStop={(_, __, dragged) => handleDragStop(dragged)}
          onEdgesChange={onEdgesChange}
          connectionMode={ConnectionMode.Loose}
          isValidConnection={connection => datasetIdOf(connection.source) !== null && datasetIdOf(connection.target) !== null && connection.source !== connection.target}
          onConnect={connection => void addEdge(connection.source, connection.target)}
          onBeforeDelete={async ({ nodes: deletedNodes, edges: deletedEdges }) => (
            deletedNodes.length === 0
            && deletedEdges.length > 0
            && window.confirm('Xóa cạnh lineage đã chọn? Cạnh suy ra từ Data Dictionary sẽ được ẩn.')
          )}
          onEdgesDelete={removed => void removeEdges(removed)}
          onEdgeClick={(_, clicked) => setSelectedEdgeKey(clicked.id)}
          onEdgeMouseEnter={(_, hovered) => setHoveredEdgeId(hovered.id)}
          onEdgeMouseLeave={() => setHoveredEdgeId(null)}
          onNodeClick={(_, clicked) => {
            if (mode === 'lineage' && clicked.type === 'modelTable') setTraceNodeId(current => (current === clicked.id ? null : clicked.id));
          }}
          onPaneClick={() => {
            setSelectedEdgeKey(null);
            setTraceNodeId(null);
          }}
          deleteKeyCode={mode === 'lineage' ? ['Backspace', 'Delete'] : null}
          colorMode={themeMode}
          minZoom={0.1}
          maxZoom={2}
          fitView
          aria-label="Canvas semantic layer"
        >
          {mode === 'lineage'
            ? <Background variant={BackgroundVariant.Dots} gap={24} size={1.4} color="var(--sl-grid-line)" />
            : <Background variant={BackgroundVariant.Lines} gap={GRID_CELL} lineWidth={1} color="var(--sl-grid-line)" />}
          <Controls position="bottom-right" showInteractive={false} />
          {mode === 'lineage' ? (
            // The lineage tools stand in a column at the top right; a selected edge's panel opens under them.
            <Panel position="top-right" className="sl-lineage-side">
              <div className="sl-lineage-tools">
                <div className="sl-lineage-detail" role="group" aria-label="Mức chi tiết của bảng">
                  {DETAIL_LEVELS.map(([level, name]) => (
                    <Button key={level} size="sm" variant={detailLevel === level ? 'default' : 'ghost'} aria-pressed={detailLevel === level} onClick={() => chooseDetailLevel(level)}>
                      {name}
                    </Button>
                  ))}
                </div>
                <Button size="sm" variant="outline" onClick={resetLineageLayout}><RotateCcw data-icon="inline-start" /> Sắp xếp lại tự động</Button>
              </div>
              {selectedFlowEdge && selectedGeometry ? (
                <div className="sl-edge-panel">
                  <div className="sl-edge-panel-title">
                    <span>{selectedEdge?.kind === 'relation' ? 'Quan hệ' : 'Luồng dữ liệu'}</span>
                    <strong title={`${nodeLabel(selectedFlowEdge.source)} → ${nodeLabel(selectedFlowEdge.target)}`}>
                      {nodeLabel(selectedFlowEdge.source)} → {nodeLabel(selectedFlowEdge.target)}
                    </strong>
                  </div>
                  <div className="sl-edge-panel-styles" role="group" aria-label="Kiểu cạnh">
                    {EDGE_STYLES.map(([style, name]) => (
                      <Button key={style} size="sm" variant={selectedGeometry.style === style ? 'default' : 'outline'} aria-pressed={selectedGeometry.style === style} onClick={() => setEdgeStyle(style)}>
                        {name}
                      </Button>
                    ))}
                  </div>
                  <p className="sl-edge-panel-hint">
                    {selectedGeometry.style === 'orthogonal'
                      ? 'Kéo tay nắm trên từng đoạn để chỉnh đường.'
                      : 'Kéo điểm mờ giữa các đoạn để thêm điểm uốn; nhấp đúp điểm uốn để bỏ.'}
                    {selectedEdge && ' Kéo nhãn để dời, nhấp đúp nhãn để đưa về giữa.'}
                  </p>
                  {selectedEdge ? (
                    <div className="sl-edge-panel-colors" role="group" aria-label="Màu cạnh">
                      {DOMAIN_COLORS.map(color => (
                        <button
                          key={color}
                          type="button"
                          className="sl-color-swatch"
                          aria-label={`Màu ${color}`}
                          aria-pressed={selectedEdge.color === color}
                          style={{ background: color }}
                          onClick={() => void setEdgeColor(selectedEdge, color)}
                        />
                      ))}
                    </div>
                  ) : null}
                  <div className="sl-edge-panel-actions">
                    <Button size="sm" variant="outline" disabled={!lineageLayoutRef.current.edges.has(selectedFlowEdge.id)} onClick={resetEdgeShape}>Đặt lại đường</Button>
                    {selectedEdge ? (
                      <Button size="sm" variant="outline" disabled={!selectedEdge.color} onClick={() => void setEdgeColor(selectedEdge, null)}>Màu mặc định</Button>
                    ) : null}
                  </div>
                  {selectedEdge ? (
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => {
                        if (!window.confirm('Xóa cạnh này? Cạnh suy ra từ Data Dictionary sẽ được ẩn.')) return;
                        setSelectedEdgeKey(null);
                        void removeEdges([{ id: selectedEdgeKey ?? '', source: '', target: '', data: { lineage: selectedEdge } }]);
                      }}
                    >
                      Xóa cạnh
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </Panel>
          ) : null}
          {mode === 'business' && selectedDomains.length > 0 ? (
            <Panel position="bottom-center" className="sl-model-selection">
              <span>Đã chọn {selectedDomains.length} nghiệp vụ</span>
              <Button size="sm" onClick={() => setMode('lineage')}><GitBranch data-icon="inline-start" /> Xem data lineage</Button>
              <Button size="sm" variant="ghost" onClick={() => setSelectedDomainIds([])}>Bỏ chọn</Button>
            </Panel>
          ) : null}
        </ReactFlow>
        </MetricFocusContext.Provider>
        </EdgeEditingContext.Provider>
        {loading && !model ? <div className="sl-model-overlay"><LoaderCircle className="sl-spin" /> Đang tải mô hình nghiệp vụ…</div> : null}
        {error ? (
          <div className="sl-model-error" role="alert">
            <span>{error}</span>
            <Button size="xs" variant="outline" onClick={() => void loadModel()}><RotateCcw data-icon="inline-start" /> Thử lại</Button>
          </div>
        ) : null}
      </section>

      <Dialog open={pending !== null} onOpenChange={open => { if (!open && !savingMembers) cancelPending(); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {pending?.changes.every(change => change.add) ? 'Thêm bảng vào nghiệp vụ?' : pending?.changes.every(change => !change.add) ? 'Bỏ bảng khỏi nghiệp vụ?' : 'Cập nhật nghiệp vụ?'}
            </DialogTitle>
            <DialogDescription>Một bảng có thể thuộc nhiều nghiệp vụ. Chọn Hủy để đưa canvas về như trước.</DialogDescription>
          </DialogHeader>
          <ul className="sl-member-changes">
            {pending?.changes.map(change => (
              <li key={`${change.domain.id}-${change.datasetId}`} className={change.add ? 'is-add' : 'is-remove'}>
                {change.add ? 'Thêm bảng ' : 'Bỏ bảng '}
                <strong>{tableData(change.datasetId).title}</strong>
                {change.add ? ' vào nghiệp vụ ' : ' khỏi nghiệp vụ '}
                <strong style={{ color: change.domain.color || undefined }}>{change.domain.name}</strong>
              </li>
            ))}
          </ul>
          <DialogFooter>
            <Button variant="outline" disabled={savingMembers} onClick={cancelPending}>Hủy</Button>
            <Button disabled={savingMembers} onClick={() => void confirmPending()}>
              {savingMembers ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null}
              Đồng ý
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DomainDialog
        open={dialog.open}
        domain={dialog.domain}
        groups={groupDatasetsByLayer(baseDatasets, layers, layerIdOf)}
        usedColors={domains.map(domain => domain.color ?? '')}
        onOpenChange={open => setDialog(current => ({ ...current, open }))}
        onSaved={() => void loadModel()}
      />
    </div>
  );
}

export function BusinessCanvas(props: BusinessCanvasProps) {
  return <ReactFlowProvider><BusinessFlow {...props} /></ReactFlowProvider>;
}

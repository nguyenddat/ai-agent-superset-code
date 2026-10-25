import type { ElkNode, ElkPort } from 'elkjs/lib/elk-api';
import { CARD_WIDTH } from './lineageCard';
import type { Lane, Point, Size } from './modelLayout';

/** A table card to lay out: its lane (data layer) and its height, which depends on the columns it lists. */
export type LineageCardBox = { id: string; lane: string; height: number };

/**
 * A link between two cards, from the card drawn on the left to the one on the right. `sourceY` and `targetY` are the
 * heights on each card where the link leaves and enters it: the row of the column it joins.
 */
export type LineageLink = { id: string; source: string; target: string; sourceY: number; targetY: number };

export type ElkLineageLayout = {
  /** Top-left corner of each card. */
  positions: Map<string, Point>;
  /** Orthogonal route of each link (start, bends, end), keyed by link id. */
  routes: Map<string, Point[]>;
  /** The band of each lane that holds cards, around its cards and its header. */
  lanes: Array<Lane & Point & Size>;
  /** Horizontal extent of each level in use, for the level headers above the bands. */
  levels: Array<{ level: number; left: number; right: number }>;
  height: number;
};

/** Room at the top of a lane band for its header. */
export const LANE_HEADER = 56;
/** Room between a lane band's other sides and its cards. */
export const LANE_INSET = 16;
/** Room above the bands for the level headers. */
export const LEVEL_HEADER = 40;

let elkInstance: Promise<{ layout: (graph: ElkNode) => Promise<ElkNode> }> | null = null;

// elkjs is large, so it is loaded on first use as its own chunk rather than with the extension entry.
function loadElk() {
  elkInstance ??= import('elkjs/lib/elk.bundled.js').then(module => new module.default());
  return elkInstance;
}

const LAYOUT_OPTIONS = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.edgeRouting': 'ORTHOGONAL',
  // Lanes are nested graphs laid out together with the root, so edges run between cards of different lanes, and
  // every coordinate comes back relative to the root.
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.json.shapeCoords': 'ROOT',
  'elk.json.edgeCoords': 'ROOT',
  'elk.partitioning.activate': 'true',
  // Partitions only order nodes within one connected component; keeping the graph whole makes unconnected
  // tables still sit in their own level instead of being packed into the first column.
  'elk.separateConnectedComponents': 'false',
  'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
  'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
  'elk.spacing.nodeNode': '32',
  'elk.spacing.edgeNode': '24',
  'elk.spacing.edgeEdge': '14',
  'elk.layered.spacing.nodeNodeBetweenLayers': '112',
  'elk.layered.spacing.edgeNodeBetweenLayers': '28',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '14',
  // Lanes of one level keep the layers' order from top to bottom unless that costs many crossings.
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.layered.considerModelOrder.crossingCounterNodeInfluence': '0.5',
};

const LANE_PADDING = `[top=${LANE_HEADER},left=${LANE_INSET},bottom=${LANE_INSET},right=${LANE_INSET}]`;

/**
 * Lays out the lineage left to right with ELK Layered (Sugiyama). Each lane is a group of its cards, and the lane's
 * level is its ELK partition: levels keep their flow order from left to right, and lanes of one level stack in one
 * column. Within that, ELK orders cards to reduce crossings and routes edges orthogonally around them. Every column
 * an edge joins is a port fixed at its row, so ELK orders and routes the edges by the rows they meet instead of
 * crossing them on the card.
 */
export async function layoutLineageWithElk(laneDefinitions: Lane[], cards: LineageCardBox[], links: LineageLink[]): Promise<ElkLineageLayout> {
  // Links that meet a card at the same row and side share one port.
  const ports = new Map<string, Map<string, ElkPort>>(cards.map(card => [card.id, new Map()]));
  const portOf = (cardId: string, y: number, side: 'EAST' | 'WEST') => {
    const id = `${cardId}:${side}:${y}`;
    ports.get(cardId)?.set(id, {
      id,
      x: side === 'EAST' ? CARD_WIDTH : 0,
      y,
      width: 0,
      height: 0,
      layoutOptions: { 'elk.port.side': side },
    });
    return id;
  };
  const edges = links.map(link => ({
    id: link.id,
    sources: [portOf(link.source, link.sourceY, 'EAST')],
    targets: [portOf(link.target, link.targetY, 'WEST')],
  }));
  const usedLanes = laneDefinitions.filter(lane => cards.some(card => card.lane === lane.key));

  const elk = await loadElk();
  const graph = await elk.layout({
    id: 'lineage',
    layoutOptions: LAYOUT_OPTIONS,
    children: usedLanes.map(lane => ({
      id: `lane:${lane.key}`,
      layoutOptions: { 'elk.partitioning.partition': String(lane.level), 'elk.padding': LANE_PADDING },
      children: cards.filter(card => card.lane === lane.key).map(card => ({
        id: card.id,
        width: CARD_WIDTH,
        height: card.height,
        ports: [...(ports.get(card.id)?.values() ?? [])],
        layoutOptions: { 'elk.portConstraints': 'FIXED_POS' },
      })),
    })),
    edges,
  });

  const place = (point: { x?: number; y?: number }): Point => ({ x: Math.round(point.x ?? 0), y: Math.round(point.y ?? 0) + LEVEL_HEADER });
  const positions = new Map<string, Point>();
  const lanes: ElkLineageLayout['lanes'] = [];
  for (const group of graph.children ?? []) {
    const lane = usedLanes.find(item => `lane:${item.key}` === group.id);
    if (lane) lanes.push({ ...lane, ...place(group), width: Math.round(group.width ?? 0), height: Math.round(group.height ?? 0) });
    for (const child of group.children ?? []) positions.set(child.id, place(child));
  }
  const routes = new Map<string, Point[]>();
  for (const edge of graph.edges ?? []) {
    const section = edge.sections?.[0];
    if (section) routes.set(edge.id, [section.startPoint, ...(section.bendPoints ?? []), section.endPoint].map(place));
  }

  const levels: ElkLineageLayout['levels'] = [];
  for (const level of [...new Set(lanes.map(lane => lane.level))].sort((a, b) => a - b)) {
    const bands = lanes.filter(lane => lane.level === level);
    levels.push({ level, left: Math.min(...bands.map(band => band.x)), right: Math.max(...bands.map(band => band.x + band.width)) });
  }
  const bottoms = lanes.map(lane => lane.y + lane.height);
  return { positions, routes, lanes, levels, height: Math.max(LEVEL_HEADER, ...bottoms) };
}

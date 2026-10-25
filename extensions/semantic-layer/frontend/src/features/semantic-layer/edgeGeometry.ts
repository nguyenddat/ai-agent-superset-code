import { Position } from '@xyflow/react';
import type { Point } from './modelLayout';
import type { StoredEdgeShape, StoredLineageCanvas } from './types';

/** How a lineage edge is drawn, as in draw.io: orthogonal segments, a straight polyline, or a smooth curve. */
export type EdgeStyle = 'orthogonal' | 'straight' | 'curved';

/**
 * The user-adjustable shape of an edge. Its ends always follow the cards it joins.
 * - `coords` shapes an orthogonal edge: alternately the x of a vertical segment and the y of a horizontal one,
 *   starting and ending with a vertical segment's x, since the edge leaves and enters cards horizontally.
 * - `waypoints` are the points a straight or curved edge passes through.
 * - `label` offsets the label's centre from the middle of the edge; null keeps it on the middle.
 * - `ports` move the source and target ends up or down the card side, from the middle of that side.
 */
export type EdgeGeometry = { style: EdgeStyle; coords: number[]; waypoints: Point[]; label: Point | null; ports: [number, number] };

export const EDGE_STYLES: Array<[EdgeStyle, string]> = [['orthogonal', 'Vuông góc'], ['straight', 'Thẳng'], ['curved', 'Cong']];
export const DEFAULT_GEOMETRY: EdgeGeometry = { style: 'orthogonal', coords: [], waypoints: [], label: null, ports: [0, 0] };

/** Edited points snap to this step, a twelfth of a canvas cell. */
export const EDGE_SNAP = 10;
/** Length of the horizontal stub an orthogonal edge keeps beside a card before it turns. */
const STUB = 24;

export const snapPoint = (point: Point): Point => ({ x: Math.round(point.x / EDGE_SNAP) * EDGE_SNAP, y: Math.round(point.y / EDGE_SNAP) * EDGE_SNAP });
const outward = (side: Position) => (side === Position.Left ? -1 : 1);

/**
 * The orthogonal shape used while the user has not shaped an edge: one vertical segment halfway between the cards,
 * or, when the target lies behind the source, a detour around both stubs.
 */
export function defaultCoords(source: Point, target: Point, sourceSide: Position, targetSide: Position): number[] {
  const exit = source.x + outward(sourceSide) * STUB;
  const entry = target.x + outward(targetSide) * STUB;
  const facing = outward(sourceSide) === 1 ? exit <= entry : exit >= entry;
  if (facing && outward(sourceSide) !== outward(targetSide)) return [Math.round((source.x + target.x) / 2)];
  if (outward(sourceSide) === outward(targetSide)) {
    const x = outward(sourceSide) === 1 ? Math.max(exit, entry) : Math.min(exit, entry);
    return [x];
  }
  return [exit, Math.round((source.y + target.y) / 2), entry];
}

/** The orthogonal coordinates from `coords`, or the default shape; always an odd number of them. */
export function effectiveCoords(geometry: EdgeGeometry, source: Point, target: Point, sourceSide: Position, targetSide: Position): number[] {
  const coords = geometry.coords.length % 2 === 1 ? geometry.coords : geometry.coords.slice(0, -1);
  if (coords.length > 0) return coords;
  return source.y === target.y && outward(sourceSide) !== outward(targetSide) && (target.x - source.x) * outward(sourceSide) > 0
    ? []
    : defaultCoords(source, target, sourceSide, targetSide);
}

/** Corner points of an orthogonal edge, ends included; segment i + 1 (i >= 0) is the one `coords[i]` places. */
export function orthogonalRoute(source: Point, target: Point, coords: number[]): Point[] {
  if (coords.length === 0) return [source, target];
  const route = [source];
  let y = source.y;
  for (let index = 0; index < coords.length; index += 2) {
    const x = coords[index];
    route.push({ x, y });
    y = index + 1 < coords.length ? coords[index + 1] : target.y;
    route.push({ x, y });
  }
  route.push(target);
  return route;
}

/**
 * Reads the orthogonal coordinates out of a route whose first and last segments are horizontal, such as the routes
 * ELK draws; null when the route does not alternate that way.
 */
export function coordsFromRoute(route: Point[]): number[] | null {
  const points = route.filter((point, index) => index === 0 || point.x !== route[index - 1].x || point.y !== route[index - 1].y);
  // Merge consecutive collinear segments.
  const corners = points.filter((point, index) => {
    if (index === 0 || index === points.length - 1) return true;
    const [before, after] = [points[index - 1], points[index + 1]];
    return !((before.x === point.x && point.x === after.x) || (before.y === point.y && point.y === after.y));
  });
  if (corners.length === 2) return corners[0].y === corners[1].y ? [] : null;
  const coords: number[] = [];
  for (let index = 1; index < corners.length; index += 1) {
    const [from, to] = [corners[index - 1], corners[index]];
    const vertical = from.x === to.x;
    if (from.x !== to.x && from.y !== to.y) return null;
    const expectVertical = (index - 1) % 2 === 1;
    if (vertical !== expectVertical) return null;
    if (index > 1 && index < corners.length - 1) coords.push(vertical ? from.x : from.y);
  }
  return coords.length % 2 === 1 ? coords : null;
}

/** All points the edge passes through, ends included, before any curve is applied. */
export function edgePoints(geometry: EdgeGeometry, source: Point, target: Point, sourceSide: Position, targetSide: Position): Point[] {
  if (geometry.style === 'orthogonal') return orthogonalRoute(source, target, effectiveCoords(geometry, source, target, sourceSide, targetSide));
  return [source, ...geometry.waypoints, target];
}

/** Cubic Bézier segments of a curve through `points`, leaving and entering the cards along their sides. */
function curveSegments(points: Point[], sourceSide: Position, targetSide: Position): Array<[Point, Point, Point, Point]> {
  const last = points.length - 1;
  const tangents = points.map((point, index) => {
    if (index === 0 || index === last) {
      const neighbour = points[index === 0 ? 1 : last - 1];
      const reach = Math.max(Math.hypot(neighbour.x - point.x, neighbour.y - point.y), 80) * 1.2;
      const direction = index === 0 ? outward(sourceSide) : -outward(targetSide);
      return { x: direction * reach, y: 0 };
    }
    return { x: (points[index + 1].x - points[index - 1].x) / 2, y: (points[index + 1].y - points[index - 1].y) / 2 };
  });
  return points.slice(1).map((point, index) => {
    const start = points[index];
    return [
      start,
      { x: start.x + tangents[index].x / 3, y: start.y + tangents[index].y / 3 },
      { x: point.x - tangents[index + 1].x / 3, y: point.y - tangents[index + 1].y / 3 },
      point,
    ];
  });
}

/** Rounded-corner polyline through `points`. */
function polylinePath(points: Point[], radius: number): string {
  let path = `M ${points[0].x},${points[0].y}`;
  for (let index = 1; index < points.length - 1; index += 1) {
    const [previous, corner, next] = [points[index - 1], points[index], points[index + 1]];
    const inLength = Math.hypot(corner.x - previous.x, corner.y - previous.y);
    const outLength = Math.hypot(next.x - corner.x, next.y - corner.y);
    const r = Math.min(radius, inLength / 2, outLength / 2);
    const before = { x: corner.x - ((corner.x - previous.x) / (inLength || 1)) * r, y: corner.y - ((corner.y - previous.y) / (inLength || 1)) * r };
    const after = { x: corner.x + ((next.x - corner.x) / (outLength || 1)) * r, y: corner.y + ((next.y - corner.y) / (outLength || 1)) * r };
    path += ` L ${before.x},${before.y} Q ${corner.x},${corner.y} ${after.x},${after.y}`;
  }
  const last = points[points.length - 1];
  return `${path} L ${last.x},${last.y}`;
}

/** The SVG path of an edge, and a polyline that follows it closely enough to place the label on. */
export function edgePath(geometry: EdgeGeometry, points: Point[], sourceSide: Position, targetSide: Position): { path: string; trace: Point[] } {
  if (geometry.style !== 'curved') return { path: polylinePath(points, geometry.style === 'orthogonal' ? 8 : 0), trace: points };
  const segments = curveSegments(points, sourceSide, targetSide);
  const path = segments.reduce((text, [, c1, c2, end]) => `${text} C ${c1.x},${c1.y} ${c2.x},${c2.y} ${end.x},${end.y}`, `M ${points[0].x},${points[0].y}`);
  const trace = [points[0]];
  for (const [p0, p1, p2, p3] of segments) {
    for (let step = 1; step <= 16; step += 1) {
      const t = step / 16;
      const u = 1 - t;
      trace.push({
        x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
        y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
      });
    }
  }
  return { path, trace };
}

/** The point halfway along a polyline. */
export function midpoint(trace: Point[]): Point {
  const lengths = trace.slice(1).map((point, index) => Math.hypot(point.x - trace[index].x, point.y - trace[index].y));
  let remaining = lengths.reduce((sum, length) => sum + length, 0) / 2;
  for (const [index, length] of lengths.entries()) {
    if (remaining <= length && length > 0) {
      const ratio = remaining / length;
      return { x: trace[index].x + (trace[index + 1].x - trace[index].x) * ratio, y: trace[index].y + (trace[index + 1].y - trace[index].y) * ratio };
    }
    remaining -= length;
  }
  return trace[0];
}

/**
 * The geometry an edge gets when the user switches its style: a straight edge and a curve share their waypoints,
 * while a switch to or from orthogonal starts from that style's plain shape.
 */
export function withStyle(geometry: EdgeGeometry, style: EdgeStyle): EdgeGeometry {
  if (style === geometry.style) return geometry;
  const keepWaypoints = style !== 'orthogonal' && geometry.style !== 'orthogonal';
  return { ...geometry, style, coords: [], waypoints: keepWaypoints ? geometry.waypoints : [] };
}

/** Hand-placed lineage cards (node ID → position) and hand-shaped edges (edge ID → geometry). */
export type LineageLayout = { nodes: Map<string, Point>; edges: Map<string, EdgeGeometry> };

const pair = (point: Point): [number, number] => [point.x, point.y];
const fromPair = ([x, y]: [number, number]): Point => ({ x, y });

export function toStoredLineage(layout: LineageLayout): StoredLineageCanvas {
  const edges: Record<string, StoredEdgeShape> = {};
  for (const [id, geometry] of layout.edges) {
    edges[id] = {
      style: geometry.style,
      coords: geometry.coords,
      waypoints: geometry.waypoints.map(pair),
      label: geometry.label ? pair(geometry.label) : null,
      ports: geometry.ports,
    };
  }
  return { nodes: Object.fromEntries([...layout.nodes].map(([id, point]) => [id, pair(point)])), edges };
}

export function fromStoredLineage(stored: StoredLineageCanvas | null): LineageLayout {
  const edges = new Map<string, EdgeGeometry>();
  for (const [id, shape] of Object.entries(stored?.edges ?? {})) {
    edges.set(id, {
      style: shape.style,
      coords: shape.coords ?? [],
      waypoints: (shape.waypoints ?? []).map(fromPair),
      label: shape.label ? fromPair(shape.label) : null,
      ports: shape.ports ?? [0, 0],
    });
  }
  return { nodes: new Map(Object.entries(stored?.nodes ?? {}).map(([id, point]) => [id, fromPair(point)])), edges };
}

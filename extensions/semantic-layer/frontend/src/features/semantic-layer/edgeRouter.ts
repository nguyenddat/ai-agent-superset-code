import type { Point, Size } from './modelLayout';

export type Box = Point & Size;
/** Side of a card an edge leaves or enters it by. */
export type CardSide = 'left' | 'right';

/** Clearance an edge keeps from every card it passes. */
const MARGIN = 14;
/** Length of the horizontal stub an edge keeps beside its card before it may turn. */
const STUB = 20;
/** Cost of one bend, in canvas pixels of length: a route takes a detour this long to save a bend. */
const BEND_COST = 48;

const outward = (side: CardSide) => (side === 'left' ? -1 : 1);
const inside = (point: Point, box: Box) => point.x > box.x && point.x < box.x + box.width && point.y > box.y && point.y < box.y + box.height;
const inflate = (box: Box, by: number): Box => ({ x: box.x - by, y: box.y - by, width: box.width + by * 2, height: box.height + by * 2 });

/** Whether the axis-aligned segment from `a` to `b` passes through the inside of `box`. */
function crosses(a: Point, b: Point, box: Box): boolean {
  const [left, right, top, bottom] = [box.x, box.x + box.width, box.y, box.y + box.height];
  if (a.y === b.y) return a.y > top && a.y < bottom && Math.min(a.x, b.x) < right && Math.max(a.x, b.x) > left;
  return a.x > left && a.x < right && Math.min(a.y, b.y) < bottom && Math.max(a.y, b.y) > top;
}

/** Whether a polyline passes through the inside of any of `boxes`. */
export function routeCrosses(points: Point[], boxes: Box[]): boolean {
  return points.slice(1).some((point, index) => {
    const from = points[index];
    // Straight and curved edges are tested along their chords, close enough to spot a card in the way.
    if (from.x !== point.x && from.y !== point.y) {
      const corner = { x: point.x, y: from.y };
      return boxes.some(box => crosses(from, corner, box) && crosses(corner, point, box));
    }
    return boxes.some(box => crosses(from, point, box));
  });
}

/** The sorted distinct values, with the midpoint of each neighbouring pair, so routes can run down the middle of gaps. */
function guides(values: number[]): number[] {
  const sorted = [...new Set(values.map(value => Math.round(value)))].sort((a, b) => a - b);
  const result: number[] = [];
  sorted.forEach((value, index) => {
    if (index > 0) result.push(Math.round((sorted[index - 1] + value) / 2));
    result.push(value);
  });
  return [...new Set(result)].sort((a, b) => a - b);
}

/** A binary min-heap of states keyed by their estimated total cost. */
class Heap {
  private items: Array<[number, number]> = [];

  get size() { return this.items.length; }

  push(key: number, value: number) {
    const items = this.items;
    items.push([key, value]);
    let index = items.length - 1;
    while (index > 0) {
      const parent = (index - 1) >> 1;
      if (items[parent][0] <= items[index][0]) break;
      [items[parent], items[index]] = [items[index], items[parent]];
      index = parent;
    }
  }

  pop(): number {
    const items = this.items;
    const top = items[0][1];
    const last = items.pop() as [number, number];
    if (items.length > 0) {
      items[0] = last;
      let index = 0;
      for (;;) {
        const [left, right] = [index * 2 + 1, index * 2 + 2];
        let smallest = index;
        if (left < items.length && items[left][0] < items[smallest][0]) smallest = left;
        if (right < items.length && items[right][0] < items[smallest][0]) smallest = right;
        if (smallest === index) break;
        [items[smallest], items[index]] = [items[index], items[smallest]];
        index = smallest;
      }
    }
    return top;
  }
}

// Directions: 0 right, 1 down, 2 left, 3 up.
const STEPS: Array<[number, number]> = [[1, 0], [0, 1], [-1, 0], [0, -1]];

/**
 * An orthogonal route from `source` to `target` that keeps clear of `obstacles`: it leaves and enters the cards
 * horizontally on their `sourceSide` and `targetSide`, and otherwise runs on a grid made of the obstacles' outlines
 * (kept MARGIN away) and the lines midway between them, taking the path that is shortest once each bend is charged
 * BEND_COST. Null when the obstacles leave no way through.
 */
export function routeOrthogonal(source: Point, sourceSide: CardSide, target: Point, targetSide: CardSide, obstacles: Box[]): Point[] | null {
  const start = { x: source.x + outward(sourceSide) * STUB, y: source.y };
  const end = { x: target.x + outward(targetSide) * STUB, y: target.y };
  // Cards packed closer than the clearance would wall in the stubs; such a card stops counting as an obstacle.
  const blocks = obstacles.map(box => inflate(box, MARGIN)).filter(box => !inside(start, box) && !inside(end, box));
  const xs = guides([start.x, end.x, ...blocks.flatMap(box => [box.x, box.x + box.width])]);
  const ys = guides([start.y, end.y, ...blocks.flatMap(box => [box.y, box.y + box.height])]);
  const columns = xs.length;
  const free = (col: number, row: number) => !blocks.some(box => inside({ x: xs[col], y: ys[row] }, box));
  const [startCol, startRow] = [xs.indexOf(Math.round(start.x)), ys.indexOf(Math.round(start.y))];
  const [endCol, endRow] = [xs.indexOf(Math.round(end.x)), ys.indexOf(Math.round(end.y))];
  // The route arrives at `end` heading into the target card.
  const entry = outward(targetSide) === 1 ? 2 : 0;

  const stateOf = (col: number, row: number, direction: number) => ((row * columns + col) << 2) | direction;
  const costs = new Map<number, number>();
  const previous = new Map<number, number>();
  const heap = new Heap();
  const estimate = (col: number, row: number) => Math.abs(xs[col] - end.x) + Math.abs(ys[row] - end.y);
  const first = stateOf(startCol, startRow, outward(sourceSide) === 1 ? 0 : 2);
  costs.set(first, 0);
  heap.push(estimate(startCol, startRow), first);
  let goal: number | null = null;
  while (heap.size > 0) {
    const state = heap.pop();
    const direction = state & 3;
    const cell = state >> 2;
    const [col, row] = [cell % columns, Math.floor(cell / columns)];
    const cost = costs.get(state) as number;
    if (col === endCol && row === endRow) {
      goal = state;
      break;
    }
    STEPS.forEach(([dx, dy], heading) => {
      // Turning straight back is never shorter.
      if (heading === (direction + 2) % 4) return;
      const [nextCol, nextRow] = [col + dx, row + dy];
      if (nextCol < 0 || nextRow < 0 || nextCol >= columns || nextRow >= ys.length || !free(nextCol, nextRow)) return;
      const [from, to] = [{ x: xs[col], y: ys[row] }, { x: xs[nextCol], y: ys[nextRow] }];
      if (blocks.some(box => crosses(from, to, box))) return;
      const arriving = nextCol === endCol && nextRow === endRow;
      const bends = (heading !== direction ? 1 : 0) + (arriving && heading !== entry ? 1 : 0);
      const nextCost = cost + Math.abs(to.x - from.x) + Math.abs(to.y - from.y) + bends * BEND_COST;
      const next = stateOf(nextCol, nextRow, heading);
      if (nextCost >= (costs.get(next) ?? Infinity)) return;
      costs.set(next, nextCost);
      previous.set(next, state);
      heap.push(nextCost + estimate(nextCol, nextRow), next);
    });
  }
  if (goal === null) return null;

  const path: Point[] = [];
  for (let state: number | undefined = goal; state !== undefined; state = previous.get(state)) {
    const cell = state >> 2;
    path.unshift({ x: xs[cell % columns], y: ys[Math.floor(cell / columns)] });
  }
  return [source, ...path, target];
}

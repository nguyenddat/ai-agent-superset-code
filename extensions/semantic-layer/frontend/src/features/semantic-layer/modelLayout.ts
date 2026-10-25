import { layerLevels } from './datasets';
import type { BusinessDomain, DataLayer, LineageEdge, StoredCanvas } from './types';

/** Side of one canvas grid cell; the business view places one table tile per cell. */
export const GRID_CELL = 120;
/** Gap between a tile and its cell's edges. */
export const TILE_INSET = 6;
export const TILE_SIZE = GRID_CELL - TILE_INSET * 2;
const GROUP_ROW_MAX_CELLS = 13;

export type Point = { x: number; y: number };
export type Size = { width: number; height: number };

/** One canvas grid cell, counted in cells from the canvas origin. */
export type Cell = { col: number; row: number };
export type Direction = 'left' | 'right' | 'up' | 'down';

/** Key of the area that collects the tables no business domain holds. */
export const UNASSIGNED_DOMAIN = 'domain-unassigned';

/**
 * A business domain on the canvas: the set of grid cells it covers, which need not form a rectangle, and the cell of
 * its header. Domains may overlap, since one table can belong to several domains.
 */
export type DomainGrid = { key: string; domain: BusinessDomain | null; cells: Cell[]; header: Cell };

/** The business view: every domain's cells and the one cell of each table. */
export type CanvasGrid = { domains: DomainGrid[]; tables: Map<number, Cell> };

/** A table that the canvas places inside (add) or outside (remove) a domain it does not, or does, belong to. */
export type MembershipChange = { datasetId: number; domain: BusinessDomain; add: boolean };

export const cellKey = (cell: Cell) => `${cell.col},${cell.row}`;

const STEPS: Record<Direction, Cell> = { left: { col: -1, row: 0 }, right: { col: 1, row: 0 }, up: { col: 0, row: -1 }, down: { col: 0, row: 1 } };

/** The cell `steps` cells away from `cell` in `direction`. */
export function stepCell(cell: Cell, direction: Direction, steps = 1): Cell {
  return { col: cell.col + STEPS[direction].col * steps, row: cell.row + STEPS[direction].row * steps };
}

/** Top-left cell and size, in cells, of the smallest rectangle around `cells`. */
export function cellBounds(cells: Cell[]): Cell & { columns: number; rows: number } {
  const cols = cells.map(cell => cell.col);
  const rows = cells.map(cell => cell.row);
  const [col, row] = [Math.min(...cols), Math.min(...rows)];
  return { col, row, columns: Math.max(...cols) - col + 1, rows: Math.max(...rows) - row + 1 };
}

/** The cells of `cells` that can be reached from `start` through side-by-side cells. */
function connectedCells(cells: Cell[], start: Cell): Cell[] {
  const remaining = new Set(cells.map(cellKey));
  if (!remaining.delete(cellKey(start))) return [];
  const reached = [start];
  for (let index = 0; index < reached.length; index += 1) {
    for (const direction of Object.keys(STEPS) as Direction[]) {
      const next = stepCell(reached[index], direction);
      if (remaining.delete(cellKey(next))) reached.push(next);
    }
  }
  return reached;
}

/** Whether every cell can be reached from every other one through side-by-side cells. */
export function cellsConnected(cells: Cell[]): boolean {
  return cells.length === 0 || connectedCells(cells, cells[0]).length === cells.length;
}

/** Whether `cell` is one of `keys` or right next to one of them. */
const touches = (cell: Cell, keys: Set<string>) => (
  keys.has(cellKey(cell)) || (Object.keys(STEPS) as Direction[]).some(direction => keys.has(cellKey(stepCell(cell, direction))))
);

type DomainEntry = { key: string; domain: BusinessDomain | null; ids: number[] };

/** Every domain with the tables it holds, then the unassigned area when some tables belong to no domain. */
function domainEntries(domains: BusinessDomain[], datasetIds: number[]): DomainEntry[] {
  const assigned = new Set(domains.flatMap(domain => domain.dataset_ids));
  const unassigned = datasetIds.filter(id => !assigned.has(id));
  return [
    ...domains.map(domain => ({ key: `domain-${domain.id}`, domain, ids: domain.dataset_ids.filter(id => datasetIds.includes(id)) })),
    ...(unassigned.length > 0 ? [{ key: UNASSIGNED_DOMAIN, domain: null, ids: unassigned }] : []),
  ];
}

/**
 * Lays each business domain out as a block of grid cells, packed into rows with one empty cell between blocks. The
 * header takes the block's top-left cell and the tables fill the following cells row by row. A table held by several
 * domains is placed in the first one only; reconcileGrid then extends the other domains over it.
 */
export function layoutDomainGroups(domains: BusinessDomain[], datasetIds: number[]): CanvasGrid {
  const grids: DomainGrid[] = [];
  const tables = new Map<number, Cell>();
  let cursor: Cell = { col: 0, row: 0 };
  let rowHeight = 0;
  for (const entry of domainEntries(domains, datasetIds)) {
    const ids = entry.ids.filter(id => !tables.has(id));
    const columns = Math.max(2, Math.ceil(Math.sqrt(ids.length + 1)));
    const rows = Math.ceil((ids.length + 1) / columns);
    if (cursor.col > 0 && cursor.col + columns > GROUP_ROW_MAX_CELLS) {
      cursor = { col: 0, row: cursor.row + rowHeight + 1 };
      rowHeight = 0;
    }
    const cells: Cell[] = [];
    for (let index = 0; index < columns * rows; index += 1) {
      cells.push({ col: cursor.col + (index % columns), row: cursor.row + Math.floor(index / columns) });
    }
    grids.push({ key: entry.key, domain: entry.domain, cells, header: cells[0] });
    ids.forEach((id, index) => tables.set(id, cells[index + 1]));
    cursor = { ...cursor, col: cursor.col + columns + 1 };
    rowHeight = Math.max(rowHeight, rows);
  }
  return { domains: grids, tables };
}

/** The nearest cell to `near`, ring by ring, that `isFree` accepts. */
function findFreeCell(near: Cell, isFree: (cell: Cell) => boolean): Cell {
  for (let radius = 0; radius < 200; radius += 1) {
    for (let row = near.row - radius; row <= near.row + radius; row += 1) {
      for (let col = near.col - radius; col <= near.col + radius; col += 1) {
        const cell = { col, row };
        if (Math.max(Math.abs(col - near.col), Math.abs(row - near.row)) === radius && isFree(cell)) return cell;
      }
    }
  }
  return near;
}

/**
 * Brings a canvas grid in line with the domains' tables: domains and tables that are new get free cells near the
 * tables or domains they belong with, each domain covers the cells of all its tables, and no domain keeps a cell that
 * holds a table it does not have.
 */
export function reconcileGrid(grid: CanvasGrid, domains: BusinessDomain[], datasetIds: number[]): CanvasGrid {
  const entries = domainEntries(domains, datasetIds);
  const tables = new Map([...grid.tables].filter(([id]) => datasetIds.includes(id)));
  const previous = new Map(grid.domains.map(item => [item.key, item]));
  const grids: DomainGrid[] = entries
    .filter(entry => previous.has(entry.key))
    .map(entry => ({ ...(previous.get(entry.key) as DomainGrid), domain: entry.domain }));
  const allCells = () => [...grids.flatMap(item => item.cells), ...tables.values()];
  const tableAt = () => new Set([...tables.values()].map(cellKey));
  const headers = () => new Set(grids.map(item => cellKey(item.header)));

  for (const entry of entries.filter(item => !previous.has(item.key))) {
    const placed = entry.ids.map(id => tables.get(id)).find(Boolean);
    const used = allCells();
    const near = placed ?? { col: used.length > 0 ? Math.max(...used.map(cell => cell.col)) + 2 : 0, row: 0 };
    const covered = new Set(grids.flatMap(item => item.cells.map(cellKey)));
    const header = findFreeCell(near, cell => !tableAt().has(cellKey(cell)) && !covered.has(cellKey(cell)));
    grids.push({ key: entry.key, domain: entry.domain, cells: [header], header });
  }
  for (const id of datasetIds.filter(item => !tables.has(item))) {
    const target = grids.find(item => entries.find(entry => entry.key === item.key)?.ids.includes(id)) as DomainGrid;
    const others = new Set(grids.filter(item => item !== target).flatMap(item => item.cells.map(cellKey)));
    const blocked = new Set([...tableAt(), ...headers(), ...others]);
    tables.set(id, findFreeCell(target.header, cell => !blocked.has(cellKey(cell))));
  }
  for (const item of grids) {
    const members = new Set(entries.find(entry => entry.key === item.key)?.ids);
    const holders = new Map([...tables].map(([id, cell]) => [cellKey(cell), id]));
    const cells = item.cells.filter(cell => {
      const holder = holders.get(cellKey(cell));
      return holder === undefined || members.has(holder);
    });
    const keys = new Set(cells.map(cellKey));
    for (const id of members) {
      const cell = tables.get(id) as Cell;
      if (!keys.has(cellKey(cell))) cells.push(cell);
    }
    item.cells = cells;
  }
  // The unassigned area stays one block around its header: a table that left its last domain moves into the nearest
  // free cell of the area or right beside it.
  const area = grids.find(item => item.key === UNASSIGNED_DOMAIN);
  if (area) {
    const members = entries.find(entry => entry.key === UNASSIGNED_DOMAIN)?.ids ?? [];
    const cells = connectedCells(area.cells, area.header);
    const domainCells = grids.filter(item => item !== area).flatMap(item => item.cells.map(cellKey));
    for (const id of members) {
      const keys = new Set(cells.map(cellKey));
      if (keys.has(cellKey(tables.get(id) as Cell))) continue;
      const blocked = new Set([...[...tables].filter(([other]) => other !== id).map(([, cell]) => cellKey(cell)), ...headers(), ...domainCells]);
      const cell = findFreeCell(area.header, candidate => !blocked.has(cellKey(candidate)) && touches(candidate, keys));
      tables.set(id, cell);
      if (!keys.has(cellKey(cell))) cells.push(cell);
    }
    area.cells = cells;
  }
  return { domains: grids, tables };
}

/** Tables outside every business domain that also lie outside the unassigned area. */
export function strayTables(grid: CanvasGrid): number[] {
  const area = new Set(grid.domains.find(item => item.key === UNASSIGNED_DOMAIN)?.cells.map(cellKey));
  const covered = new Set(grid.domains.filter(item => item.domain).flatMap(item => item.cells.map(cellKey)));
  return [...grid.tables].filter(([, cell]) => !covered.has(cellKey(cell)) && !area.has(cellKey(cell))).map(([id]) => id);
}

/**
 * Whether the business view is consistent: tables sit in different cells and never on a header, headers sit in
 * different cells, and the unassigned area stays apart from the domains.
 */
export function validGrid(grid: CanvasGrid): boolean {
  const tableCells = [...grid.tables.values()].map(cellKey);
  const headers = grid.domains.map(item => cellKey(item.header));
  if (new Set(tableCells).size !== tableCells.length || new Set(headers).size !== headers.length) return false;
  if (tableCells.some(key => headers.includes(key))) return false;
  const unassigned = new Set(grid.domains.find(item => item.key === UNASSIGNED_DOMAIN)?.cells.map(cellKey));
  return grid.domains.every(item => item.key === UNASSIGNED_DOMAIN || item.cells.every(cell => !unassigned.has(cellKey(cell))));
}

/** Tables that now lie inside a domain they do not belong to, or outside a domain they belong to. */
export function membershipChanges(grid: CanvasGrid): MembershipChange[] {
  const changes: MembershipChange[] = [];
  for (const item of grid.domains) {
    if (!item.domain) continue;
    const covered = new Set(item.cells.map(cellKey));
    for (const [datasetId, cell] of grid.tables) {
      const inside = covered.has(cellKey(cell));
      if (inside !== item.domain.dataset_ids.includes(datasetId)) changes.push({ datasetId, domain: item.domain, add: inside });
    }
  }
  return changes;
}

/** The canvas in the form the backend stores. */
export function toStoredCanvas(grid: CanvasGrid): StoredCanvas {
  const pair = (cell: Cell): [number, number] => [cell.col, cell.row];
  return {
    domains: grid.domains.map(domain => ({ key: domain.key, header: pair(domain.header), cells: domain.cells.map(pair) })),
    tables: Object.fromEntries([...grid.tables].map(([id, cell]) => [String(id), pair(cell)])),
  };
}

/** A stored canvas, before reconcileGrid attaches the current domains to it. */
export function fromStoredCanvas(stored: StoredCanvas): CanvasGrid {
  const cell = ([col, row]: [number, number]): Cell => ({ col, row });
  return {
    domains: stored.domains.map(domain => ({ key: domain.key, domain: null, header: cell(domain.header), cells: domain.cells.map(cell) })),
    tables: new Map(Object.entries(stored.tables).map(([id, position]) => [Number(id), cell(position)])),
  };
}

/** Canvas position and size of a domain's node: the rectangle around its cells. */
export function domainFrame(grid: DomainGrid): { position: Point; size: Size; origin: Cell } {
  const bounds = cellBounds(grid.cells);
  return {
    position: { x: bounds.col * GRID_CELL, y: bounds.row * GRID_CELL },
    size: { width: bounds.columns * GRID_CELL, height: bounds.rows * GRID_CELL },
    origin: { col: bounds.col, row: bounds.row },
  };
}

/** Canvas position of a table tile in `cell`. */
export function tilePosition(cell: Cell): Point {
  return { x: cell.col * GRID_CELL + TILE_INSET, y: cell.row * GRID_CELL + TILE_INSET };
}

/** The cell a tile at canvas `position` is closest to. */
export function tileCell(position: Point): Cell {
  return { col: Math.round((position.x - TILE_INSET) / GRID_CELL), row: Math.round((position.y - TILE_INSET) / GRID_CELL) };
}

/**
 * A lineage lane: one data layer, or the unclassified datasets. `level` counts the levels in use from 0; lanes on one
 * level share a column of the lineage.
 */
export type Lane = { key: string; label: string; hint: string; color: string | null; level: number };

export const UNCLASSIFIED_LANE = 'unclassified';

/** Lineage lanes in flow order: the data layers level by level, then the unclassified datasets on a level after them. */
export function lineageLanes(layers: DataLayer[]): Lane[] {
  const levels = layerLevels(layers);
  return [
    ...levels.flatMap((level, index) => level.map(layer => ({
      key: `layer-${layer.id}`,
      label: layer.name,
      hint: layer.description ?? '',
      color: layer.color,
      level: index,
    }))),
    { key: UNCLASSIFIED_LANE, label: 'Chưa phân tầng', hint: 'Phân loại trong Data Dictionary', color: null, level: levels.length },
  ];
}

export function datasetLaneKey(layerId: number | null | undefined): string {
  return layerId == null ? UNCLASSIFIED_LANE : `layer-${layerId}`;
}

export type LineageItem = { id: string; lane: string; datasetId: number; active: boolean };

/**
 * Picks the tables of the selected domains (all tables when none is selected) and adds their direct lineage neighbours
 * as inactive context.
 */
export function selectLineageItems(
  datasetLanes: Map<number, string>,
  domains: BusinessDomain[],
  selectedDomainIds: number[],
  edges: LineageEdge[],
): LineageItem[] {
  const selected = domains.filter(domain => selectedDomainIds.includes(domain.id));
  const active = new Set(selected.length > 0 ? selected.flatMap(domain => domain.dataset_ids) : [...datasetLanes.keys()]);
  const included = new Set(active);
  for (const edge of edges) {
    if (active.has(edge.source)) included.add(edge.target);
    if (active.has(edge.target)) included.add(edge.source);
  }
  return [...included]
    .filter(id => datasetLanes.has(id))
    .map(id => ({ id: `table-${id}`, lane: datasetLanes.get(id) as string, datasetId: id, active: active.has(id) }));
}

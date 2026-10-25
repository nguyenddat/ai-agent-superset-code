/**
 * Geometry of a lineage table card. ELK lays the cards out from these sizes and attaches edges to the column rows at
 * `portY`, and the card's CSS draws every part at the same fixed height, so an edge meets the row it joins.
 */

/** How much of each table the lineage cards show: the name only, the key columns, or every column. */
export type DetailLevel = 'name' | 'keys' | 'all';

export const DETAIL_LEVELS: Array<[DetailLevel, string]> = [['name', 'Tên bảng'], ['keys', 'Cột khóa'], ['all', 'Tất cả cột']];

export const CARD_WIDTH = 264;
/** The card border, drawn inside the card's height. */
export const CARD_BORDER = 1;
export const CARD_HEADER = 48;
/** Each listed column, its top border included. */
export const CARD_ROW = 26;
/** The "+N cột khác" line under the listed columns. */
export const CARD_MORE = 22;
/** The row that opens the dataset's metrics. */
export const CARD_METRICS = 28;

/** A column listed on a card, with what the tooltip tells about it; `metric` marks a column a metric arrow leaves. */
export type CardColumn = { name: string; type: string; pk: boolean; fk: boolean; metric: boolean; title: string };

/**
 * The columns a metric's arrows leave from: the values it aggregates, or every column it uses when it aggregates none
 * of them (a count of the rows that meet a condition). Empty when its columns are unknown; its arrow then leaves the
 * card's metrics row.
 */
export function metricSources(metric: { columns: Array<{ name: string; role: 'measure' | 'filter' }> | null }): string[] {
  const columns = metric.columns ?? [];
  const measures = columns.filter(column => column.role === 'measure');
  return (measures.length > 0 ? measures : columns).map(column => column.name);
}

/** What a card lists: its columns in order, how many it leaves out, and how many metrics it has. */
export type CardContent = { columns: CardColumn[]; hidden: number; metrics: number };

export function cardHeight(content: CardContent): number {
  return CARD_BORDER * 2
    + CARD_HEADER
    + content.columns.length * CARD_ROW
    + (content.hidden > 0 ? CARD_MORE : 0)
    + (content.metrics > 0 ? CARD_METRICS : 0);
}

/** Height on the card where an edge joining `column` meets it: that column's row, or the header when it is not listed. */
export function portY(content: CardContent, column: string | null): number {
  const index = column === null ? -1 : content.columns.findIndex(item => item.name === column);
  return index < 0 ? CARD_BORDER + CARD_HEADER / 2 : CARD_BORDER + CARD_HEADER + index * CARD_ROW + CARD_ROW / 2;
}

/** React Flow handle of a column row on one side of a card, or of the header when the column is not listed. */
export function handleId(content: CardContent, column: string | null, side: 'l' | 'r'): string {
  return column !== null && content.columns.some(item => item.name === column) ? `c:${column}:${side}` : side;
}

/** A dataset's metrics stand in a column to the right of its card, each joined to the card by one arrow. */
export const METRIC_WIDTH = 224;
export const METRIC_HEIGHT = 32;
/** Room between the card and its metrics, where every arrow runs down a lane of its own. */
const METRIC_GAP_X = 88;
const METRIC_GAP_Y = 6;
/** Room the arrows keep from the card and from the metrics before they turn. */
const LANE_MARGIN = 14;
const LANE_STEP = 8;

type MetricLike = { columns: Array<{ name: string; role: 'measure' | 'filter' }> | null };

/**
 * Where a metric stands beside its card, relative to the card's top-left corner: `y` is the metric's top, `sources`
 * the heights its arrow leaves the card at (the rows of the columns it is computed from, or the metrics row), and
 * `lane` the x of the arrow's vertical run.
 */
export type MetricSlot<M> = { metric: M; y: number; sources: number[]; lane: number };

/**
 * The metrics of a card laid out beside it. Each metric stands level with the middle of the rows it is computed
 * from, or as close under it as the metrics above allow, so metrics keep the order of their rows and arrows run
 * almost level; a metric of several rows stands between them rather than taking a place by its topmost one. Arrows
 * then mostly run down, and an arrow lower on the card takes a lane nearer to the card, so they keep from crossing.
 */
export function metricSlots<M extends MetricLike>(content: CardContent, metrics: M[]): Array<MetricSlot<M>> {
  const metricsRow = cardHeight(content) - CARD_BORDER - CARD_METRICS / 2;
  const middle = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;
  const items = metrics
    .map((metric, index) => {
      const listed = metricSources(metric).filter(name => content.columns.some(column => column.name === name));
      const sources = listed.length > 0 ? listed.map(name => portY(content, name)) : [metricsRow];
      return { metric, index, sources, centre: middle(sources) };
    })
    .sort((a, b) => a.centre - b.centre || a.index - b.index);
  const step = Math.min(LANE_STEP, (METRIC_GAP_X - LANE_MARGIN * 2) / Math.max(1, items.length - 1));
  let bottom = -Infinity;
  return items.map(({ metric, sources, centre }, order) => {
    const y = Math.max(centre - METRIC_HEIGHT / 2, bottom + METRIC_GAP_Y);
    bottom = y + METRIC_HEIGHT;
    return { metric, y, sources, lane: CARD_WIDTH + METRIC_GAP_X - LANE_MARGIN - order * step };
  });
}

/** Left edge of a card's metrics, relative to the card. */
export const METRIC_LEFT = CARD_WIDTH + METRIC_GAP_X;

/** The box around a card's metrics, for the card at `card`. */
export function metricColumn<M>(card: { x: number; y: number }, slots: Array<MetricSlot<M>>) {
  const top = Math.min(...slots.map(slot => slot.y));
  const bottom = Math.max(...slots.map(slot => slot.y + METRIC_HEIGHT));
  return { x: card.x + METRIC_LEFT, y: card.y + top, width: METRIC_WIDTH, height: bottom - top };
}

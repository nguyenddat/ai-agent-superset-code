import type { DashboardDataset, DataLayer } from './types';

export const UNCLASSIFIED_LAYER_LABEL = 'Chưa phân tầng';

export function getDatasetName(dataset: DashboardDataset): string {
  return dataset.name || dataset.datasource_name || dataset.table_name || `Dataset ${dataset.id}`;
}

/** Layers in flow order: level by level, and in their sort order within a level. */
export function orderLayers(layers: DataLayer[]): DataLayer[] {
  return [...layers].sort((a, b) => a.level - b.level || a.sort_order - b.sort_order || a.id - b.id);
}

/** The levels in flow order, each with its layers; levels no layer uses are left out. */
export function layerLevels(layers: DataLayer[]): DataLayer[][] {
  const levels = new Map<number, DataLayer[]>();
  for (const layer of orderLayers(layers)) levels.set(layer.level, [...(levels.get(layer.level) ?? []), layer]);
  return [...levels.values()];
}

/**
 * Groups datasets by the data layer they are classified into in the data dictionary, in layer flow order, with
 * unclassified datasets last.
 */
export function groupDatasetsByLayer(
  datasets: DashboardDataset[],
  layers: DataLayer[],
  layerIdOf: (datasetId: number) => number | null | undefined,
): Array<{ label: string; layer: DataLayer | null; datasets: DashboardDataset[] }> {
  const ordered = orderLayers(layers);
  const groups = ordered.map(layer => ({ label: layer.name, layer, datasets: [] as DashboardDataset[] }));
  const unclassified = { label: UNCLASSIFIED_LAYER_LABEL, layer: null, datasets: [] as DashboardDataset[] };
  for (const dataset of datasets) {
    const group = groups.find(item => item.layer.id === layerIdOf(dataset.id)) ?? unclassified;
    group.datasets.push(dataset);
  }
  return [...groups, unclassified].filter(group => group.datasets.length > 0);
}

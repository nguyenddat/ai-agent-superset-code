import type { DashboardDataset } from './types';

export function getDatasetName(dataset: DashboardDataset): string {
  return dataset.name || dataset.datasource_name || dataset.table_name || `Dataset ${dataset.id}`;
}

export function getDatasetTableLabel(dataset: DashboardDataset): string {
  const table = dataset.table_name || dataset.datasource_name || dataset.name || `Dataset ${dataset.id}`;
  return dataset.schema && !table.startsWith(`${dataset.schema}.`) ? `${dataset.schema}.${table}` : table;
}

export function getDatasetSourceTable(dataset: DashboardDataset | undefined): string {
  const rawTableName = dataset?.table_name || dataset?.datasource_name || dataset?.name || '';
  return dataset?.schema && !rawTableName.startsWith(`${dataset.schema}.`)
    ? `${dataset.schema}.${rawTableName}`
    : rawTableName;
}

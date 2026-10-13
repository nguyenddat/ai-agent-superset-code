import type { Node } from '@xyflow/react';

export type DatasetColumn = {
  column_name: string;
  verbose_name?: string | null;
  type?: string | null;
  description?: string | null;
  is_dttm?: boolean;
};

export type DatasetMetric = {
  metric_name: string;
  verbose_name?: string | null;
  expression?: string | null;
  description?: string | null;
};

export type DashboardDataset = {
  id: number;
  name?: string | null;
  datasource_name?: string | null;
  schema?: string | null;
  table_name?: string | null;
  description?: string | null;
  database?: { database_name?: string | null };
  columns?: DatasetColumn[];
  metrics?: DatasetMetric[];
};

export type ColumnDictionary = {
  id: number;
  column_name: string;
  display_name: string;
  data_type: string;
  nullable: boolean;
  default_value: string | null;
  is_pk: boolean;
  is_fk: boolean;
  referenced_column: string | null;
  referenced_dataset_id: number | null;
  referenced_column_name: string | null;
  referenced_dataset_label?: string | null;
  is_unique: boolean;
  unit: string | null;
  format: string | null;
  business_term: string | null;
};

export type ReferenceDataset = {
  id: number;
  dataset_name: string;
  label: string;
  columns: string[];
};

export type ColumnDictionarySuggestion = {
  column_name: string;
  display_name: string;
  unit: string | null;
  business_term: string | null;
};

export type DatasetDictionary = {
  dataset_id: number;
  dataset_name: string;
  display_name: string;
  description: string | null;
  grain: string | null;
  create_column: string | null;
  dataset_type: 'base' | 'aggregate' | null;
  columns: ColumnDictionary[];
  read_only?: boolean;
};

export type SemanticField = {
  id: string;
  name: string;
  kind: 'column' | 'metric';
  type?: string | null;
  expression?: string | null;
  sourceTable?: string;
  sourceDatasetId?: number;
  datasetType?: 'base' | 'aggregate' | null;
  referencedDatasetId?: number | null;
  referencedColumnName?: string | null;
};

export type SemanticNodeData = SemanticField & {
  fields?: SemanticField[];
  onRemove: (id: string) => void;
  onRemoveField: (nodeId: string, fieldId: string) => void;
};

export type SemanticNode = Node<SemanticNodeData, 'semanticField'>;

export type ThemeMode = 'light' | 'dark';

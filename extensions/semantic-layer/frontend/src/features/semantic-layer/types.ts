export type DatasetColumn = {
  column_name: string;
  verbose_name?: string | null;
  type?: string | null;
  description?: string | null;
  is_dttm?: boolean;
};

export type DatasetMetric = {
  id: number;
  metric_name: string;
  verbose_name?: string | null;
  expression?: string | null;
  description?: string | null;
};

/** The intentionally redacted lifecycle state returned by metric-contract endpoints. */
export type MetricContract = {
  id: number;
  dataset_id: number;
  metric_id: number;
  metric_name: string;
  status: 'candidate' | 'approved' | 'revoked';
  owner_id: number | null;
  approver_id: number | null;
  approved_at: string | null;
  revoker_id: number | null;
  revoked_at: string | null;
  current: boolean;
};

export type MetricContractResponse = { contract: MetricContract };

export type MetricContractExecution = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  row_count: number;
  truncated: boolean;
  /** The SQL Superset ran, RLS included; only administrators receive it. */
  sql?: string | null;
};

/** Review state of a metric: `outdated` is a candidate or approval whose metric changed after it was recorded. */
export type MetricReviewState = 'not_started' | 'ineligible' | 'candidate' | 'approved' | 'outdated' | 'revoked';

export type MetricFormula = {
  aggregation: string;
  measure_column: string | null;
  measure_constant: string | null;
  condition: string | null;
  columns: string[];
};

export type MetricReviewItem = {
  dataset_id: number;
  metric_id: number;
  metric_name: string;
  verbose_name: string | null;
  description: string | null;
  expression: string | null;
  d3format: string | null;
  formula: MetricFormula | null;
  ineligibility: string | null;
  state: MetricReviewState;
  contract: (MetricContract & { owner_name: string | null; approver_name: string | null; revoker_name: string | null }) | null;
};

/** A dataset column a metric run may group by or filter on. */
export type MetricQueryColumn = {
  column_name: string;
  verbose_name: string | null;
  type: string | null;
  is_dttm: boolean;
  groupby: boolean;
  filterable: boolean;
};

export type MetricQueryDataset = { id: number; name: string; columns: MetricQueryColumn[] };

export type MetricReviewList = { datasets: MetricQueryDataset[]; metrics: MetricReviewItem[] };

export type MetricFilterOperator = '==' | '!=' | '<' | '<=' | '>' | '>=' | 'IN' | 'NOT IN';

export type MetricQueryFilter = { column: string; operator: MetricFilterOperator; value: string | number | boolean | Array<string | number> };

export type GlossaryStatus = 'draft' | 'approved' | 'revoked';
export type GlossaryProvenance = 'manual' | 'import' | 'ai_suggestion';
export type GlossaryLink = {
  id?: number;
  kind: 'dataset' | 'column' | 'metric';
  dataset_id: number;
  column_name?: string | null;
  metric_id?: number | null;
  dataset_name?: string | null;
  metric_name?: string | null;
};
export type GlossaryRevision = {
  id: number;
  revision_number: number;
  canonical_name: string;
  definition: string;
  synonyms: string[];
  provenance: GlossaryProvenance;
  status: GlossaryStatus;
  is_current: boolean;
  created_at?: string | null;
  approved_at?: string | null;
  revoked_at?: string | null;
  links: GlossaryLink[];
};
export type GlossaryTerm = {
  id: number;
  canonical_name: string;
  owner_id: number | null;
  steward_id: number | null;
  current_revision?: GlossaryRevision | null;
  revisions?: GlossaryRevision[];
};
export type GlossaryAuditEvent = {
  id: number;
  action: string;
  revision_number?: number | null;
  actor_id?: number | null;
  reason?: string | null;
  created_at?: string | null;
};
export type GlossaryTermPayload = {
  canonical_name: string;
  definition: string;
  synonyms: string[];
  owner_id: number | null;
  steward_id: number | null;
  provenance: GlossaryProvenance;
  links: Array<Pick<GlossaryLink, 'kind' | 'dataset_id' | 'column_name' | 'metric_id'>>;
};

export type SupersetDatabase = {
  id: number;
  database_name: string;
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
  database_name?: string | null;
  schema?: string | null;
  columns: string[];
  column_types?: Record<string, string>;
  /** Columns declared as primary key or unique in the data dictionary. */
  key_columns?: Record<string, { pk: boolean; unique: boolean }>;
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
  layer_id: number | null;
  columns: ColumnDictionary[];
  read_only?: boolean;
};

/**
 * Admin-defined warehouse layer. `level` is the direction data flows: layers feed the layers on higher levels, and
 * layers on one level sit side by side. `sort_order` orders all layers, level by level.
 */
export type DataLayer = {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  sort_order: number;
  level: number;
};

export type ThemeMode = 'light' | 'dark';

export type BusinessDomain = {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  dataset_ids: number[];
};

/** "flow": data moves from source into target. "relation": source references target inside one layer. */
export type LineageEdgeKind = 'flow' | 'relation';

export type LineageEdge = {
  source: number;
  target: number;
  kind: LineageEdgeKind;
  origin: 'dictionary' | 'manual';
  label: string | null;
  /** Display colour chosen by the user; null uses the default edge colour. */
  color: string | null;
  /** Cardinality at the source and target ends, inferred from FK declarations; absent on manual edges. */
  source_cardinality?: '1' | 'n';
  target_cardinality?: '1' | 'n';
  columns: string[];
  /** Column pairs behind the edge, oriented from its source dataset to its target; empty on manual edges. */
  column_links: Array<{ source: string; target: string }>;
};

export type ModelMetric = {
  id: number;
  dataset_id: number;
  metric_name: string;
  verbose_name: string | null;
  description: string | null;
  expression: string | null;
  /**
   * Dataset columns the expression uses: a `measure` is a value it aggregates, a `filter` picks the rows it covers.
   * Null when the expression could not be parsed.
   */
  columns: Array<{ name: string; role: 'measure' | 'filter' }> | null;
};

/** Stored business-view canvas: each domain's header and cells, and each table's cell, as [col, row] pairs. */
export type StoredCanvas = {
  domains: Array<{ key: string; header: [number, number]; cells: Array<[number, number]> }>;
  tables: Record<string, [number, number]>;
};

/** A lineage edge shape as stored: see EdgeGeometry, with points as [x, y] pairs. */
export type StoredEdgeShape = {
  style: 'orthogonal' | 'straight' | 'curved';
  coords: number[];
  waypoints: Array<[number, number]>;
  label: [number, number] | null;
  ports: [number, number];
};

/** Stored lineage canvas: the cards the user moved, keyed by node ID, and the edges the user shaped, by edge ID. */
export type StoredLineageCanvas = {
  nodes: Record<string, [number, number]>;
  edges: Record<string, StoredEdgeShape>;
};

export type BusinessModel = {
  /** Where the business view drew domains and tables last time, or null before the first save. */
  canvas: StoredCanvas | null;
  /** The lineage cards and edges the user placed by hand, or null before the first save. */
  lineage_canvas: StoredLineageCanvas | null;
  domains: BusinessDomain[];
  layers: DataLayer[];
  /** Data-dictionary classification of each dataset, keyed by dataset ID. */
  classifications: Record<string, { layer_id: number | null; dataset_type: DatasetDictionary['dataset_type'] }>;
  edges: LineageEdge[];
  metrics: ModelMetric[];
};

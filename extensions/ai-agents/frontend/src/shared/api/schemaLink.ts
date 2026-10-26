const SCHEMA_LINK_API = '/extensions/text-to-bi/superset-ai-agent/schema-link';

export type GraphLayer = { id: number; name: string; level: number };

export type GraphTable = { dataset_id: number; table: string; label: string | null; layer: GraphLayer | null };

export type GraphEdge = {
  id: number;
  from: number;
  from_column: string;
  to: number;
  to_column: string;
  cardinality: 'many_to_one' | 'one_to_one';
};

export type GraphView = {
  tables: GraphTable[];
  edges: GraphEdge[];
  excluded: Array<{ dataset_id: number; table: string; reason: string }>;
};

export type StageStatus = 'pending' | 'done' | 'failed';
type StageBase = { status: StageStatus; ms: number | null; error?: string };

type Located = { dataset_id: number; table: string; column: string | null; label: string };

export type GoalStage = StageBase & {
  measures?: Array<Located & {
    aggregation: string; source: string; indicator: { code: string; name: string | null; unit: string | null } | null;
  }>;
  group_by?: Array<Located & { time_grain: string | null }>;
  filters?: Array<Located & { operator: string; value: unknown; source: string }>;
  row_kinds?: Array<Located & { value: string; grain: string }>;
  limit?: number;
};

export type NodesStage = StageBase & { root?: number; terminals?: number[]; reasons?: Record<string, string[]> };

export type GraphStage = StageBase & Partial<GraphView>;

export type PathStep = { edge: number; from: number; to: number; forward: boolean; fanout: boolean; cost: number; on: string };

export type PathStage = StageBase & {
  algorithm?: 'dijkstra' | 'steiner' | 'steiner_heuristic';
  root?: number;
  cost?: number;
  fanout?: boolean;
  tables?: number[];
  steps?: PathStep[];
  alternatives?: Record<string, number[][]>;
  ambiguous?: boolean;
  unreachable?: number[];
  problems?: Array<{ table: number; kind: string; message: string; options: string[] }>;
};

export type AnalysisTrace = {
  status: string;
  message: string | null;
  sql: string | null;
  stages: { goal: GoalStage; nodes: NodesStage; graph: GraphStage; path: PathStage };
};

async function readJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message || body.error || `Yêu cầu thất bại (${response.status}).`);
  return body as T;
}

export async function canUseSchemaLinkLab(): Promise<boolean> {
  try {
    const body = await readJson<{ can_use_lab: boolean }>(await fetch(`${SCHEMA_LINK_API}/access`, { credentials: 'same-origin' }));
    return body.can_use_lab === true;
  } catch {
    return false;
  }
}

export async function getSchemaGraph(databaseId: number): Promise<{ tables: unknown[]; edges: unknown[]; database: { name: string } }> {
  return readJson(await fetch(`${SCHEMA_LINK_API}/graph?database_id=${encodeURIComponent(databaseId)}`, { credentials: 'same-origin' }));
}

export async function analyzeGoal(databaseId: number, goal: unknown): Promise<AnalysisTrace> {
  const csrf = await readJson<{ result: string }>(await fetch('/api/v1/security/csrf_token/', { credentials: 'same-origin' }));
  const response = await fetch(`${SCHEMA_LINK_API}/analyze`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf.result },
    body: JSON.stringify({ database_id: databaseId, goal }),
  });
  return readJson<AnalysisTrace>(response);
}

/** The raw schema graph turned into the view the analysis trace draws, for drawing before any analysis. */
export function graphViewOf(payload: { tables: any[]; edges: any[]; excluded?: any[] }): GraphView {
  return {
    tables: payload.tables.map(table => ({
      dataset_id: table.dataset_id, table: table.table, label: table.label ?? null, layer: table.layer ?? null,
    })),
    edges: payload.edges.map(edge => ({
      id: edge.id, from: edge.from.dataset_id, from_column: edge.from.column, to: edge.to.dataset_id,
      to_column: edge.to.column, cardinality: edge.cardinality,
    })),
    excluded: payload.excluded ?? [],
  };
}

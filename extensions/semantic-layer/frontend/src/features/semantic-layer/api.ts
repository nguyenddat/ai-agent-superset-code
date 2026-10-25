import { EXPERT_RULES_API, SEMANTIC_LAYER_API } from './constants';

export const expertRulesApi = {
  rules: `${EXPERT_RULES_API}/expert-rules`,
  options: `${EXPERT_RULES_API}/expert-rules/options`,
  draft: (ruleId: number) => `${EXPERT_RULES_API}/expert-rules/${encodeURIComponent(ruleId)}/draft`,
  approve: (ruleId: number) => `${EXPERT_RULES_API}/expert-rules/${encodeURIComponent(ruleId)}/approve`,
  revoke: (ruleId: number) => `${EXPERT_RULES_API}/expert-rules/${encodeURIComponent(ruleId)}/revoke`,
  audit: (ruleId: number) => `${EXPERT_RULES_API}/expert-rules/${encodeURIComponent(ruleId)}/audit`,
};

export const semanticLayerApi = {
  access: `${SEMANTIC_LAYER_API}/access`,
  datasetDictionary: (datasetId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/dictionary`
  ),
  suggestColumnDictionary: (datasetId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/dictionary/suggest`
  ),
  referenceOptions: `${SEMANTIC_LAYER_API}/datasets/reference-options`,
  businessModel: (databaseId: number) => `${SEMANTIC_LAYER_API}/business-model?database_id=${encodeURIComponent(databaseId)}`,
  businessCanvas: (databaseId: number) => `${SEMANTIC_LAYER_API}/business-canvas?database_id=${encodeURIComponent(databaseId)}`,
  lineageCanvas: (databaseId: number) => `${SEMANTIC_LAYER_API}/lineage-canvas?database_id=${encodeURIComponent(databaseId)}`,
  businessDomains: `${SEMANTIC_LAYER_API}/business-domains`,
  businessDomain: (domainId: number) => `${SEMANTIC_LAYER_API}/business-domains/${encodeURIComponent(domainId)}`,
  lineageEdges: `${SEMANTIC_LAYER_API}/lineage-edges`,
  lineageEdgeColor: `${SEMANTIC_LAYER_API}/lineage-edges/color`,
  dataLayers: `${SEMANTIC_LAYER_API}/data-layers`,
  dataLayer: (layerId: number) => `${SEMANTIC_LAYER_API}/data-layers/${encodeURIComponent(layerId)}`,
  dataLayersOrder: `${SEMANTIC_LAYER_API}/data-layers/order`,
  metricContracts: (databaseId: number) => `${SEMANTIC_LAYER_API}/metric-contracts?database_id=${encodeURIComponent(databaseId)}`,
  metricContractCandidate: (datasetId: number, metricId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/metrics/${encodeURIComponent(metricId)}/contract/candidate`
  ),
  metricContractApprove: (datasetId: number, metricId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/metrics/${encodeURIComponent(metricId)}/contract/approve`
  ),
  metricContractRevoke: (datasetId: number, metricId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/metrics/${encodeURIComponent(metricId)}/contract/revoke`
  ),
  metricContractEvents: (datasetId: number, metricId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/metrics/${encodeURIComponent(metricId)}/contract/events`
  ),
  metricDefinition: (datasetId: number, metricId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/metrics/${encodeURIComponent(metricId)}/definition`
  ),
  metricContractExecute: (datasetId: number, metricId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/metrics/${encodeURIComponent(metricId)}/semantic-query/execute`
  ),
  glossary: `${SEMANTIC_LAYER_API}/glossary`,
  glossaryOptions: `${SEMANTIC_LAYER_API}/glossary/options`,
  glossaryTerm: (termId: number) => `${SEMANTIC_LAYER_API}/glossary/${encodeURIComponent(termId)}`,
  glossaryDraft: (termId: number) => `${SEMANTIC_LAYER_API}/glossary/${encodeURIComponent(termId)}/draft`,
  glossaryApprove: (termId: number) => `${SEMANTIC_LAYER_API}/glossary/${encodeURIComponent(termId)}/approve`,
  glossaryRevoke: (termId: number) => `${SEMANTIC_LAYER_API}/glossary/${encodeURIComponent(termId)}/revoke`,
  glossaryAudit: (termId: number) => `${SEMANTIC_LAYER_API}/glossary/${encodeURIComponent(termId)}/audit`,
  glossaryDiscovery: `${SEMANTIC_LAYER_API}/glossary/discovery`,
} as const;

export const supersetApi = {
  csrfToken: '/api/v1/security/csrf_token/',
  databases: `/api/v1/database/?q=${encodeURIComponent('(order_column:database_name,order_direction:asc,page_size:100)')}`,
  dataset: (datasetId: number) => `/api/v1/dataset/${encodeURIComponent(datasetId)}`,
  databaseDatasets: (databaseId: number, page: number) => `/api/v1/dataset/?q=${encodeURIComponent(
    `(filters:!((col:database,opr:rel_o_m,value:${databaseId})),page:${page},page_size:100)`,
  )}`,
} as const;

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const payload = await response.json().catch(() => ({}));
  return payload?.message || payload?.error || fallback;
}

/** Sends a JSON request to the extension API with Superset's CSRF token and returns the parsed body. */
export async function requestJson<T>(url: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE', body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') {
    const csrfResponse = await fetch(supersetApi.csrfToken, { credentials: 'same-origin', headers });
    if (!csrfResponse.ok) throw new Error(`Không lấy được CSRF token (${csrfResponse.status}).`);
    const csrfPayload = await csrfResponse.json();
    const csrfToken = csrfPayload?.result || csrfPayload?.csrf_token;
    if (!csrfToken || typeof csrfToken !== 'string') throw new Error('Khong nhan duoc CSRF token.');
    headers['X-CSRFToken'] = csrfToken;
  }
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await errorMessage(response, `Yêu cầu thất bại (${response.status}).`));
  return await response.json() as T;
}

import { SEMANTIC_LAYER_API } from './constants';

export const semanticLayerApi = {
  access: `${SEMANTIC_LAYER_API}/access`,
  datasetDictionary: (datasetId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/dictionary`
  ),
  suggestColumnDictionary: (datasetId: number) => (
    `${SEMANTIC_LAYER_API}/dataset/${encodeURIComponent(datasetId)}/dictionary/suggest`
  ),
  referenceOptions: `${SEMANTIC_LAYER_API}/datasets/reference-options`,
  dashboardDatasets: (dashboardId: string) => (
    `${SEMANTIC_LAYER_API}/dashboard/${encodeURIComponent(dashboardId)}/datasets`
  ),
} as const;

export const supersetApi = {
  csrfToken: '/api/v1/security/csrf_token/',
  dashboardDatasets: (dashboardId: string) => `/api/v1/dashboard/${encodeURIComponent(dashboardId)}/datasets`,
  dataset: (datasetId: number) => `/api/v1/dataset/${encodeURIComponent(datasetId)}`,
  datasets: (page: number) => `/api/v1/dataset/?q=${encodeURIComponent(`(page:${page},page_size:100)`)}`,
} as const;

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
} as const;

export const supersetApi = {
  csrfToken: '/api/v1/security/csrf_token/',
  databases: `/api/v1/database/?q=${encodeURIComponent('(order_column:database_name,order_direction:asc,page_size:100)')}`,
  dataset: (datasetId: number) => `/api/v1/dataset/${encodeURIComponent(datasetId)}`,
  databaseDatasets: (databaseId: number, page: number) => `/api/v1/dataset/?q=${encodeURIComponent(
    `(filters:!((col:database,opr:rel_o_m,value:${databaseId})),page:${page},page_size:100)`,
  )}`,
} as const;

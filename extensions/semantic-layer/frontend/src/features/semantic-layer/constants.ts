export const SEMANTIC_LAYER_API = '/extensions/text-to-bi/superset-semantic-layer/semantic-layer';

export const SEMANTIC_LAYER_PAGE = '/semantic-layer/';

export type SemanticLayerModule = 'dictionary' | 'semantic' | 'metrics' | 'glossary';

export const semanticLayerModules: Array<{ id: SemanticLayerModule; label: string; description: string }> = [
  { id: 'dictionary', label: 'Data Dictionary', description: 'Chỉnh metadata datasets và columns' },
  { id: 'semantic', label: 'Semantic Layer', description: 'Nghiệp vụ và data lineage' },
  { id: 'metrics', label: 'Metrics', description: 'Duyệt định nghĩa metric và chạy thử' },
  { id: 'glossary', label: 'Business Glossary', description: 'Governed business terms' },
];

export function semanticLayerModuleHref(module: SemanticLayerModule): string {
  return `${SEMANTIC_LAYER_PAGE}?module=${module}`;
}

export function semanticLayerModuleFromLocation(): SemanticLayerModule {
  const module = new URLSearchParams(window.location.search).get('module');
  return semanticLayerModules.some(item => item.id === module) ? module as SemanticLayerModule : 'dictionary';
}

export const semanticLayerEvents = {
  moduleRequest: 'semantic-layer-module-request',
} as const;

export const semanticLayerSelectors = {
  header: 'header#main-menu',
  navbar: 'ul[data-test="navbar-top"]',
  navItem: '[data-test="semantic-layer-nav-item"]',
  navDropdown: '[data-test="semantic-layer-nav-dropdown"]',
} as const;

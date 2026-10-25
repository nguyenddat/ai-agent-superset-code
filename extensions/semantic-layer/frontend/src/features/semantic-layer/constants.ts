export const SEMANTIC_LAYER_API = '/extensions/text-to-bi/superset-semantic-layer/semantic-layer';

export const EXPERT_RULES_API = '/extensions/text-to-bi/superset-semantic-layer/expert-rules';

export const SEMANTIC_LAYER_PAGE = '/semantic-layer/';

export type SemanticLayerModule = 'dictionary' | 'semantic' | 'metrics' | 'glossary' | 'rules';

export const semanticLayerModules: Array<{ id: SemanticLayerModule; label: string; description: string }> = [
  { id: 'dictionary', label: 'Data Dictionary', description: 'Chỉnh metadata datasets và columns' },
  { id: 'semantic', label: 'Semantic Model', description: 'Nghiệp vụ và data lineage' },
  { id: 'metrics', label: 'Metrics', description: 'Duyệt định nghĩa metric và chạy thử' },
  { id: 'glossary', label: 'Business Glossary', description: 'Thuật ngữ nghiệp vụ được quản trị' },
  { id: 'rules', label: 'Expert Rules', description: 'Quy tắc nghiệp vụ của chuyên gia' },
];

/**
 * The navbar shows one menu per audience: data engineers model datasets, business owners govern what AI Agent may
 * use. Both menus open the same page.
 */
export const semanticLayerModuleGroups: Array<{ id: string; label: string; modules: SemanticLayerModule[] }> = [
  { id: 'modeling', label: 'Mô hình dữ liệu', modules: ['dictionary', 'semantic'] },
  { id: 'governance', label: 'Quản trị nghiệp vụ', modules: ['metrics', 'glossary', 'rules'] },
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

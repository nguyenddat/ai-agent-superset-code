export const SEMANTIC_LAYER_API = '/extensions/text-to-bi/superset-semantic-layer/semantic-layer';

export const semanticLayerEvents = {
  expand: 'text-to-bi:expand-semantic-layer',
  fieldsChange: 'semantic-fields-change',
  open: 'text-to-bi:open-semantic-layer',
  pointerDrop: 'semantic-field-pointer-drop',
} as const;

export const semanticLayerSelectors = {
  actionsMenu: 'ul[role="menu"], ul.ant-dropdown-menu',
  actionsTrigger: 'button[data-test="actions-trigger"], button[aria-label="Menu actions trigger"]',
  menuDivider: '[data-test="semantic-layer-menu-divider"]',
  menuItem: '[data-test="semantic-layer-menu-item"]',
} as const;

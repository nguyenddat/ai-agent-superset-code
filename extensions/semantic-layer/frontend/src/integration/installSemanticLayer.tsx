import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom';
import { Boxes, Braces, CalendarClock, Check, ChevronDown, Database, Layers3, LoaderCircle, Table2 } from 'lucide-react';
import '@xyflow/react/dist/style.css';
import { DataDictionary } from '../features/semantic-layer/DataDictionary';
import { SemanticCanvas } from '../features/semantic-layer/SemanticCanvas';
import { semanticLayerApi, supersetApi } from '../features/semantic-layer/api';
import {
  SEMANTIC_LAYER_PAGE,
  semanticLayerEvents,
  semanticLayerModuleFromLocation,
  semanticLayerModuleHref,
  semanticLayerModules,
  semanticLayerSelectors,
} from '../features/semantic-layer/constants';
import type { SemanticLayerModule } from '../features/semantic-layer/constants';
import { getDatasetName, getDatasetSourceTable } from '../features/semantic-layer/datasets';
import type { DashboardDataset, DatasetDictionary, SemanticField, SupersetDatabase, ThemeMode } from '../features/semantic-layer/types';

function activeSupersetTheme(): ThemeMode {
  const luminance = (color: string) => {
    const match = color.match(/rgba?\(([^)]+)\)/i);
    if (!match) return null;
    const values = match[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    if (values.length < 3 || values.some(value => !Number.isFinite(value))) return null;
    if (values.length > 3 && values[3] === 0) return null;
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2];
  };
  const body = getComputedStyle(document.body);
  const background = luminance(body.backgroundColor);
  if (background !== null) return background < 128 ? 'dark' : 'light';
  const foreground = luminance(body.color);
  return foreground !== null && foreground > 128 ? 'dark' : 'light';
}

function SemanticLayerPage() {
  const [databases, setDatabases] = useState<SupersetDatabase[]>([]);
  const [selectedDatabase, setSelectedDatabase] = useState<number | null>(null);
  const [datasets, setDatasets] = useState<DashboardDataset[]>([]);
  const [dictionaryByDataset, setDictionaryByDataset] = useState<Record<number, DatasetDictionary>>({});
  const [dictionariesReady, setDictionariesReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedDataset, setSelectedDataset] = useState<number | null>(null);
  const [themeMode, setThemeMode] = useState(activeSupersetTheme);
  const [columnsExpanded, setColumnsExpanded] = useState(true);
  const [metricsExpanded, setMetricsExpanded] = useState(true);
  const [canvasFieldIds, setCanvasFieldIds] = useState<string[]>([]);
  const [activeModule, setActiveModule] = useState<SemanticLayerModule>(semanticLayerModuleFromLocation);
  const [dictionaryDirty, setDictionaryDirty] = useState(false);

  const canLeaveDictionary = () => (
    !dictionaryDirty || window.confirm('Bạn có thay đổi chưa lưu trong Data Dictionary. Tiếp tục và bỏ các thay đổi này?')
  );

  // The Superset navbar dropdown asks for a module change; the page owns the unsaved-changes check and the URL.
  useEffect(() => {
    const onModuleRequest = (event: Event) => {
      const module = (event as CustomEvent<SemanticLayerModule>).detail;
      if (module === activeModule) return;
      if (activeModule === 'dictionary' && !canLeaveDictionary()) return;
      window.history.pushState(null, '', semanticLayerModuleHref(module));
      setActiveModule(module);
    };
    const onPopState = () => setActiveModule(semanticLayerModuleFromLocation());
    window.addEventListener(semanticLayerEvents.moduleRequest, onModuleRequest);
    window.addEventListener('popstate', onPopState);
    return () => {
      window.removeEventListener(semanticLayerEvents.moduleRequest, onModuleRequest);
      window.removeEventListener('popstate', onPopState);
    };
  });

  const selectDataset = (datasetId: number) => {
    if (datasetId === selectedDataset) return;
    if (activeModule === 'dictionary' && !canLeaveDictionary()) return;
    setSelectedDataset(datasetId);
  };

  const selectDatabase = (databaseId: number) => {
    if (activeModule === 'dictionary' && !canLeaveDictionary()) return;
    setSelectedDatabase(databaseId);
  };

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const syncTheme = () => setThemeMode(activeSupersetTheme());
    const observer = new MutationObserver(syncTheme);
    observer.observe(document.body, { attributes: true, childList: true, subtree: true });
    observer.observe(document.head, { childList: true });
    const syncCanvasFields = (event: Event) => {
      setCanvasFieldIds((event as CustomEvent<string[]>).detail ?? []);
    };
    window.addEventListener(semanticLayerEvents.fieldsChange, syncCanvasFields);
    return () => {
      observer.disconnect();
      window.removeEventListener(semanticLayerEvents.fieldsChange, syncCanvasFields);
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  useEffect(() => {
    let active = true;
    fetch(supersetApi.databases, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(async response => {
        if (!response.ok) throw new Error(`Không tải được databases (${response.status}).`);
        const payload = await response.json();
        if (!active) return;
        const result = Array.isArray(payload?.result) ? payload.result as SupersetDatabase[] : [];
        setDatabases(result);
        setSelectedDatabase(result[0]?.id ?? null);
        if (result.length === 0) setLoading(false);
      })
      .catch(reason => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : 'Không tải được databases.');
        setLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (selectedDatabase === null) return undefined;
    let active = true;
    setLoading(true);
    setError('');
    (async () => {
      const allDatasets: DashboardDataset[] = [];
      let page = 0;
      let count = Number.POSITIVE_INFINITY;
      while (allDatasets.length < count) {
        const response = await fetch(supersetApi.databaseDatasets(selectedDatabase, page), {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        if (!response.ok) throw new Error(`Không tải được datasets (${response.status}).`);
        const payload = await response.json();
        const results = Array.isArray(payload?.result) ? payload.result as DashboardDataset[] : [];
        allDatasets.push(...results);
        count = Number(payload?.count ?? allDatasets.length);
        if (results.length === 0) break;
        page += 1;
      }
      return allDatasets;
    })()
      .then(async allDatasets => {
        const hydrated = await Promise.all(allDatasets.map(async dataset => {
          if ((dataset.columns?.length ?? 0) > 0) return dataset;
          try {
            const detailResponse = await fetch(supersetApi.dataset(dataset.id), {
              credentials: 'same-origin',
              headers: { Accept: 'application/json' },
            });
            if (!detailResponse.ok) return dataset;
            const detailPayload = await detailResponse.json();
            const detail = detailPayload?.result as DashboardDataset | undefined;
            return detail ? { ...dataset, ...detail, id: dataset.id } : dataset;
          } catch {
            return dataset;
          }
        }));
        if (!active) return;
        setDatasets(hydrated);
        setSelectedDataset(hydrated[0]?.id ?? null);
        setLoading(false);
      })
      .catch(reason => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : 'Không tải được dữ liệu semantic.');
        setLoading(false);
      });
    return () => { active = false; };
  }, [selectedDatabase]);

  const currentDataset = datasets.find(dataset => dataset.id === selectedDataset);
  const currentModule = semanticLayerModules.find(module => module.id === activeModule) ?? semanticLayerModules[0];
  const sourceTable = getDatasetSourceTable(currentDataset);

  useEffect(() => {
    let active = true;
    if (datasets.length === 0) {
      setDictionaryByDataset({});
      setDictionariesReady(true);
      return () => { active = false; };
    }
    setDictionariesReady(false);
    Promise.all(datasets.map(async dataset => {
      try {
        const response = await fetch(semanticLayerApi.datasetDictionary(dataset.id), {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        if (!response.ok) return null;
        return await response.json() as DatasetDictionary;
      } catch {
        return null;
      }
    })).then(dictionaries => {
      if (!active) return;
      setDictionaryByDataset(Object.fromEntries(dictionaries.filter((item): item is DatasetDictionary => item !== null).map(item => [item.dataset_id, item])));
      setDictionariesReady(true);
    });
    return () => { active = false; };
  }, [datasets]);
  const startDrag = (event: React.PointerEvent<HTMLElement>, item: SemanticField) => {
    if (event.button !== 0) return;
    const { clientX: startX, clientY: startY, pointerId } = event;
    let dragging = false;
    let activeCanvas: Element | null = null;
    const clearDragState = () => {
      activeCanvas?.classList.remove('is-drop-target');
      document.body.classList.remove('sl-dragging-field');
    };
    const onPointerMove = (moveEvent: PointerEvent) => {
      if (moveEvent.pointerId !== pointerId) return;
      if (!dragging && Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < 6) return;
      dragging = true;
      moveEvent.preventDefault();
      const targetCanvas = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY)?.closest('.sl-flow-canvas') ?? null;
      if (targetCanvas !== activeCanvas) {
        activeCanvas?.classList.remove('is-drop-target');
        activeCanvas = targetCanvas;
        activeCanvas?.classList.add('is-drop-target');
      }
      document.body.classList.add('sl-dragging-field');
    };
    const finishDrag = (upEvent: PointerEvent) => {
      if (upEvent.pointerId !== pointerId) return;
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', finishDrag);
      window.removeEventListener('pointercancel', finishDrag);
      clearDragState();
      if (!dragging) return;
      const targetCanvas = document.elementFromPoint(upEvent.clientX, upEvent.clientY)?.closest('.sl-flow-canvas');
      if (targetCanvas) {
        window.dispatchEvent(new CustomEvent(semanticLayerEvents.pointerDrop, {
          detail: { item, clientX: upEvent.clientX, clientY: upEvent.clientY },
        }));
      }
    };
    window.addEventListener('pointermove', onPointerMove, { passive: false });
    window.addEventListener('pointerup', finishDrag);
    window.addEventListener('pointercancel', finishDrag);
  };

  return (
    <div className="sl-page" data-theme-mode={themeMode}>
      <section className="sl-panel" aria-label="Semantic Layer Explorer">
        <div className="sl-panel-workspace">
          <header className="sl-header">
            <div className="sl-header-icon"><Layers3 /></div>
            <div className="sl-header-copy">
              <h2>{currentModule.label}</h2>
              <p>{currentModule.description}</p>
            </div>
            <label className="sl-header-select" title="Database">
              <Database />
              <select aria-label="Database" value={selectedDatabase ?? ''} disabled={databases.length === 0} onChange={event => selectDatabase(Number(event.target.value))}>
                {databases.map(database => <option key={database.id} value={database.id}>{database.database_name}</option>)}
              </select>
            </label>
            <label className="sl-header-select sl-dataset-select" title="Dataset">
              <Table2 />
              <span className="sl-select-caption">Datasets ({datasets.length})</span>
              <select aria-label="Dataset" value={selectedDataset ?? ''} disabled={loading || datasets.length === 0} onChange={event => selectDataset(Number(event.target.value))}>
                {datasets.map(dataset => <option key={dataset.id} value={dataset.id}>{getDatasetName(dataset)}</option>)}
              </select>
            </label>
          </header>

          {loading ? (
            <div className="sl-state"><LoaderCircle className="sl-spin" /><span>Đang tải metadata database…</span></div>
          ) : error ? (
            <div className="sl-state sl-error"><p>{error}</p></div>
          ) : (
            <div className="sl-content">
              {currentDataset ? (
                activeModule === 'dictionary' ? (
                  <main className="sl-dictionary-main">
                    <DataDictionary key={currentDataset.id} dataset={currentDataset} onDirtyChange={setDictionaryDirty} />
                  </main>
                ) : (
                <main className="sl-details">
                  <div className="sl-workspace">
                    <aside className="sl-field-palette" aria-label="Trường dữ liệu có thể kéo">
                      <div className="sl-section-heading"><span><Boxes /> Trường dữ liệu</span><span className="sl-count">{(currentDataset.columns?.length ?? 0) + (currentDataset.metrics?.length ?? 0)}</span></div>
                      <p className="sl-palette-hint">Kéo column hoặc metric vào canvas để bắt đầu xây dựng.</p>
                      <section className="sl-palette-group">
                        <button className="sl-palette-label sl-palette-toggle" type="button" aria-expanded={columnsExpanded} aria-controls="sl-columns-list" onClick={() => setColumnsExpanded(value => !value)}>
                          <span>COLUMNS</span><ChevronDown className={columnsExpanded ? '' : 'is-collapsed'} />
                        </button>
                        <div id="sl-columns-list" className={`sl-palette-items${columnsExpanded ? ' is-expanded' : ''}`}>
                          <div className="sl-palette-items-inner">
                            {(currentDataset.columns ?? []).map(column => {
                              const dictionaryColumn = dictionaryByDataset[currentDataset.id]?.columns.find(item => item.column_name === column.column_name);
                              const item: SemanticField = { id: `column-${currentDataset.id}-${column.column_name}`, name: dictionaryColumn?.display_name || column.verbose_name || column.column_name, kind: 'column', type: column.is_dttm ? 'TIME' : column.type, sourceTable, sourceDatasetId: currentDataset.id, datasetType: dictionaryByDataset[currentDataset.id]?.dataset_type ?? null, referencedDatasetId: dictionaryColumn?.referenced_dataset_id, referencedColumnName: dictionaryColumn?.referenced_column_name };
                              const inCanvas = canvasFieldIds.includes(item.id);
                              return (
                                <article className={`sl-field-card${inCanvas ? ' is-in-canvas' : ''}`} key={item.id} onPointerDown={event => startDrag(event, item)}>
                                  <div className="sl-item-icon">{column.is_dttm ? <CalendarClock /> : <Braces />}</div>
                                  <div className="sl-item-copy"><strong>{item.name}</strong>{column.verbose_name ? <code>{column.column_name}</code> : null}</div>
                                  <div className="sl-field-card-trailing">
                                    {inCanvas ? <span className="sl-field-status" title="Đã có trên canvas"><Check /> Đã thêm</span> : null}
                                    <span className="sl-type">{item.type || 'COLUMN'}</span>
                                  </div>
                                </article>
                              );
                            })}
                            {(currentDataset.columns ?? []).length === 0 ? <p className="sl-empty">Chưa có cột.</p> : null}
                          </div>
                        </div>
                      </section>
                      <section className="sl-palette-group">
                        <button className="sl-palette-label sl-palette-toggle" type="button" aria-expanded={metricsExpanded} aria-controls="sl-metrics-list" onClick={() => setMetricsExpanded(value => !value)}>
                          <span>METRICS</span><ChevronDown className={metricsExpanded ? '' : 'is-collapsed'} />
                        </button>
                        <div id="sl-metrics-list" className={`sl-palette-items${metricsExpanded ? ' is-expanded' : ''}`}>
                          <div className="sl-palette-items-inner">
                            {(currentDataset.metrics ?? []).map(metric => {
                              const item = { id: `metric-${currentDataset.id}-${metric.metric_name}`, name: metric.verbose_name || metric.metric_name, kind: 'metric' as const, expression: metric.expression };
                              const inCanvas = canvasFieldIds.includes(item.id);
                              return (
                                <article className={`sl-field-card${inCanvas ? ' is-in-canvas' : ''}`} key={item.id} onPointerDown={event => startDrag(event, item)}>
                                  <div className="sl-item-icon"><Layers3 /></div>
                                  <div className="sl-item-copy"><strong>{item.name}</strong>{metric.expression ? <code>{metric.expression}</code> : null}</div>
                                  {inCanvas ? <div className="sl-field-card-trailing"><span className="sl-field-status" title="Đã có trên canvas"><Check /> Đã thêm</span></div> : null}
                                </article>
                              );
                            })}
                            {(currentDataset.metrics ?? []).length === 0 ? <p className="sl-empty">Dataset chưa có metric.</p> : null}
                          </div>
                        </div>
                      </section>
                    </aside>

                    <section className="sl-canvas" aria-label="Canvas semantic layer">
                      <SemanticCanvas themeMode={themeMode} datasets={datasets} dictionaries={dictionaryByDataset} dictionariesReady={dictionariesReady} />
                    </section>
                  </div>
                </main>
                )
              ) : (
                <div className="sl-no-dataset">
                  <Database />
                  <strong>{selectedDatabase === null ? 'Chưa có database' : 'Database chưa có dataset'}</strong>
                  <span>Tạo dataset trong Superset để bắt đầu xây dựng semantic layer.</span>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

/** Adds an admin-only Semantic Layer entry to Superset's navigation bar and renders its page. */
export function installSemanticLayer(): () => void {
  let host: HTMLDivElement | undefined;
  let frame = 0;

  const isSemanticLayerPage = () => `${window.location.pathname.replace(/\/$/, '')}/` === SEMANTIC_LAYER_PAGE;

  let dropdown: HTMLDivElement | undefined;
  let closeTimer = 0;

  const openDropdown = (anchor: Element) => {
    window.clearTimeout(closeTimer);
    if (!dropdown) {
      dropdown = document.createElement('div');
      dropdown.className = 'sl-nav-dropdown';
      dropdown.setAttribute('role', 'menu');
      dropdown.setAttribute('data-test', 'semantic-layer-nav-dropdown');
      dropdown.innerHTML = semanticLayerModules.map(module => (
        `<a role="menuitem" data-module="${module.id}" href="${semanticLayerModuleHref(module.id)}"><strong>${module.label}</strong><span>${module.description}</span></a>`
      )).join('');
      dropdown.addEventListener('mouseenter', () => window.clearTimeout(closeTimer));
      dropdown.addEventListener('mouseleave', scheduleClose);
      dropdown.addEventListener('click', event => {
        const link = (event.target as Element).closest<HTMLAnchorElement>('a[data-module]');
        if (!link) return;
        closeDropdown();
        if (!isSemanticLayerPage()) return;
        // Already on the page: switch modules in place so unsaved dictionary edits can be confirmed first.
        event.preventDefault();
        window.dispatchEvent(new CustomEvent(semanticLayerEvents.moduleRequest, { detail: link.dataset.module }));
      });
      document.body.append(dropdown);
    }
    const rect = anchor.getBoundingClientRect();
    dropdown.style.top = `${rect.bottom}px`;
    dropdown.style.left = `${rect.left}px`;
    dropdown.setAttribute('data-theme-mode', activeSupersetTheme());
    const currentModule = isSemanticLayerPage() ? semanticLayerModuleFromLocation() : null;
    dropdown.querySelectorAll<HTMLAnchorElement>('a[data-module]').forEach(link => {
      link.classList.toggle('is-active', link.dataset.module === currentModule);
    });
    dropdown.classList.add('is-open');
  };

  function closeDropdown() {
    window.clearTimeout(closeTimer);
    dropdown?.classList.remove('is-open');
  }

  function scheduleClose() {
    window.clearTimeout(closeTimer);
    closeTimer = window.setTimeout(closeDropdown, 150);
  }

  const unmountPage = () => {
    if (!host) return;
    ReactDOM.unmountComponentAtNode(host);
    host.remove();
    host = undefined;
  };

  const sync = () => {
    frame = 0;
    const navbar = document.querySelector<HTMLUListElement>(semanticLayerSelectors.navbar);
    if (navbar) {
      let item = navbar.querySelector(semanticLayerSelectors.navItem);
      if (!item) {
        item = document.createElement('li');
        item.className = 'ant-menu-item ant-menu-item-only-child';
        item.setAttribute('role', 'menuitem');
        item.setAttribute('data-test', 'semantic-layer-nav-item');
        item.setAttribute('aria-haspopup', 'menu');
        item.innerHTML = `<span class="ant-menu-title-content"><a class="sl-nav-trigger" href="${SEMANTIC_LAYER_PAGE}">Semantic Layer<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></a></span>`;
        const trigger = item;
        trigger.addEventListener('mouseenter', () => openDropdown(trigger));
        trigger.addEventListener('mouseleave', scheduleClose);
        trigger.addEventListener('focusin', () => openDropdown(trigger));
        trigger.addEventListener('click', event => {
          event.preventDefault();
          if (dropdown?.classList.contains('is-open')) closeDropdown();
          else openDropdown(trigger);
        });
        navbar.append(item);
      }
      item.classList.toggle('ant-menu-item-selected', isSemanticLayerPage());
    }

    if (!isSemanticLayerPage()) {
      unmountPage();
      return;
    }
    const header = document.querySelector<HTMLElement>(semanticLayerSelectors.header);
    if (host || !header) return;
    host = document.createElement('div');
    host.style.setProperty('--sl-nav-height', `${header.offsetHeight}px`);
    header.after(host);
    ReactDOM.render(<SemanticLayerPage />, host);
  };

  const schedule = () => {
    if (!frame) frame = window.requestAnimationFrame(sync);
  };
  const observer = new MutationObserver(schedule);

  fetch(semanticLayerApi.access, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  })
    .then(response => response.ok ? response.json() : null)
    .then(payload => {
      if (payload?.is_admin !== true) return;
      observer.observe(document.body, { childList: true, subtree: true });
      window.addEventListener('popstate', schedule);
      sync();
    })
    .catch(() => undefined);

  return () => {
    observer.disconnect();
    window.removeEventListener('popstate', schedule);
    if (frame) window.cancelAnimationFrame(frame);
    window.clearTimeout(closeTimer);
    document.querySelector(semanticLayerSelectors.navItem)?.remove();
    dropdown?.remove();
    unmountPage();
  };
}

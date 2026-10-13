import React, { useEffect, useState } from 'react';
import ReactDOM, { createPortal } from 'react-dom';
import { BookOpen, Boxes, Braces, CalendarClock, Check, ChevronDown, Database, GitBranch, Layers3, LoaderCircle, PanelRightClose, PanelRightOpen, Plus, Search, X } from 'lucide-react';
import '@xyflow/react/dist/style.css';
import { DataDictionary } from '../features/semantic-layer/DataDictionary';
import { SemanticCanvas } from '../features/semantic-layer/SemanticCanvas';
import { semanticLayerApi, supersetApi } from '../features/semantic-layer/api';
import { semanticLayerEvents, semanticLayerSelectors } from '../features/semantic-layer/constants';
import { getDatasetName, getDatasetSourceTable, getDatasetTableLabel } from '../features/semantic-layer/datasets';
import type { DashboardDataset, DatasetDictionary, SemanticField, ThemeMode } from '../features/semantic-layer/types';

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

function SemanticLayerPanel({ dashboardId }: { dashboardId: string }) {
  const [datasets, setDatasets] = useState<DashboardDataset[]>([]);
  const [dictionaryByDataset, setDictionaryByDataset] = useState<Record<number, DatasetDictionary>>({});
  const [dictionariesReady, setDictionariesReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedDataset, setSelectedDataset] = useState<number | null>(null);
  const [themeMode, setThemeMode] = useState(activeSupersetTheme);
  const [collapsed, setCollapsed] = useState(false);
  const [columnsExpanded, setColumnsExpanded] = useState(true);
  const [metricsExpanded, setMetricsExpanded] = useState(true);
  const [canvasFieldIds, setCanvasFieldIds] = useState<string[]>([]);
  const [datasetPickerOpen, setDatasetPickerOpen] = useState(false);
  const [systemDatasets, setSystemDatasets] = useState<DashboardDataset[]>([]);
  const [datasetSearch, setDatasetSearch] = useState('');
  const [pickerSelectedId, setPickerSelectedId] = useState<number | null>(null);
  const [datasetPickerLoading, setDatasetPickerLoading] = useState(false);
  const [datasetPickerError, setDatasetPickerError] = useState('');
  const [savingDataset, setSavingDataset] = useState(false);
  const [activeModule, setActiveModule] = useState<'dictionary' | 'semantic'>('dictionary');
  const [dictionaryDirty, setDictionaryDirty] = useState(false);

  const canLeaveDictionary = () => (
    !dictionaryDirty || window.confirm('Bạn có thay đổi chưa lưu trong Data Dictionary. Tiếp tục và bỏ các thay đổi này?')
  );

  const selectModule = (module: 'dictionary' | 'semantic') => {
    if (module === activeModule) return;
    if (activeModule === 'dictionary' && !canLeaveDictionary()) return;
    setActiveModule(module);
  };

  const selectDataset = (datasetId: number) => {
    if (datasetId === selectedDataset) return;
    if (activeModule === 'dictionary' && !canLeaveDictionary()) return;
    setSelectedDataset(datasetId);
  };

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const syncTheme = () => setThemeMode(activeSupersetTheme());
    const observer = new MutationObserver(syncTheme);
    observer.observe(document.body, { attributes: true, childList: true, subtree: true });
    observer.observe(document.head, { childList: true });
    const expandPanel = () => setCollapsed(false);
    const syncCanvasFields = (event: Event) => {
      setCanvasFieldIds((event as CustomEvent<string[]>).detail ?? []);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && datasetPickerOpen) {
        event.preventDefault();
        event.stopPropagation();
        setDatasetPickerOpen(false);
        return;
      }
      if (event.key === 'Escape') setCollapsed(true);
    };
    window.addEventListener(semanticLayerEvents.expand, expandPanel);
    window.addEventListener(semanticLayerEvents.fieldsChange, syncCanvasFields);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      observer.disconnect();
      window.removeEventListener(semanticLayerEvents.expand, expandPanel);
      window.removeEventListener(semanticLayerEvents.fieldsChange, syncCanvasFields);
      window.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [datasetPickerOpen]);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(supersetApi.dashboardDatasets(dashboardId), {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      }),
      fetch(semanticLayerApi.dashboardDatasets(dashboardId), {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      }),
    ])
      .then(async ([datasetsResponse, semanticDatasetsResponse]) => {
        if (!datasetsResponse.ok) throw new Error(`Không tải được datasets (${datasetsResponse.status}).`);
        const [payload, dashboardPayload] = await Promise.all([
          datasetsResponse.json(),
          semanticDatasetsResponse.ok ? semanticDatasetsResponse.json() : Promise.resolve({ dataset_ids: [] }),
        ]);
        if (!active) return;
        const result = Array.isArray(payload?.result) ? payload.result as DashboardDataset[] : [];
        const linkedIds = Array.isArray(dashboardPayload?.dataset_ids) ? dashboardPayload.dataset_ids.map(Number) : [];
        const extraIds = linkedIds.filter((id: number) => Number.isInteger(id) && !result.some(dataset => dataset.id === id));
        const extraDatasets = await Promise.all(extraIds.map(async (id: number) => {
          try {
            const response = await fetch(supersetApi.dataset(id), {
              credentials: 'same-origin',
              headers: { Accept: 'application/json' },
            });
            if (!response.ok) return null;
            const detail = await response.json();
            return detail?.result as DashboardDataset | null;
          } catch {
            return null;
          }
        }));
        const allDatasets = [...result, ...extraDatasets.filter((dataset): dataset is DashboardDataset => dataset !== null)];
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
  }, [dashboardId]);

  const currentDataset = datasets.find(dataset => dataset.id === selectedDataset);
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

  const openDatasetPicker = async () => {
    setDatasetPickerOpen(true);
    setPickerSelectedId(null);
    setDatasetSearch('');
    setDatasetPickerError('');
    if (systemDatasets.length > 0) return;
    setDatasetPickerLoading(true);
    try {
      const all: DashboardDataset[] = [];
      let page = 0;
      let count = Number.POSITIVE_INFINITY;
      while (all.length < count) {
        const response = await fetch(supersetApi.datasets(page), {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        if (!response.ok) throw new Error(`Không tải được danh sách dataset (${response.status}).`);
        const payload = await response.json();
        const results = Array.isArray(payload?.result) ? payload.result as DashboardDataset[] : [];
        all.push(...results);
        count = Number(payload?.count ?? all.length);
        if (results.length === 0) break;
        page += 1;
      }
      setSystemDatasets(all.sort((left, right) => getDatasetTableLabel(left).localeCompare(getDatasetTableLabel(right))));
    } catch (reason) {
      setDatasetPickerError(reason instanceof Error ? reason.message : 'Không tải được danh sách dataset.');
    } finally {
      setDatasetPickerLoading(false);
    }
  };

  const addSelectedDataset = async () => {
    if (pickerSelectedId === null) return;
    setSavingDataset(true);
    setDatasetPickerError('');
    try {
      const selected = systemDatasets.find(dataset => dataset.id === pickerSelectedId);
      if (!selected) throw new Error('Không tìm thấy dataset đã chọn.');

      const [csrfResponse, detailResponse] = await Promise.all([
        fetch(supersetApi.csrfToken, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        }),
        fetch(supersetApi.dataset(selected.id), {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        }),
      ]);
      if (!csrfResponse.ok) throw new Error(`Không lấy được CSRF token (${csrfResponse.status}).`);
      if (!detailResponse.ok) throw new Error(`Không đọc được dataset (${detailResponse.status}).`);

      const [csrfPayload, detailPayload] = await Promise.all([csrfResponse.json(), detailResponse.json()]);

      const csrfToken = csrfPayload?.result || csrfPayload?.csrf_token;
      const updateResponse = await fetch(semanticLayerApi.dashboardDatasets(dashboardId), {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({ dataset_id: selected.id }),
      });
      if (!updateResponse.ok) {
        const errorPayload = await updateResponse.json().catch(() => ({}));
        throw new Error(errorPayload?.message || `Không thể lưu dataset vào dashboard (${updateResponse.status}).`);
      }

      const dataset = { ...selected, ...(detailPayload?.result ?? {}), id: selected.id } as DashboardDataset;
      setDatasets(current => current.some(item => item.id === dataset.id) ? current : [...current, dataset]);
      setSelectedDataset(dataset.id);
      setDatasetPickerOpen(false);
    } catch (reason) {
      setDatasetPickerError(reason instanceof Error ? reason.message : 'Không thể thêm dataset vào dashboard.');
    } finally {
      setSavingDataset(false);
    }
  };

  const linkedDatasetIds = new Set(datasets.map(dataset => dataset.id));
  const normalizedSearch = datasetSearch.trim().toLocaleLowerCase();
  const filteredSystemDatasets = systemDatasets.filter(dataset => {
    const searchText = `${getDatasetTableLabel(dataset)} ${dataset.database?.database_name ?? ''}`.toLocaleLowerCase();
    return searchText.includes(normalizedSearch);
  });

  return createPortal(
    <div className={`sl-overlay${collapsed ? ' is-collapsed' : ' is-open'}`} data-theme-mode={themeMode}>
      <section className={`sl-panel${collapsed ? ' is-collapsed' : ''}`} role="dialog" aria-modal="true" aria-label="Semantic Layer Explorer" aria-hidden={collapsed}>
        <div className="sl-panel-workspace">
          <header className="sl-header">
            <div className="sl-header-icon"><Layers3 /></div>
            <div className="sl-header-copy">
              <h2>Semantic Layer</h2>
              <p>Khám phá datasets, columns và metrics trên dashboard này</p>
            </div>
            <nav className="sl-module-switcher" aria-label="Semantic metadata modules">
              <button className={activeModule === 'dictionary' ? 'is-active' : ''} type="button" aria-label="Data Dictionary" title="Data Dictionary" aria-current={activeModule === 'dictionary' ? 'page' : undefined} onClick={() => selectModule('dictionary')}>
                <BookOpen /><span>Data Dictionary</span>
              </button>
              <button className={activeModule === 'semantic' ? 'is-active' : ''} type="button" aria-label="Semantic Layer" title="Semantic Layer" aria-current={activeModule === 'semantic' ? 'page' : undefined} onClick={() => selectModule('semantic')}>
                <GitBranch /><span>Semantic Layer</span>
              </button>
            </nav>
            <button className="sl-close" type="button" aria-label="Thu gọn Semantic Layer" title="Thu gọn" onClick={() => setCollapsed(true)}><PanelRightClose /></button>
          </header>

          {loading ? (
            <div className="sl-state"><LoaderCircle className="sl-spin" /><span>Đang tải metadata dashboard…</span></div>
          ) : error ? (
            <div className="sl-state sl-error"><p>{error}</p></div>
          ) : (
            <div className="sl-content">
              <nav className="sl-dataset-list" aria-label="Datasets của dashboard">
                <div className="sl-section-caption">DATASETS <span>{datasets.length}</span></div>
                <div className="sl-dataset-options">
                  {datasets.map(dataset => (
                    <button
                      className={`sl-dataset-option${dataset.id === selectedDataset ? ' is-selected' : ''}`}
                      key={dataset.id}
                      type="button"
                      onClick={() => selectDataset(dataset.id)}
                    >
                      <Database />
                      <span>{getDatasetName(dataset)}</span>
                    </button>
                  ))}
                </div>
                <button className="sl-add-dataset" type="button" aria-label="Thêm dataset vào dashboard" title="Thêm dataset vào dashboard" onClick={openDatasetPicker}>
                  <Plus />
                </button>
              </nav>

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
                  <strong>Dashboard chưa có dataset</strong>
                  <span>Thêm một dataset để bắt đầu xây dựng semantic layer.</span>
                  <button type="button" onClick={openDatasetPicker}><Plus /> Chọn dataset</button>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
      {datasetPickerOpen ? (
        <div className="sl-dataset-picker-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setDatasetPickerOpen(false); }}>
          <section className="sl-dataset-picker" role="dialog" aria-modal="true" aria-labelledby="sl-dataset-picker-title" onMouseDown={event => event.stopPropagation()}>
            <header className="sl-dataset-picker-header">
              <div>
                <h3 id="sl-dataset-picker-title">Thêm dataset vào dashboard</h3>
                <p>Chọn dataset có sẵn trong hệ thống để dùng trong Semantic Layer.</p>
              </div>
              <button type="button" aria-label="Đóng" title="Đóng" onClick={() => setDatasetPickerOpen(false)}><X /></button>
            </header>
            <label className="sl-dataset-picker-search">
              <Search />
              <input autoFocus value={datasetSearch} onChange={event => setDatasetSearch(event.target.value)} placeholder="Tìm theo tên bảng hoặc database…" />
            </label>
            {datasetPickerError ? <div className="sl-dataset-picker-error" role="alert">{datasetPickerError}</div> : null}
            <div className="sl-dataset-picker-list" role="listbox" aria-label="Dataset có sẵn">
              {datasetPickerLoading ? (
                <div className="sl-dataset-picker-state"><LoaderCircle className="sl-spin" /> Đang tải danh sách dataset…</div>
              ) : filteredSystemDatasets.length > 0 ? filteredSystemDatasets.map(dataset => {
                const alreadyLinked = linkedDatasetIds.has(dataset.id);
                return (
                  <button
                    className={`sl-dataset-picker-option${dataset.id === pickerSelectedId ? ' is-selected' : ''}`}
                    type="button"
                    role="option"
                    aria-selected={dataset.id === pickerSelectedId}
                    disabled={alreadyLinked}
                    key={dataset.id}
                    onClick={() => setPickerSelectedId(dataset.id)}
                  >
                    <Database />
                    <span className="sl-dataset-picker-copy">
                      <strong>{getDatasetTableLabel(dataset)}</strong>
                      <small>{dataset.database?.database_name || 'Dataset'}</small>
                    </span>
                    {alreadyLinked ? <span className="sl-dataset-picker-linked">Đã thêm</span> : null}
                  </button>
                );
              }) : (
                <div className="sl-dataset-picker-state">{systemDatasets.length ? 'Không tìm thấy dataset phù hợp.' : 'Hệ thống chưa có dataset nào.'}</div>
              )}
            </div>
            <footer className="sl-dataset-picker-footer">
              <button className="sl-picker-cancel" type="button" onClick={() => setDatasetPickerOpen(false)}>Hủy</button>
              <button className="sl-picker-submit" type="button" disabled={pickerSelectedId === null || savingDataset} onClick={addSelectedDataset}>
                {savingDataset ? <LoaderCircle className="sl-spin" /> : <Plus />}
                Thêm dataset
              </button>
            </footer>
          </section>
        </div>
      ) : null}
      {collapsed ? (
        <button
          className="sl-collapsed-trigger"
          type="button"
          aria-label="Mở lại Semantic Layer"
          title="Mở lại Semantic Layer"
          onClick={() => setCollapsed(false)}
        >
          <PanelRightOpen />
        </button>
      ) : null}
    </div>,
    document.body,
  );
}

function SemanticLayerHost({ dashboardId }: { dashboardId: string }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const showPanel = () => {
      setOpen(true);
      window.dispatchEvent(new Event(semanticLayerEvents.expand));
    };
    window.addEventListener(semanticLayerEvents.open, showPanel);
    return () => window.removeEventListener(semanticLayerEvents.open, showPanel);
  }, []);
  return (
    open ? <SemanticLayerPanel dashboardId={dashboardId} /> : null
  );
}

/** Adds an admin-only entry to Superset's dashboard action dropdown. */
export function installDashboardSemanticLayer(): () => void {
  let host: HTMLSpanElement | undefined;
  let frame = 0;
  let mountedDashboard = '';
  let accessChecked = false;
  let adminAllowed = false;
  let pendingDashboard = '';
  let checking = false;

  const removeMenuItem = () => {
    document.querySelector(semanticLayerSelectors.menuItem)?.remove();
    document.querySelector(semanticLayerSelectors.menuDivider)?.remove();
  };

  const clear = () => {
    removeMenuItem();
    if (host) {
      ReactDOM.unmountComponentAtNode(host);
      host.remove();
    }
    host = undefined;
    mountedDashboard = '';
  };

  const addMenuItem = () => {
    const menu = Array.from(document.querySelectorAll<HTMLUListElement>(semanticLayerSelectors.actionsMenu))
      .find(candidate => {
        const style = getComputedStyle(candidate);
        return style.display !== 'none' && style.visibility !== 'hidden'
          && /Share|Refresh dashboard|Download/i.test(candidate.textContent ?? '');
      });
    if (!menu || menu.querySelector(semanticLayerSelectors.menuItem)) return;

    const divider = document.createElement('li');
    divider.className = 'ant-dropdown-menu-item-divider';
    divider.setAttribute('role', 'separator');
    divider.dataset.test = 'semantic-layer-menu-divider';

    const item = document.createElement('li');
    item.className = 'ant-dropdown-menu-item ant-dropdown-menu-item-only-child sl-menu-item';
    item.setAttribute('role', 'menuitem');
    item.setAttribute('tabindex', '-1');
    item.dataset.test = 'semantic-layer-menu-item';
    item.innerHTML = '<span class="ant-dropdown-menu-title-content">Semantic Layer</span>';
    menu.append(divider, item);
  };

  const mountForDashboard = (dashboardId: string) => {
    if (!host) {
      host = document.createElement('span');
      host.hidden = true;
      host.dataset.semanticLayerHost = 'true';
      document.body.append(host);
    }
    if (mountedDashboard !== dashboardId) {
      if (mountedDashboard) ReactDOM.unmountComponentAtNode(host);
      mountedDashboard = dashboardId;
      ReactDOM.render(<SemanticLayerHost dashboardId={dashboardId} />, host);
    }
    addMenuItem();
  };

  const handleMenuClick = (event: MouseEvent) => {
    const target = event.target;
    if (!(target instanceof Element) || !target.closest(semanticLayerSelectors.menuItem)) return;
    event.preventDefault();
    window.dispatchEvent(new Event(semanticLayerEvents.open));
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLButtonElement>(semanticLayerSelectors.actionsTrigger)?.click();
    });
  };

  const mount = () => {
    frame = 0;
    const match = window.location.pathname.match(/^\/superset\/dashboard\/([^/]+)/);
    if (!match) {
      pendingDashboard = '';
      if (host) clear();
      return;
    }
    const dashboardId = decodeURIComponent(match[1]);
    if (accessChecked) {
      if (adminAllowed) mountForDashboard(dashboardId);
      else if (host) clear();
      return;
    }
    pendingDashboard = dashboardId;
    if (checking) return;
    checking = true;
    fetch(semanticLayerApi.access, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(response => response.ok ? response.json() : null)
      .then(payload => {
        accessChecked = true;
        adminAllowed = payload?.is_admin === true;
        if (adminAllowed && pendingDashboard) mountForDashboard(pendingDashboard);
      })
      .catch(() => { accessChecked = true; adminAllowed = false; })
      .finally(() => { checking = false; });
  };

  const schedule = () => {
    if (!frame) frame = window.requestAnimationFrame(mount);
  };
  const observer = new MutationObserver(schedule);
  observer.observe(document.body, { childList: true, subtree: true });
  document.addEventListener('click', handleMenuClick, true);
  window.addEventListener('popstate', schedule);
  mount();

  return () => {
    observer.disconnect();
    document.removeEventListener('click', handleMenuClick, true);
    window.removeEventListener('popstate', schedule);
    if (frame) window.cancelAnimationFrame(frame);
    clear();
  };
}

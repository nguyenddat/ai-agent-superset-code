import React, { useCallback, useEffect, useState } from 'react';
import ReactDOM from 'react-dom';
import { Database, Layers3, LoaderCircle, Table2 } from 'lucide-react';
import '@xyflow/react/dist/style.css';
import '@/styles/globals.css';
import { PortalContainerContext } from '@/lib/portal-container';
import { DataDictionary } from '../features/semantic-layer/DataDictionary';
import { BusinessCanvas } from '../features/semantic-layer/BusinessCanvas';
import { Glossary } from '../features/semantic-layer/Glossary';
import { MetricContracts } from '../features/semantic-layer/MetricContracts';
import { requestJson, semanticLayerApi, supersetApi } from '../features/semantic-layer/api';
import {
  SEMANTIC_LAYER_PAGE,
  semanticLayerEvents,
  semanticLayerModuleFromLocation,
  semanticLayerModuleHref,
  semanticLayerModules,
  semanticLayerSelectors,
} from '../features/semantic-layer/constants';
import type { SemanticLayerModule } from '../features/semantic-layer/constants';
import { getDatasetName, groupDatasetsByLayer } from '../features/semantic-layer/datasets';
import { HeaderPicker } from '../features/semantic-layer/HeaderPicker';
import { LayersDialog } from '../features/semantic-layer/LayersDialog';
import type { DashboardDataset, DataLayer, DatasetDictionary, SupersetDatabase, ThemeMode } from '../features/semantic-layer/types';

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
  const [pageElement, setPageElement] = useState<HTMLDivElement | null>(null);
  const [datasets, setDatasets] = useState<DashboardDataset[]>([]);
  const [dictionaryByDataset, setDictionaryByDataset] = useState<Record<number, DatasetDictionary>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedDataset, setSelectedDataset] = useState<number | null>(null);
  const [themeMode, setThemeMode] = useState(activeSupersetTheme);
  const [activeModule, setActiveModule] = useState<SemanticLayerModule>(semanticLayerModuleFromLocation);
  const [dictionaryDirty, setDictionaryDirty] = useState(false);
  const [layers, setLayers] = useState<DataLayer[]>([]);
  const [layersDialogOpen, setLayersDialogOpen] = useState(false);
  // Bumped when layers or dictionaries change so the canvas reloads its classification-dependent model.
  const [modelRevision, setModelRevision] = useState(0);

  const loadLayers = useCallback(async () => {
    try {
      const payload = await requestJson<{ layers: DataLayer[] }>(semanticLayerApi.dataLayers, 'GET');
      setLayers(payload.layers);
    } catch {
      setLayers([]);
    }
    setModelRevision(value => value + 1);
  }, []);

  useEffect(() => { void loadLayers(); }, [loadLayers]);

  const onDictionarySaved = useCallback((dictionary: DatasetDictionary) => {
    setDictionaryByDataset(current => ({ ...current, [dictionary.dataset_id]: dictionary }));
    setModelRevision(value => value + 1);
  }, []);

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
    // The page fills the viewport and only its inner panes scroll. If focus or scrollIntoView moves the window or a
    // frame container, the header and Save button leave the screen with no way to scroll back, so undo it.
    const frameSelector = '#app, .sl-page, .sl-panel, .sl-panel-workspace, .sl-content, .sl-dictionary-main, .sl-dictionary, .sl-details';
    const resetFrameScroll = (event: Event) => {
      const target = event.target;
      if (target === document || target === document.documentElement || target === document.body) {
        if (window.scrollX || window.scrollY) window.scrollTo(0, 0);
      } else if (target instanceof HTMLElement && target.matches(frameSelector) && (target.scrollTop || target.scrollLeft)) {
        target.scrollTop = 0;
        target.scrollLeft = 0;
      }
    };
    document.addEventListener('scroll', resetFrameScroll, true);
    return () => {
      observer.disconnect();
      document.removeEventListener('scroll', resetFrameScroll, true);
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

  useEffect(() => {
    let active = true;
    if (datasets.length === 0) {
      setDictionaryByDataset({});
      return () => { active = false; };
    }
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
    });
    return () => { active = false; };
  }, [datasets]);

  return (
    <PortalContainerContext.Provider value={pageElement}>
    <div className="sl-page" data-theme-mode={themeMode} ref={setPageElement}>
      <section className="sl-panel" aria-label="Semantic Layer Explorer">
        <div className="sl-panel-workspace">
          <header className="sl-header">
            <div className="sl-header-icon"><Layers3 /></div>
            <div className="sl-header-copy">
              <h2>{currentModule.label}</h2>
              <p>{currentModule.description}</p>
            </div>
            <div className="sl-header-select">
              <HeaderPicker
                ariaLabel="Database"
                icon={Database}
                items={databases.map(database => ({ value: database.id, label: database.database_name }))}
                value={selectedDatabase}
                onChange={selectDatabase}
                disabled={databases.length === 0}
                placeholder="Chọn database"
              />
            </div>
            <div className="sl-header-select sl-dataset-select">
              <HeaderPicker
                ariaLabel="Dataset"
                icon={Table2}
                caption={`Datasets (${datasets.length})`}
                items={groupDatasetsByLayer(datasets, layers, id => dictionaryByDataset[id]?.layer_id).flatMap(group => group.datasets.map(dataset => ({ value: dataset.id, label: getDatasetName(dataset), group: group.label })))}
                value={selectedDataset}
                onChange={selectDataset}
                disabled={loading || datasets.length === 0}
                placeholder="Chọn dataset"
              />
            </div>
          </header>

          {loading ? (
            <div className="sl-state"><LoaderCircle className="sl-spin" /><span>Đang tải metadata database…</span></div>
          ) : error ? (
            <div className="sl-state sl-error"><p>{error}</p></div>
          ) : (
            <div className="sl-content">
              {activeModule === 'glossary' ? (
                <main className="sl-details"><Glossary datasets={datasets} /></main>
              ) : activeModule === 'metrics' ? (
                <main className="sl-details"><MetricContracts databaseId={selectedDatabase} /></main>
              ) : currentDataset ? (
                activeModule === 'dictionary' ? (
                  <main className="sl-dictionary-main">
                    <DataDictionary key={currentDataset.id} dataset={currentDataset} layers={layers} onDirtyChange={setDictionaryDirty} onSaved={onDictionarySaved} onManageLayers={() => setLayersDialogOpen(true)} />
                  </main>
                ) : (
                <main className="sl-details">
                  <BusinessCanvas
                    themeMode={themeMode}
                    databaseId={selectedDatabase as number}
                    datasets={datasets}
                    dictionaries={dictionaryByDataset}
                    focusDatasetId={selectedDataset}
                    revision={modelRevision}
                  />
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
      <LayersDialog open={layersDialogOpen} layers={layers} onOpenChange={setLayersDialogOpen} onSaved={() => void loadLayers()} />
    </div>
    </PortalContainerContext.Provider>
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

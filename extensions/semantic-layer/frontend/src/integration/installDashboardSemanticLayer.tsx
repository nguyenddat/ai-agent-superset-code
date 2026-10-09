import React, { useEffect, useState } from 'react';
import ReactDOM, { createPortal } from 'react-dom';
import { Background, BackgroundVariant, BaseEdge, Controls, Edge, EdgeProps, EdgeTypes, Handle, Node, NodeProps, NodeTypes, Position, ReactFlow, ReactFlowProvider, addEdge, useEdgesState, useNodesState, useReactFlow } from '@xyflow/react';
import { Boxes, Braces, CalendarClock, Check, ChevronDown, Database, Layers3, LoaderCircle, PanelRightClose, PanelRightOpen, Plus, Search, Trash2, X } from 'lucide-react';
import '@xyflow/react/dist/style.css';

type DatasetColumn = {
  column_name: string;
  verbose_name?: string | null;
  type?: string | null;
  description?: string | null;
  is_dttm?: boolean;
};

type DatasetMetric = {
  metric_name: string;
  verbose_name?: string | null;
  expression?: string | null;
  description?: string | null;
};

type DashboardDataset = {
  id: number;
  name?: string | null;
  datasource_name?: string | null;
  schema?: string | null;
  table_name?: string | null;
  description?: string | null;
  database?: { database_name?: string | null };
  columns?: DatasetColumn[];
  metrics?: DatasetMetric[];
};

const SEMANTIC_LAYER_API = '/extensions/text-to-bi/text-to-bi-semantic-layer/semantic-layer';
const TABLE_FIELD_ROW_STEP = 68;

type SemanticField = {
  id: string;
  name: string;
  kind: 'column' | 'metric';
  type?: string | null;
  expression?: string | null;
  sourceTable?: string;
};

type SemanticNodeData = SemanticField & {
  fields?: SemanticField[];
  onRemove: (id: string) => void;
  onRemoveField: (nodeId: string, fieldId: string) => void;
};
type SemanticNode = Node<SemanticNodeData, 'semanticField'>;

function SemanticFieldNode({ id, data }: NodeProps<SemanticNode>) {
  if (data.kind === 'column' && data.sourceTable && data.fields) {
    return (
      <div className="sl-flow-node sl-table-node">
        <div className="sl-table-node-header">
          <div className="sl-item-icon"><Database /></div>
          <strong title={data.sourceTable}>{data.sourceTable}</strong>
          <span>{data.fields.length} cột</span>
        </div>
        <div className="sl-table-node-fields">
          {data.fields.map(field => (
            <div className="sl-table-node-field" key={field.id}>
              <Handle id={`column-${field.id}-target`} type="target" position={Position.Left} />
              <Braces />
              <span title={field.name}>{field.name}</span>
              <small>{field.type || 'UNKNOWN'}</small>
              <button className="nodrag nopan" type="button" aria-label={`Xóa ${field.name} khỏi ${data.sourceTable}`} title="Xóa cột" onClick={event => { event.stopPropagation(); data.onRemoveField(id, field.id); }}><X /></button>
              <Handle id={`column-${field.id}-source`} type="source" position={Position.Right} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={`sl-flow-node${data.kind === 'metric' ? ' is-metric' : ''}`}>
      <Handle type="target" position={Position.Left} />
      <div className="sl-item-icon">{data.kind === 'metric' ? <Layers3 /> : <Braces />}</div>
      <div className="sl-item-copy">
        <strong>{data.name}</strong>
        {data.kind === 'column' && data.sourceTable ? <span className="sl-flow-node-table">BẢNG · {data.sourceTable}</span> : null}
        <span>{data.kind === 'metric' ? data.expression || 'METRIC' : `COLUMN · ${data.type || 'UNKNOWN'}`}</span>
      </div>
      <button className="nodrag nopan" type="button" aria-label={`Xóa ${data.name} khỏi canvas`} title="Xóa khỏi canvas" onClick={() => data.onRemove(id)}><Trash2 /></button>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const semanticNodeTypes: NodeTypes = { semanticField: SemanticFieldNode };

function BundledSemanticEdge({ sourceX, sourceY, targetX, targetY, style, markerEnd }: EdgeProps) {
  // Edges with the same target share this final horizontal segment, creating
  // a compact visual bundle while retaining each source-to-target relation.
  const bundleX = Math.max(sourceX + 24, targetX - 34);
  const curveX = sourceX + (bundleX - sourceX) * 0.55;
  const path = `M ${sourceX},${sourceY} C ${curveX},${sourceY} ${bundleX},${targetY} ${bundleX},${targetY} L ${targetX},${targetY}`;
  return <BaseEdge path={path} markerEnd={markerEnd} style={{ ...style, strokeWidth: 5 }} />;
}

const semanticEdgeTypes: EdgeTypes = { semantic: BundledSemanticEdge };

function isValidSemanticConnection(connection: { sourceHandle?: string | null; targetHandle?: string | null }) {
  if (!connection.sourceHandle || !connection.targetHandle) return true;
  const sourceColumn = connection.sourceHandle.replace(/-source$/, '');
  const targetColumn = connection.targetHandle.replace(/-target$/, '');
  return sourceColumn !== targetColumn;
}

function SemanticFlowCanvas({ themeMode }: { themeMode: 'light' | 'dark' }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<SemanticNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { screenToFlowPosition } = useReactFlow<SemanticNode>();

  useEffect(() => {
    window.dispatchEvent(new CustomEvent('semantic-fields-change', {
      detail: nodes.flatMap(node => node.data.fields?.map(field => field.id) ?? [node.data.id]),
    }));
  }, [nodes]);

  const removeNode = (nodeId: string) => {
    setNodes(current => current.filter(node => node.id !== nodeId));
    setEdges(current => current.filter(edge => edge.source !== nodeId && edge.target !== nodeId));
  };

  const removeField = (nodeId: string, fieldId: string) => {
    const currentNode = nodes.find(node => node.id === nodeId);
    if ((currentNode?.data.fields?.length ?? 0) <= 1) {
      removeNode(nodeId);
      return;
    }
    setNodes(current => current.flatMap(node => {
      if (node.id !== nodeId || !node.data.fields) return [node];
      const fields = node.data.fields.filter(field => field.id !== fieldId);
      if (fields.length === 0) return [];
      return [{ ...node, data: { ...node.data, fields } }];
    }));
  };

  const addField = (item: SemanticField, clientX: number, clientY: number) => {
    const position = screenToFlowPosition({ x: clientX, y: clientY });
    if (item.kind === 'column' && item.sourceTable) {
      const sourceTable = item.sourceTable;
      const tableNodeId = `table-${sourceTable}`;
      setNodes(current => {
        const existing = current.find(node => node.id === tableNodeId);
        if (existing) {
          if (existing.data.fields?.some(field => field.id === item.id)) return current;
          return current.map(node => node.id === tableNodeId
            ? {
              ...node,
              position: { ...node.position, y: node.position.y - TABLE_FIELD_ROW_STEP / 2 },
              data: { ...node.data, fields: [...(node.data.fields ?? []), item] },
            }
            : node);
        }
        return [...current, {
          id: tableNodeId,
          type: 'semanticField',
          position,
          data: { ...item, id: tableNodeId, name: sourceTable, fields: [item], onRemove: removeNode, onRemoveField: removeField },
        }];
      });
      return;
    }
    setNodes(current => current.some(node => node.id === item.id) ? current : [...current, {
      id: item.id,
      type: 'semanticField',
      position,
      data: { ...item, onRemove: removeNode, onRemoveField: removeField },
    }]);
  };

  useEffect(() => {
    const handlePointerDrop = (event: Event) => {
      const detail = (event as CustomEvent<{ item: SemanticField; clientX: number; clientY: number }>).detail;
      if (detail?.item) addField(detail.item, detail.clientX, detail.clientY);
    };
    window.addEventListener('semantic-field-pointer-drop', handlePointerDrop);
    return () => window.removeEventListener('semantic-field-pointer-drop', handlePointerDrop);
  }, [screenToFlowPosition]);

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const raw = event.dataTransfer.getData('application/x-semantic-field');
    if (!raw) return;
    try {
      const item = JSON.parse(raw) as SemanticField;
      addField(item, event.clientX, event.clientY);
    } catch {
      // Ignore malformed drag data.
    }
  };

  return (
    <div className="sl-flow-canvas" onDrop={handleDrop} onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={semanticNodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={connection => {
          if (!isValidSemanticConnection(connection)) return;
          setEdges(current => addEdge({ ...connection, type: 'semantic', style: { stroke: 'var(--sl-accent)', strokeWidth: 5 }, interactionWidth: 22, zIndex: 10 }, current));
        }}
        isValidConnection={isValidSemanticConnection}
        edgeTypes={semanticEdgeTypes}
        colorMode={themeMode}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        minZoom={0.25}
        maxZoom={2}
        snapToGrid
        snapGrid={[24, 24]}
        deleteKeyCode={['Backspace', 'Delete']}
        aria-label="Canvas semantic layer"
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.8} color="var(--sl-grid-dot)" />
        <Controls position="bottom-right" showInteractive={false} />
        {nodes.length === 0 ? (
          <div className="sl-empty-canvas">
            <Plus />
            <strong>Kéo cột vào đây</strong>
            <span>Thả columns hoặc metrics lên canvas, rồi nối các mục để biểu diễn quan hệ.</span>
          </div>
        ) : null}
      </ReactFlow>
      <span className="sl-canvas-count">{nodes.length} mục</span>
    </div>
  );
}

function SemanticCanvasHost({ themeMode }: { themeMode: 'light' | 'dark' }) {
  return <ReactFlowProvider><SemanticFlowCanvas themeMode={themeMode} /></ReactFlowProvider>;
}

function activeSupersetTheme(): 'light' | 'dark' {
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
    window.addEventListener('text-to-bi:expand-semantic-layer', expandPanel);
    window.addEventListener('semantic-fields-change', syncCanvasFields);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      observer.disconnect();
      window.removeEventListener('text-to-bi:expand-semantic-layer', expandPanel);
      window.removeEventListener('semantic-fields-change', syncCanvasFields);
      window.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [datasetPickerOpen]);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`/api/v1/dashboard/${encodeURIComponent(dashboardId)}/datasets`, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      }),
      fetch(`${SEMANTIC_LAYER_API}/dashboard/${encodeURIComponent(dashboardId)}/datasets`, {
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
            const response = await fetch(`/api/v1/dataset/${encodeURIComponent(id)}`, {
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
            const detailResponse = await fetch(`/api/v1/dataset/${encodeURIComponent(dataset.id)}`, {
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
  const datasetName = (dataset: DashboardDataset) => dataset.name || dataset.datasource_name || dataset.table_name || `Dataset ${dataset.id}`;
  const datasetTableLabel = (dataset: DashboardDataset) => {
    const table = dataset.table_name || dataset.datasource_name || dataset.name || `Dataset ${dataset.id}`;
    return dataset.schema && !table.startsWith(`${dataset.schema}.`) ? `${dataset.schema}.${table}` : table;
  };
  const rawTableName = currentDataset?.table_name || currentDataset?.datasource_name || currentDataset?.name || '';
  const sourceTable = currentDataset?.schema && !rawTableName.startsWith(`${currentDataset.schema}.`)
    ? `${currentDataset.schema}.${rawTableName}`
    : rawTableName;
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
        window.dispatchEvent(new CustomEvent('semantic-field-pointer-drop', {
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
        const query = encodeURIComponent(`(page:${page},page_size:100)`);
        const response = await fetch(`/api/v1/dataset/?q=${query}`, {
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
      setSystemDatasets(all.sort((left, right) => datasetTableLabel(left).localeCompare(datasetTableLabel(right))));
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
        fetch('/api/v1/security/csrf_token/', {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        }),
        fetch(`/api/v1/dataset/${encodeURIComponent(selected.id)}`, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        }),
      ]);
      if (!csrfResponse.ok) throw new Error(`Không lấy được CSRF token (${csrfResponse.status}).`);
      if (!detailResponse.ok) throw new Error(`Không đọc được dataset (${detailResponse.status}).`);

      const [csrfPayload, detailPayload] = await Promise.all([csrfResponse.json(), detailResponse.json()]);

      const csrfToken = csrfPayload?.result || csrfPayload?.csrf_token;
      const updateResponse = await fetch(`${SEMANTIC_LAYER_API}/dashboard/${encodeURIComponent(dashboardId)}/datasets`, {
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
    const searchText = `${datasetTableLabel(dataset)} ${dataset.database?.database_name ?? ''}`.toLocaleLowerCase();
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
                      onClick={() => setSelectedDataset(dataset.id)}
                    >
                      <Database />
                      <span>{datasetName(dataset)}</span>
                    </button>
                  ))}
                </div>
                <button className="sl-add-dataset" type="button" aria-label="Thêm dataset vào dashboard" title="Thêm dataset vào dashboard" onClick={openDatasetPicker}>
                  <Plus />
                </button>
              </nav>

              {currentDataset ? (
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
                              const item = { id: `column-${currentDataset.id}-${column.column_name}`, name: column.verbose_name || column.column_name, kind: 'column' as const, type: column.is_dttm ? 'TIME' : column.type, sourceTable };
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
                      <SemanticCanvasHost themeMode={themeMode} />
                    </section>
                  </div>
                </main>
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
                      <strong>{datasetTableLabel(dataset)}</strong>
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
      window.dispatchEvent(new Event('text-to-bi:expand-semantic-layer'));
    };
    window.addEventListener('text-to-bi:open-semantic-layer', showPanel);
    return () => window.removeEventListener('text-to-bi:open-semantic-layer', showPanel);
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
    document.querySelector('[data-test="semantic-layer-menu-item"]')?.remove();
    document.querySelector('[data-test="semantic-layer-menu-divider"]')?.remove();
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
    const menu = document.querySelector<HTMLUListElement>('ul[data-test="header-actions-menu"]');
    if (!menu || menu.querySelector('[data-test="semantic-layer-menu-item"]')) return;

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
    if (!(target instanceof Element) || !target.closest('[data-test="semantic-layer-menu-item"]')) return;
    event.preventDefault();
    window.dispatchEvent(new Event('text-to-bi:open-semantic-layer'));
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLButtonElement>('button[data-test="actions-trigger"]')?.click();
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
    fetch('/extensions/text-to-bi/text-to-bi-semantic-layer/semantic-layer/access', {
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

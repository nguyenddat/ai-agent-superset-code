import React, { useEffect } from 'react';
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  Edge,
  EdgeProps,
  EdgeTypes,
  Handle,
  NodeProps,
  NodeTypes,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react';
import { Braces, Database, Layers3, Plus, Trash2, X } from 'lucide-react';
import { semanticLayerEvents } from './constants';
import type { DashboardDataset, DatasetDictionary, SemanticField, SemanticNode, ThemeMode } from './types';
import { getDatasetSourceTable, getDatasetTableLabel } from './datasets';

const TABLE_FIELD_ROW_STEP = 68;

function SemanticFieldNode({ id, data }: NodeProps<SemanticNode>) {
  if (data.kind === 'column' && data.sourceTable && data.fields) {
    return (
      <div className={`sl-flow-node sl-table-node${data.datasetType ? ` is-${data.datasetType}` : ''}`}>
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

function SemanticFlowCanvas({ themeMode, datasets, dictionaries, dictionariesReady }: { themeMode: ThemeMode; datasets: DashboardDataset[]; dictionaries: Record<number, DatasetDictionary>; dictionariesReady: boolean }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<SemanticNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { screenToFlowPosition } = useReactFlow<SemanticNode>();

  useEffect(() => {
    if (datasets.length === 0 || !dictionariesReady) return;
    const referencedColumns = new Set<string>();
    for (const dictionary of Object.values(dictionaries)) {
      for (const column of dictionary.columns) {
        if (column.referenced_dataset_id != null && column.referenced_column_name) {
          referencedColumns.add(`${column.referenced_dataset_id}:${column.referenced_column_name}`);
        }
      }
    }
    const fieldsByDataset = new Map<number, SemanticField[]>();
    const nextNodes: SemanticNode[] = datasets.map((dataset, index) => {
      const table = getDatasetSourceTable(dataset) || getDatasetTableLabel(dataset);
      const dictionary = dictionaries[dataset.id];
      const supersetColumnsByName = new Map((dataset.columns ?? []).map(column => [column.column_name, column]));
      const fields = (dictionary?.columns ?? [])
        .filter(column => column.is_pk || column.is_fk || column.referenced_dataset_id != null || referencedColumns.has(`${dataset.id}:${column.column_name}`))
        .map(meta => {
          const column = supersetColumnsByName.get(meta.column_name);
          return {
            id: `column-${dataset.id}-${meta.column_name}`,
            name: meta.display_name || column?.verbose_name || meta.column_name,
            kind: 'column' as const,
            type: column?.is_dttm ? 'TIME' : column?.type || meta.data_type,
            sourceTable: table,
            sourceDatasetId: dataset.id,
            datasetType: dictionary?.dataset_type ?? null,
            referencedDatasetId: meta.referenced_dataset_id,
            referencedColumnName: meta.referenced_column_name,
          };
        });
      fieldsByDataset.set(dataset.id, fields);
      return {
        id: `table-${dataset.id}`,
        type: 'semanticField',
        position: { x: index * 440, y: 0 },
        data: { id: `table-${dataset.id}`, name: table, kind: 'column', sourceTable: table, sourceDatasetId: dataset.id, datasetType: dictionary?.dataset_type ?? null, fields, onRemove: removeNode, onRemoveField: removeField },
      };
    });
    const nextEdges: Edge[] = [];
    for (const [datasetId, fields] of fieldsByDataset) {
      for (const field of fields) {
        if (!field.referencedDatasetId || !field.referencedColumnName || !fieldsByDataset.has(field.referencedDatasetId)) continue;
        const target = fieldsByDataset.get(field.referencedDatasetId)?.find(item => item.id === `column-${field.referencedDatasetId}-${field.referencedColumnName}`);
        if (!target) continue;
        nextEdges.push({
          id: `reference-${field.id}-${target.id}`,
          source: `table-${datasetId}`,
          sourceHandle: `column-${field.id}-source`,
          target: `table-${field.referencedDatasetId}`,
          targetHandle: `column-${target.id}-target`,
          type: 'semantic',
          label: 'reference',
          style: { stroke: field.datasetType === 'aggregate' ? '#805ad5' : '#168eb1', strokeWidth: 3 },
          interactionWidth: 22,
        });
      }
    }
    setNodes(nextNodes);
    setEdges(nextEdges);
  }, [datasets, dictionaries, dictionariesReady]);

  useEffect(() => {
    window.dispatchEvent(new CustomEvent(semanticLayerEvents.fieldsChange, {
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
      const tableNodeId = `table-${item.sourceDatasetId ?? sourceTable}`;
      setNodes(current => {
        const existing = current.find(node => node.id === tableNodeId);
        if (existing) {
          if (existing.data.fields?.some(field => field.id === item.id)) return current;
          return current.map(node => node.id === tableNodeId
            ? {
              ...node,
              position: { ...node.position, y: node.position.y - TABLE_FIELD_ROW_STEP / 2 },
              data: { ...node.data, fields: [...(node.data.fields ?? []), item], datasetType: item.datasetType ?? node.data.datasetType },
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
    window.addEventListener(semanticLayerEvents.pointerDrop, handlePointerDrop);
    return () => window.removeEventListener(semanticLayerEvents.pointerDrop, handlePointerDrop);
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

export function SemanticCanvas({ themeMode, datasets, dictionaries, dictionariesReady }: { themeMode: ThemeMode; datasets: DashboardDataset[]; dictionaries: Record<number, DatasetDictionary>; dictionariesReady: boolean }) {
  return <ReactFlowProvider><SemanticFlowCanvas themeMode={themeMode} datasets={datasets} dictionaries={dictionaries} dictionariesReady={dictionariesReady} /></ReactFlowProvider>;
}

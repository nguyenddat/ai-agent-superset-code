import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  LockKeyhole,
  RotateCcw,
  Save,
  Settings2,
  Sparkles,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi, supersetApi } from './api';
import { layerLevels } from './datasets';
import { ReferenceFields } from './ReferenceFields';
import { TimeSemanticsFields, type TimeSemantics } from './TimeSemanticsFields';
import type {
  ColumnDictionary, ColumnDictionarySuggestion, DashboardDataset, DataLayer, DatasetDictionary, ReferenceDataset,
  TemporalKind,
} from './types';

type DataDictionaryProps = {
  dataset: DashboardDataset;
  layers: DataLayer[];
  onDirtyChange: (dirty: boolean) => void;
  onSaved: (dictionary: DatasetDictionary) => void;
  onManageLayers: () => void;
};

const datasetTypeItems: Array<{ label: string; value: DatasetDictionary['dataset_type'] }> = [
  { label: 'Chưa phân loại', value: null },
  { label: 'Base dataset', value: 'base' },
  { label: 'Aggregate dataset', value: 'aggregate' },
];

const temporalKindItems: Array<{ label: string; value: TemporalKind | null }> = [
  { label: 'Không phải cột thời gian', value: null },
  { label: 'Ngày', value: 'date' },
  { label: 'Ngày giờ', value: 'timestamp' },
];
const TEMPORAL_KIND_LABELS: Record<TemporalKind, string> = { date: 'Ngày', timestamp: 'Ngày giờ' };

const editableFields: Array<keyof Omit<ColumnDictionary, 'id' | 'column_name'>> = [
  'display_name',
  'nullable',
  'default_value',
  'is_pk',
  'is_fk',
  'referenced_dataset_id',
  'referenced_column_name',
  'is_unique',
  'unit',
  'format',
  'business_term',
  'temporal_kind',
];

type DictionaryTab = 'columns' | 'general' | 'time';
const TAB_STORAGE_KEY = 'sl-dictionary-tab';

/** The tab last opened in this browser, so switching datasets keeps the administrator where they work. */
function rememberedTab(): DictionaryTab {
  try {
    const stored = window.localStorage.getItem(TAB_STORAGE_KEY);
    return stored === 'general' || stored === 'time' ? stored : 'columns';
  } catch {
    return 'columns';
  }
}

function timeSemanticsOf(dictionary: DatasetDictionary): TimeSemantics {
  return { time_column: dictionary.time_column, row_kind_column: dictionary.row_kind_column, grains: dictionary.grains ?? [] };
}

function normalizeNullableText(value: string | null): string | null {
  return value === '' ? null : value;
}

function comparableColumns(columns: ColumnDictionary[]): string {
  return JSON.stringify(columns.map(column => ({
    column_name: column.column_name,
    ...Object.fromEntries(editableFields.map(field => [field, column[field]])),
  })));
}

async function responseMessage(response: Response, fallback: string): Promise<string> {
  const payload = await response.json().catch(() => ({}));
  return payload?.message || payload?.error || fallback;
}

export function DataDictionary({ dataset, layers, onDirtyChange, onSaved, onManageLayers }: DataDictionaryProps) {
  const [dictionary, setDictionary] = useState<DatasetDictionary | null>(null);
  const [baseline, setBaseline] = useState<ColumnDictionary[]>([]);
  const [datasetBaseline, setDatasetBaseline] = useState({
    display_name: '',
    description: null as string | null,
    grain: null as string | null,
    create_column: null as string | null,
    dataset_type: null as DatasetDictionary['dataset_type'],
    layer_id: null as number | null,
    timeSemantics: JSON.stringify({ time_column: null, row_kind_column: null, grains: [] }),
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState('');
  const [suggested, setSuggested] = useState(false);
  const [suggestProgress, setSuggestProgress] = useState('');
  const [referenceDatasets, setReferenceDatasets] = useState<ReferenceDataset[]>([]);
  const [referenceOptionsError, setReferenceOptionsError] = useState('');
  // Bumped after a save so the reference picker sees newly declared key columns.
  const [referenceRevision, setReferenceRevision] = useState(0);
  const [expandedColumns, setExpandedColumns] = useState<Set<string>>(() => new Set());
  const [tab, setTab] = useState<DictionaryTab>(rememberedTab);

  const columns = dictionary?.columns ?? [];
  const generalDirty = dictionary !== null && (
    dictionary.display_name !== datasetBaseline.display_name
    || dictionary.description !== datasetBaseline.description
    || dictionary.grain !== datasetBaseline.grain
    || dictionary.create_column !== datasetBaseline.create_column
    || dictionary.dataset_type !== datasetBaseline.dataset_type
    || dictionary.layer_id !== datasetBaseline.layer_id
  );
  const timeDirty = dictionary !== null && JSON.stringify(timeSemanticsOf(dictionary)) !== datasetBaseline.timeSemantics;
  const columnsDirty = useMemo(() => comparableColumns(columns) !== comparableColumns(baseline), [baseline, columns]);
  const dirty = generalDirty || timeDirty || columnsDirty;
  const selectTab = (next: DictionaryTab) => {
    setTab(next);
    try {
      window.localStorage.setItem(TAB_STORAGE_KEY, next);
    } catch {
      // A browser that blocks storage just opens the default tab next time.
    }
  };

  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (!dirty) return undefined;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warnBeforeUnload);
    return () => window.removeEventListener('beforeunload', warnBeforeUnload);
  }, [dirty]);

  const loadDictionary = async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    setSaveError('');
    setSaved(false);
    try {
      const response = await fetch(semanticLayerApi.datasetDictionary(dataset.id), {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        signal,
      });
      if (!response.ok) throw new Error(await responseMessage(response, `Không tải được data dictionary (${response.status}).`));
      const payload = await response.json() as DatasetDictionary;
      if (!Array.isArray(payload.columns)) throw new Error('Data dictionary trả về dữ liệu không hợp lệ.');
      setDictionary(payload);
      setBaseline(payload.columns);
      setDatasetBaseline({
        display_name: payload.display_name,
        description: payload.description,
        grain: payload.grain,
        create_column: payload.create_column,
        dataset_type: payload.dataset_type,
        layer_id: payload.layer_id ?? null,
        timeSemantics: JSON.stringify(timeSemanticsOf(payload)),
      });
    } catch (reason) {
      if ((reason as Error).name !== 'AbortError') {
        setError(reason instanceof Error ? reason.message : 'Không tải được data dictionary.');
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    setExpandedColumns(new Set());
    void loadDictionary(controller.signal);
    return () => controller.abort();
  }, [dataset.id]);

  useEffect(() => {
    const controller = new AbortController();
    const loadReferenceOptions = async () => {
      setReferenceOptionsError('');
      try {
        const response = await fetch(semanticLayerApi.referenceOptions, {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(await responseMessage(response, 'Không tải được danh sách bảng tham chiếu.'));
        const payload = await response.json() as { datasets?: ReferenceDataset[] };
        setReferenceDatasets(Array.isArray(payload.datasets) ? payload.datasets : []);
      } catch (reason) {
        if ((reason as Error).name !== 'AbortError') {
          setReferenceOptionsError(reason instanceof Error ? reason.message : 'Không tải được danh sách bảng tham chiếu.');
        }
      }
    };
    void loadReferenceOptions();
    return () => controller.abort();
  }, [referenceRevision]);

  const updateColumn = <K extends keyof ColumnDictionary>(columnName: string, field: K, value: ColumnDictionary[K]) => {
    setSaved(false);
    setSaveError('');
    setDictionary(current => current ? {
      ...current,
      columns: current.columns.map(column => (
        column.column_name === columnName ? { ...column, [field]: value } : column
      )),
    } : current);
  };

  const toggleExpanded = (columnName: string) => {
    setExpandedColumns(current => {
      const next = new Set(current);
      if (next.has(columnName)) next.delete(columnName);
      else next.add(columnName);
      return next;
    });
  };

  const updateDataset = <K extends 'display_name' | 'description' | 'grain' | 'create_column' | 'dataset_type' | 'layer_id'>(
    field: K,
    value: DatasetDictionary[K],
  ) => {
    setSaved(false);
    setSaveError('');
    setDictionary(current => current ? { ...current, [field]: value } : current);
  };

  const updateTimeSemantics = (timeSemantics: TimeSemantics) => {
    setSaved(false);
    setSaveError('');
    setDictionary(current => current ? { ...current, ...timeSemantics } : current);
  };

  const suggestDictionary = async () => {
    if (!dictionary || readOnly || suggesting) return;
    setSuggesting(true);
    setSuggestError('');
    setSuggested(false);
    setSuggestProgress('Đang chuẩn bị gợi ý…');
    try {
      const csrfResponse = await fetch(supersetApi.csrfToken, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (!csrfResponse.ok) throw new Error(`Không lấy được CSRF token (${csrfResponse.status}).`);
      const csrfPayload = await csrfResponse.json();
      const csrfToken = csrfPayload?.result || csrfPayload?.csrf_token;
      const response = await fetch(semanticLayerApi.suggestColumnDictionary(dataset.id), {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          Accept: 'text/event-stream',
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({}),
      });
      if (!response.ok) throw new Error(await responseMessage(response, `Không tạo được gợi ý (${response.status}).`));
      if (!response.body) throw new Error('Không nhận được luồng gợi ý từ agent.');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let eventName = 'message';
      let dataLines: string[] = [];
      let receivedSuggestions = false;
      const mergeSuggestions = (existing: ColumnDictionary[], suggestions: ColumnDictionarySuggestion[]) => {
        const suggestionsByName = new Map(suggestions.map(suggestion => [suggestion.column_name, suggestion]));
        return existing.map(column => {
          const suggestion = suggestionsByName.get(column.column_name);
          if (!suggestion) return column;
          const isDefaultDisplayName = !column.display_name.trim() || column.display_name.trim() === column.column_name;
          return {
            ...column,
            display_name: isDefaultDisplayName && suggestion.display_name ? suggestion.display_name : column.display_name,
            unit: column.unit?.trim() ? column.unit : suggestion.unit,
            business_term: column.business_term?.trim() ? column.business_term : suggestion.business_term,
          };
        });
      };
      const applyEvent = (name: string, rawData: string) => {
        if (!rawData) return;
        const payload = JSON.parse(rawData) as {
          total?: number;
          processed?: number;
          message?: string;
          suggestions?: ColumnDictionarySuggestion[];
          dataset?: Pick<DatasetDictionary, 'display_name' | 'description' | 'grain' | 'create_column'>;
        };
        if (name === 'error') throw new Error(payload.message || 'Agent không thể tạo gợi ý.');
        if (name === 'status') {
          setSuggestProgress(payload.message || `Đang xử lý ${payload.processed ?? 0}/${payload.total ?? columns.length} columns…`);
        } else if (name === 'suggestions') {
          if (!Array.isArray(payload.suggestions)) throw new Error('Agent trả về dữ liệu gợi ý không hợp lệ.');
          const suggestions = payload.suggestions;
          receivedSuggestions = true;
          setDictionary(current => current ? {
            ...current,
            columns: mergeSuggestions(current.columns, suggestions),
          } : current);
          setBaseline(current => mergeSuggestions(current, suggestions));
          setSaved(false);
          setSuggested(true);
          setSuggestProgress(`Đã xử lý ${payload.processed ?? payload.total ?? columns.length}/${payload.total ?? columns.length} columns · đã lưu AutoFill.`);
        } else if (name === 'dataset_suggestion') {
          if (!payload.dataset) throw new Error('Agent trả về dictionary dataset không hợp lệ.');
          const datasetSuggestion = payload.dataset;
          setDictionary(current => current ? {
            ...current,
            display_name: !current.display_name.trim() || current.display_name.trim() === current.dataset_name
              ? datasetSuggestion.display_name
              : current.display_name,
            description: current.description?.trim() ? current.description : datasetSuggestion.description,
            grain: current.grain?.trim() ? current.grain : datasetSuggestion.grain,
            create_column: current.create_column || datasetSuggestion.create_column,
          } : current);
          setDatasetBaseline(current => ({ ...current, ...datasetSuggestion }));
          setSaved(false);
          setSuggested(true);
          setSuggestProgress('Đã lưu AutoFill cho dictionary dataset.');
        } else if (name === 'done') {
          setSuggestProgress(`Hoàn tất AutoFill dataset và ${payload.processed ?? payload.total ?? columns.length}/${payload.total ?? columns.length} columns.`);
          setSuggested(receivedSuggestions);
        }
      };
      const consume = (chunk: string) => {
        buffer += chunk;
        let boundary = buffer.indexOf('\n');
        while (boundary !== -1) {
          const line = buffer.slice(0, boundary).replace(/\r$/, '');
          buffer = buffer.slice(boundary + 1);
          if (!line) {
            applyEvent(eventName, dataLines.join('\n'));
            eventName = 'message';
            dataLines = [];
          } else if (line.startsWith('event:')) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trimStart());
          }
          boundary = buffer.indexOf('\n');
        }
      };
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        consume(decoder.decode(value, { stream: true }));
      }
      consume(decoder.decode());
      if (buffer) {
        const line = buffer.replace(/\r$/, '');
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
      }
      if (buffer || dataLines.length) applyEvent(eventName, dataLines.join('\n'));
      if (!receivedSuggestions) setSuggestProgress('Hoàn tất. Không có trường trống cần gợi ý.');
    } catch (reason) {
      setSuggestError(reason instanceof Error ? reason.message : 'Không tạo được gợi ý data dictionary.');
    } finally {
      setSuggesting(false);
    }
  };

  const saveChanges = async () => {
    if (!dictionary || !dirty || dictionary.read_only) return;
    setSaving(true);
    setSaveError('');
    setSaved(false);
    try {
      const csrfResponse = await fetch(supersetApi.csrfToken, {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      if (!csrfResponse.ok) throw new Error(`Không lấy được CSRF token (${csrfResponse.status}).`);
      const csrfPayload = await csrfResponse.json();
      const csrfToken = csrfPayload?.result || csrfPayload?.csrf_token;
      const response = await fetch(semanticLayerApi.datasetDictionary(dataset.id), {
        method: 'PUT',
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({
          dataset: {
            display_name: dictionary.display_name.trim(),
            description: normalizeNullableText(dictionary.description?.trim() ?? ''),
            grain: normalizeNullableText(dictionary.grain?.trim() ?? ''),
            create_column: dictionary.create_column || null,
            dataset_type: dictionary.dataset_type,
            layer_id: dictionary.layer_id ?? null,
            time_column: dictionary.time_column,
            row_kind_column: dictionary.row_kind_column,
            grains: dictionary.grains.map(item => ({ ...item, label: normalizeNullableText(item.label?.trim() ?? '') })),
          },
          columns: columns.map(({ column_name, ...column }) => ({
            column_name,
            ...Object.fromEntries(editableFields.map(field => {
              const value = column[field];
              const nullableText = ['default_value', 'unit', 'format', 'business_term'].includes(field);
              return [field, nullableText && typeof value === 'string' ? normalizeNullableText(value.trim()) : value];
            })),
          })),
        }),
      });
      if (!response.ok) throw new Error(await responseMessage(response, `Không lưu được data dictionary (${response.status}).`));
      const payload = await response.json() as DatasetDictionary;
      setDictionary(payload);
      setBaseline(payload.columns);
      setDatasetBaseline({
        display_name: payload.display_name,
        description: payload.description,
        grain: payload.grain,
        create_column: payload.create_column,
        dataset_type: payload.dataset_type,
        layer_id: payload.layer_id ?? null,
        timeSemantics: JSON.stringify(timeSemanticsOf(payload)),
      });
      setSaved(true);
      onSaved(payload);
      setReferenceRevision(value => value + 1);
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : 'Không lưu được data dictionary.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="sl-dictionary-state"><LoaderCircle className="sl-spin" /><span>Đang tải data dictionary…</span></div>;
  }

  if (error) {
    return (
      <div className="sl-dictionary-state is-error" role="alert">
        <AlertCircle />
        <strong>Không tải được data dictionary</strong>
        <span>{error}</span>
        <button type="button" onClick={() => void loadDictionary()}><RotateCcw /> Thử lại</button>
      </div>
    );
  }

  if (!dictionary) {
    return (
      <div className="sl-dictionary-state">
        <strong>Dataset chưa có column</strong>
        <span>Đồng bộ columns trong Superset rồi tải lại data dictionary.</span>
        <button type="button" onClick={() => void loadDictionary()}><RotateCcw /> Tải lại</button>
      </div>
    );
  }

  const readOnly = dictionary.read_only === true;
  const layerItems: Array<{ label: string; value: number | null }> = [
    { label: 'Chưa phân tầng', value: null },
    ...layerLevels(layers).flatMap((level, index) => level.map(layer => ({ label: `${layer.name} · Cấp ${index + 1}`, value: layer.id }))),
  ];
  const createColumnItems: Array<{ label: string; value: string | null }> = [
    { label: 'Chưa chọn', value: null },
    ...columns.map(column => ({ label: column.column_name, value: column.column_name })),
  ];
  return (
    <section className="sl-dictionary" aria-label={`Data dictionary của ${dictionary.dataset_name}`}>
      <header className="sl-dictionary-toolbar">
        <div>
          <h3>{dictionary.display_name}</h3>
          <p>{columns.length} columns · Chỉnh metadata dùng chung cho AI và báo cáo.</p>
        </div>
        <div className="sl-dictionary-actions">
          {readOnly ? <span className="sl-read-only"><LockKeyhole /> Chỉ đọc</span> : null}
          {dirty && !readOnly ? <span className="sl-dirty-status" role="status">Chưa lưu</span> : null}
          {saved ? <span className="sl-save-success" role="status"><Check /> Đã lưu</span> : null}
          {!readOnly ? (
            <Button variant="outline" disabled={saving || suggesting} onClick={() => void suggestDictionary()} title="Điền metadata còn trống; classification do người dùng chọn">
              {suggesting ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <Sparkles data-icon="inline-start" />}
              {suggesting ? 'Đang điền…' : 'AutoFill'}
            </Button>
          ) : null}
          <Button disabled={!dirty || saving || suggesting || readOnly} onClick={() => void saveChanges()}>
            {saving ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <Save data-icon="inline-start" />}
            {saving ? 'Đang lưu…' : 'Lưu thay đổi'}
          </Button>
        </div>
      </header>
      <div className="sl-metrics-tabs sl-dictionary-tabs" role="tablist" aria-label="Nội dung data dictionary">
        {([
          ['columns', `Cột (${columns.length})`, columnsDirty],
          ['general', 'Thông tin chung', generalDirty],
          ['time', 'Thời gian và grain', timeDirty],
        ] as const).map(([id, label, tabDirty]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => selectTab(id)}>
            {label}
            {tabDirty ? <span className="sl-tab-dirty" title="Có thay đổi chưa lưu" aria-label="Có thay đổi chưa lưu" /> : null}
          </button>
        ))}
      </div>
      <div className="sl-dictionary-body" role="tabpanel">
        {saveError ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {saveError}</div> : null}
        {referenceOptionsError && tab === 'columns' ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {referenceOptionsError}</div> : null}
        {suggestError ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {suggestError}</div> : null}
        {suggestProgress ? <div className="sl-dictionary-suggestion-status" role="status">{suggestProgress}{suggested && !suggesting ? ' Chỉnh sửa thêm thì bấm Lưu thay đổi.' : ''}</div> : null}
        {tab === 'general' ? (
          <div className="sl-dataset-dictionary-fields">
            <Field>
              <FieldLabel htmlFor="sl-dataset-display-name">Dataset name</FieldLabel>
              <Input id="sl-dataset-display-name" disabled={readOnly || saving} value={dictionary.display_name} onChange={event => updateDataset('display_name', event.target.value)} />
            </Field>
            <Field>
              <FieldLabel>Tầng dữ liệu</FieldLabel>
              <div className="flex gap-1.5">
                <Select items={layerItems} value={dictionary.layer_id ?? null} disabled={readOnly || saving} onValueChange={value => updateDataset('layer_id', value)}>
                  <SelectTrigger aria-label="Tầng dữ liệu" className="min-w-0 flex-1"><SelectValue /></SelectTrigger>
                  <SelectContent alignItemWithTrigger={false}>
                    <SelectGroup>
                      {layerItems.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <Button variant="outline" size="icon" aria-label="Quản lý tầng dữ liệu" title="Quản lý tầng dữ liệu" onClick={onManageLayers}><Settings2 /></Button>
              </div>
            </Field>
            <Field>
              <FieldLabel>Classification</FieldLabel>
              <Select items={datasetTypeItems} value={dictionary.dataset_type} disabled={readOnly || saving} onValueChange={value => updateDataset('dataset_type', value)}>
                <SelectTrigger aria-label="Dataset classification" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent alignItemWithTrigger={false}>
                  <SelectGroup>
                    {datasetTypeItems.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel title="Cột ghi nhận thời điểm tạo bản ghi, dùng để lọc theo thời gian">Cột thời gian tạo</FieldLabel>
              <Select items={createColumnItems} value={dictionary.create_column} disabled={readOnly || saving} onValueChange={value => updateDataset('create_column', value)}>
                <SelectTrigger aria-label="Dataset create column" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent alignItemWithTrigger={false}>
                  <SelectGroup>
                    {createColumnItems.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field className="sl-field-wide">
              <FieldLabel htmlFor="sl-dataset-description">Description</FieldLabel>
              <Textarea id="sl-dataset-description" className="max-h-36" disabled={readOnly || saving} value={dictionary.description ?? ''} onChange={event => updateDataset('description', normalizeNullableText(event.target.value))} />
            </Field>
            <Field className="sl-field-wide">
              <FieldLabel htmlFor="sl-dataset-grain" title="Mô tả bằng lời một dòng đại diện cho điều gì; grain dùng để truy vấn khai báo ở mục Thời gian và grain">Mô tả grain</FieldLabel>
              <Textarea id="sl-dataset-grain" className="max-h-36" disabled={readOnly || saving} value={dictionary.grain ?? ''} onChange={event => updateDataset('grain', normalizeNullableText(event.target.value))} />
            </Field>
          </div>
        ) : null}
        {tab === 'time' ? (
          <TimeSemanticsFields
            datasetId={dataset.id}
            columns={columns}
            value={timeSemanticsOf(dictionary)}
            disabled={readOnly || saving}
            onChange={updateTimeSemantics}
          />
        ) : null}
        {tab === 'columns' ? (
          <table className="sl-dictionary-table">
            <thead>
              <tr>
                <th scope="col"><span className="sl-visually-hidden">Chi tiết</span></th>
                <th scope="col">Column</th>
                <th scope="col">Display name</th>
                <th scope="col">Business term</th>
                <th scope="col">Khóa</th>
              </tr>
            </thead>
            <tbody>
              {columns.map(column => {
                const expanded = expandedColumns.has(column.column_name);
                const disabled = readOnly || saving;
                const detailsId = `sl-column-details-${column.id}`;
                const reference = column.referenced_column_name
                  ? `${referenceDatasets.find(item => item.id === column.referenced_dataset_id)?.dataset_name ?? column.referenced_dataset_label ?? ''}.${column.referenced_column_name}`
                  : null;
                return (
                  <React.Fragment key={column.column_name}>
                    <tr className={expanded ? 'is-expanded' : undefined}>
                      <td className="sl-expand-cell">
                        <button type="button" aria-expanded={expanded} aria-controls={detailsId} aria-label={`Chi tiết của ${column.column_name}`} onClick={() => toggleExpanded(column.column_name)}>
                          {expanded ? <ChevronDown /> : <ChevronRight />}
                        </button>
                      </td>
                      <th scope="row">
                        <code title={column.column_name}>{column.column_name}</code>
                        <span className="sl-type-badge" title={column.data_type}>{column.data_type}</span>
                        {column.temporal_kind ? <span className="sl-type-badge is-temporal">{TEMPORAL_KIND_LABELS[column.temporal_kind]}</span> : null}
                      </th>
                      <td><Input aria-label={`Display name của ${column.column_name}`} disabled={disabled} value={column.display_name} onChange={event => updateColumn(column.column_name, 'display_name', event.target.value)} /></td>
                      <td><Textarea aria-label={`Business term của ${column.column_name}`} className="min-h-8 max-h-24 resize-none py-1" disabled={disabled} value={column.business_term ?? ''} onChange={event => updateColumn(column.column_name, 'business_term', normalizeNullableText(event.target.value))} /></td>
                      <td>
                        <div className="sl-key-toggles">
                          <label className={column.is_pk ? 'is-on' : undefined} title="Primary key"><input aria-label={`${column.column_name} là primary key`} type="checkbox" disabled={disabled} checked={column.is_pk} onChange={event => updateColumn(column.column_name, 'is_pk', event.target.checked)} />PK</label>
                          <label className={column.is_fk ? 'is-on' : undefined} title="Foreign key"><input aria-label={`${column.column_name} là foreign key`} type="checkbox" disabled={disabled} checked={column.is_fk} onChange={event => {
                            const checked = event.target.checked;
                            updateColumn(column.column_name, 'is_fk', checked);
                            if (!checked) {
                              updateColumn(column.column_name, 'referenced_dataset_id', null);
                              updateColumn(column.column_name, 'referenced_column_name', null);
                            } else if (!expanded) {
                              toggleExpanded(column.column_name);
                            }
                          }} />FK</label>
                          <label className={column.is_unique ? 'is-on' : undefined} title="Unique"><input aria-label={`${column.column_name} là unique`} type="checkbox" disabled={disabled} checked={column.is_unique} onChange={event => updateColumn(column.column_name, 'is_unique', event.target.checked)} />UQ</label>
                        </div>
                        {reference ? <span className="sl-key-reference" title={reference}>→ {reference}</span> : null}
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="sl-column-details-row" id={detailsId}>
                        <td />
                        <td colSpan={4}>
                          <div className="sl-column-details">
                            <ReferenceFields
                              datasets={referenceDatasets}
                              datasetId={column.referenced_dataset_id}
                              columnName={column.referenced_column_name}
                              sourceColumnName={column.column_name}
                              sourceDatasetId={dataset.id}
                              disabled={disabled}
                              onChange={(referencedDatasetId, referencedColumnName) => {
                                if (referencedDatasetId && referencedColumnName) {
                                  updateColumn(column.column_name, 'is_fk', true);
                                }
                                updateColumn(column.column_name, 'referenced_dataset_id', referencedDatasetId);
                                updateColumn(column.column_name, 'referenced_column_name', referencedColumnName);
                              }}
                            />
                            <label className="sl-column-detail">Default<Input aria-label={`Default value của ${column.column_name}`} disabled={disabled} value={column.default_value ?? ''} onChange={event => updateColumn(column.column_name, 'default_value', normalizeNullableText(event.target.value))} /></label>
                            <label className="sl-column-detail">Unit<Input aria-label={`Unit của ${column.column_name}`} disabled={disabled} value={column.unit ?? ''} onChange={event => updateColumn(column.column_name, 'unit', normalizeNullableText(event.target.value))} /></label>
                            <label className="sl-column-detail">Format<Input aria-label={`Format của ${column.column_name}`} disabled={disabled} value={column.format ?? ''} onChange={event => updateColumn(column.column_name, 'format', normalizeNullableText(event.target.value))} /></label>
                            <label className="sl-column-detail">
                              Kiểu thời gian
                              <Select items={temporalKindItems} value={column.temporal_kind} disabled={disabled} onValueChange={value => updateColumn(column.column_name, 'temporal_kind', value)}>
                                <SelectTrigger aria-label={`Kiểu thời gian của ${column.column_name}`} className="w-full"><SelectValue /></SelectTrigger>
                                <SelectContent alignItemWithTrigger={false}>
                                  <SelectGroup>
                                    {temporalKindItems.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
                                  </SelectGroup>
                                </SelectContent>
                              </Select>
                            </label>
                            <label className="sl-column-detail is-check"><input aria-label={`${column.column_name} nullable`} disabled={disabled} type="checkbox" checked={column.nullable} onChange={event => updateColumn(column.column_name, 'nullable', event.target.checked)} />Nullable</label>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  );
}

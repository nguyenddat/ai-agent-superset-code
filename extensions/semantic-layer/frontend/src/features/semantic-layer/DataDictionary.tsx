import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  LockKeyhole,
  RotateCcw,
  Save,
  Sparkles,
} from 'lucide-react';
import { semanticLayerApi, supersetApi } from './api';
import { ReferenceColumnPicker } from './ReferenceColumnPicker';
import type { ColumnDictionary, ColumnDictionarySuggestion, DashboardDataset, DatasetDictionary, ReferenceDataset } from './types';

type DataDictionaryProps = {
  dataset: DashboardDataset;
  onDirtyChange: (dirty: boolean) => void;
};

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
];
const PAGE_SIZE = 7;

// Grows with its content up to the CSS max-height, then scrolls, so long dataset text stays readable.
function AutoGrowTextarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${element.scrollHeight + element.offsetHeight - element.clientHeight}px`;
  }, [props.value]);
  return <textarea ref={ref} {...props} />;
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

export function DataDictionary({ dataset, onDirtyChange }: DataDictionaryProps) {
  const [dictionary, setDictionary] = useState<DatasetDictionary | null>(null);
  const [baseline, setBaseline] = useState<ColumnDictionary[]>([]);
  const [datasetBaseline, setDatasetBaseline] = useState({
    display_name: '',
    description: null as string | null,
    grain: null as string | null,
    create_column: null as string | null,
    dataset_type: null as DatasetDictionary['dataset_type'],
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
  const [page, setPage] = useState(0);

  const columns = dictionary?.columns ?? [];
  const pageCount = Math.max(1, Math.ceil(columns.length / PAGE_SIZE));
  const pageColumns = columns.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const datasetDirty = dictionary !== null && (
    dictionary.display_name !== datasetBaseline.display_name
    || dictionary.description !== datasetBaseline.description
    || dictionary.grain !== datasetBaseline.grain
    || dictionary.create_column !== datasetBaseline.create_column
    || dictionary.dataset_type !== datasetBaseline.dataset_type
  );
  const dirty = useMemo(
    () => datasetDirty || comparableColumns(columns) !== comparableColumns(baseline),
    [baseline, columns, datasetDirty],
  );

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
    setPage(0);
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
  }, []);

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

  const updateDataset = <K extends 'display_name' | 'description' | 'grain' | 'create_column' | 'dataset_type'>(
    field: K,
    value: DatasetDictionary[K],
  ) => {
    setSaved(false);
    setSaveError('');
    setDictionary(current => current ? { ...current, [field]: value } : current);
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
      });
      setSaved(true);
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
          {!readOnly ? <button type="button" disabled={saving || suggesting} onClick={() => void suggestDictionary()} title="Điền metadata còn trống; classification do người dùng chọn">
            {suggesting ? <LoaderCircle className="sl-spin" /> : <Sparkles />}
            {suggesting ? 'Đang điền…' : 'AutoFill'}
          </button> : null}
          <nav className="sl-dictionary-pagination" aria-label="Phân trang columns">
            <button type="button" aria-label="Trang trước" disabled={page === 0} onClick={() => setPage(current => Math.max(0, current - 1))}><ChevronLeft /></button>
            <span title={`Trang ${page + 1} / ${pageCount}`}>{columns.length === 0 ? '0 columns' : `${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, columns.length)} / ${columns.length}`} · Trang {page + 1}/{pageCount}</span>
            <button type="button" aria-label="Trang sau" disabled={page + 1 >= pageCount} onClick={() => setPage(current => Math.min(pageCount - 1, current + 1))}><ChevronRight /></button>
          </nav>
          <button className="is-primary" type="button" disabled={!dirty || saving || suggesting || readOnly} onClick={() => void saveChanges()}>
            {saving ? <LoaderCircle className="sl-spin" /> : <Save />}
            {saving ? 'Đang lưu…' : 'Lưu thay đổi'}
          </button>
        </div>
      </header>
      <div className="sl-dictionary-body">
        {saveError ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {saveError}</div> : null}
        {referenceOptionsError ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {referenceOptionsError}</div> : null}
        {suggestError ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {suggestError}</div> : null}
        {suggestProgress ? <div className="sl-dictionary-suggestion-status" role="status">{suggestProgress}{suggested && !suggesting ? ' Chỉnh sửa thêm thì bấm Lưu thay đổi.' : ''}</div> : null}
        <div className="sl-dataset-dictionary-fields">
          <label>Dataset name<input aria-label="Dataset display name" disabled={readOnly || saving} value={dictionary.display_name} onChange={event => updateDataset('display_name', event.target.value)} /></label>
          <label>Classification<select aria-label="Dataset classification" disabled={readOnly || saving} value={dictionary.dataset_type ?? ''} onChange={event => updateDataset('dataset_type', (event.target.value || null) as DatasetDictionary['dataset_type'])}>
            <option value="">Chưa phân loại</option>
            <option value="base">Base dataset</option>
            <option value="aggregate">Aggregate dataset</option>
          </select></label>
          <label>Create column<select aria-label="Dataset create column" disabled={readOnly || saving} value={dictionary.create_column ?? ''} onChange={event => updateDataset('create_column', event.target.value || null)}>
            <option value="">Chưa chọn</option>
            {columns.map(column => <option key={column.column_name} value={column.column_name}>{column.column_name}</option>)}
          </select></label>
          <label className="is-description">Description<AutoGrowTextarea aria-label="Dataset description" disabled={readOnly || saving} rows={3} value={dictionary.description ?? ''} onChange={event => updateDataset('description', normalizeNullableText(event.target.value))} /></label>
          <label>Grain<AutoGrowTextarea aria-label="Dataset grain" disabled={readOnly || saving} rows={3} value={dictionary.grain ?? ''} onChange={event => updateDataset('grain', normalizeNullableText(event.target.value))} /></label>
        </div>
        <table className="sl-dictionary-table">
          <thead>
            <tr>
              <th scope="col">Column</th>
              <th scope="col">Display name</th>
              <th scope="col">Data type</th>
              <th scope="col">Nullable</th>
              <th scope="col">Default</th>
              <th scope="col">PK</th>
              <th scope="col">FK</th>
              <th scope="col">Referenced column</th>
              <th scope="col">Unique</th>
              <th scope="col">Unit</th>
              <th scope="col">Format</th>
              <th scope="col">Business term</th>
            </tr>
          </thead>
          <tbody>
            {pageColumns.map(column => (
              <tr key={column.column_name}>
                <th scope="row" data-label="Column"><code title={column.column_name}>{column.column_name}</code></th>
                <td data-label="Display name"><input aria-label={`Display name của ${column.column_name}`} disabled={readOnly || saving} value={column.display_name} onChange={event => updateColumn(column.column_name, 'display_name', event.target.value)} /></td>
                <td data-label="Data type"><input aria-label={`Data type của ${column.column_name}`} readOnly value={column.data_type} /></td>
                <td data-label="Nullable"><input aria-label={`${column.column_name} nullable`} disabled={readOnly || saving} type="checkbox" checked={column.nullable} onChange={event => updateColumn(column.column_name, 'nullable', event.target.checked)} /></td>
                <td data-label="Default"><input aria-label={`Default value của ${column.column_name}`} disabled={readOnly || saving} value={column.default_value ?? ''} onChange={event => updateColumn(column.column_name, 'default_value', normalizeNullableText(event.target.value))} /></td>
                <td data-label="Primary key"><input aria-label={`${column.column_name} là primary key`} disabled={readOnly || saving} type="checkbox" checked={column.is_pk} onChange={event => updateColumn(column.column_name, 'is_pk', event.target.checked)} /></td>
                <td data-label="Foreign key"><input aria-label={`${column.column_name} là foreign key`} disabled={readOnly || saving} type="checkbox" checked={column.is_fk} onChange={event => {
                  const checked = event.target.checked;
                  updateColumn(column.column_name, 'is_fk', checked);
                  if (!checked) {
                    updateColumn(column.column_name, 'referenced_dataset_id', null);
                    updateColumn(column.column_name, 'referenced_column_name', null);
                  }
                }} /></td>
                <td data-label="Referenced column">
                  <ReferenceColumnPicker
                    datasets={referenceDatasets}
                    datasetId={column.referenced_dataset_id}
                    columnName={column.referenced_column_name}
                    disabled={readOnly || saving}
                    onChange={(referencedDatasetId, referencedColumnName) => {
                      if (referencedDatasetId && referencedColumnName) {
                        updateColumn(column.column_name, 'is_fk', true);
                      }
                      updateColumn(column.column_name, 'referenced_dataset_id', referencedDatasetId);
                      updateColumn(column.column_name, 'referenced_column_name', referencedColumnName);
                    }}
                  />
                </td>
                <td data-label="Unique"><input aria-label={`${column.column_name} là unique`} disabled={readOnly || saving} type="checkbox" checked={column.is_unique} onChange={event => updateColumn(column.column_name, 'is_unique', event.target.checked)} /></td>
                <td data-label="Unit"><input aria-label={`Unit của ${column.column_name}`} disabled={readOnly || saving} value={column.unit ?? ''} onChange={event => updateColumn(column.column_name, 'unit', normalizeNullableText(event.target.value))} /></td>
                <td data-label="Format"><input aria-label={`Format của ${column.column_name}`} disabled={readOnly || saving} value={column.format ?? ''} onChange={event => updateColumn(column.column_name, 'format', normalizeNullableText(event.target.value))} /></td>
                <td data-label="Business term"><textarea aria-label={`Business term của ${column.column_name}`} disabled={readOnly || saving} rows={2} value={column.business_term ?? ''} onChange={event => updateColumn(column.column_name, 'business_term', normalizeNullableText(event.target.value))} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

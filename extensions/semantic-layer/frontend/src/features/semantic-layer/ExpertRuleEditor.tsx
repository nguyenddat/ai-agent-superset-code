import React, { useState } from 'react';
import { AlertCircle, LoaderCircle, Plus, Trash2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { expertRulesApi, requestJson } from './api';
import {
  columnValueKind, expertRuleErrorMessage, LIST_OPERATORS, OPERATOR_LABELS, VALUELESS_OPERATORS,
} from './expertRuleFormat';
import type {
  ExpertRule, ExpertRuleColumnOption, ExpertRuleCondition, ExpertRuleConditionValue, ExpertRuleDatasetOption,
  ExpertRuleOperator, ExpertRulePayload, ExpertRuleReference,
} from './types';

type ConditionDraft = { key: number; columnId: string; operator: ExpertRuleOperator; valueText: string };
type PairDraft = { key: number; first: string; second: string };

type OptionItem = { value: string; label: string };

const OPERATOR_ITEMS: OptionItem[] = (Object.keys(OPERATOR_LABELS) as ExpertRuleOperator[])
  .map(operator => ({ value: operator, label: OPERATOR_LABELS[operator] }));
const BOOLEAN_ITEMS: OptionItem[] = [{ value: 'true', label: 'Đúng' }, { value: 'false', label: 'Sai' }];

let nextDraftKey = 1;
const draftKey = () => nextDraftKey++;

function conditionValueText(value: ExpertRuleConditionValue): string {
  if (Array.isArray(value)) return value.map(item => String(item)).join(', ');
  return value === null ? '' : String(value);
}

/** Builds the stored condition, or explains which value does not fit its column. */
function buildCondition(draft: ConditionDraft, column: ExpertRuleColumnOption): ExpertRuleCondition | string {
  const fieldRef = { column_dictionary_id: column.id };
  if (VALUELESS_OPERATORS.includes(draft.operator)) {
    return { field_ref: fieldRef, operator: draft.operator, value_type: 'null', value: null };
  }
  const kind = columnValueKind(column.data_type);
  const parse = (text: string): string | number | boolean | null => {
    if (kind === 'number') return text.trim() === '' || Number.isNaN(Number(text)) ? null : Number(text);
    if (kind === 'boolean') return text === 'true';
    return text.trim() || null;
  };
  if (LIST_OPERATORS.includes(draft.operator)) {
    const items = draft.valueText.split(',').map(item => item.trim()).filter(Boolean).map(parse);
    if (items.length === 0 || items.includes(null)) {
      return `Nhập danh sách giá trị hợp lệ cho "${column.display_name}".`;
    }
    return { field_ref: fieldRef, operator: draft.operator, value_type: 'array', value: items };
  }
  const value = parse(draft.valueText);
  if (value === null) return `Nhập giá trị ${kind === 'number' ? 'số ' : ''}cho "${column.display_name}".`;
  return { field_ref: fieldRef, operator: draft.operator, value_type: kind, value };
}

/** A labelled select; an item whose value is null stands for "none". */
export function OptionSelect<Value extends string | null = string>({
  label, items, value, placeholder, className = 'w-full min-w-0', size = 'sm', disabled, onChange,
}: {
  label: string;
  items: Array<{ value: Value; label: string }>;
  value: Value | null;
  placeholder?: string;
  className?: string;
  size?: 'sm' | 'default';
  disabled?: boolean;
  onChange: (value: Value) => void;
}) {
  return (
    <Select items={items} value={value} disabled={disabled} onValueChange={selected => onChange(selected as Value)}>
      <SelectTrigger size={size} aria-label={label} className={className}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent alignItemWithTrigger={false}>
        <SelectGroup>
          {items.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

function ReferencePicker({ label, available, selectedIds, onChange }: {
  label: string;
  available: ExpertRuleReference[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
}) {
  const items = available.map(reference => ({ value: String(reference.id), label: reference.name }));
  const nameOf = (id: number) => available.find(reference => reference.id === id)?.name ?? `#${id}`;
  return (
    <div className="sl-metric-trial-field">
      {selectedIds.map(id => (
        <span key={id} className="sl-metric-token">
          {nameOf(id)}
          <button
            type="button"
            aria-label={`Bỏ ${nameOf(id)}`}
            onClick={() => onChange(selectedIds.filter(item => item !== id))}
          >
            <X />
          </button>
        </span>
      ))}
      {available.length === 0 ? <span className="sl-metric-muted">Dataset này chưa có mục nào đã duyệt.</span> : (
        <Select
          multiple
          items={items}
          value={selectedIds.map(String)}
          onValueChange={value => onChange((value as string[]).map(Number))}
        >
          <SelectTrigger size="sm" aria-label={label}><Plus /> Thêm</SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            <SelectGroup>
              {items.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
            </SelectGroup>
          </SelectContent>
        </Select>
      )}
    </div>
  );
}

function PairRows({ rows, firstLabel, secondLabel, firstPlaceholder, secondPlaceholder, addLabel, onChange }: {
  rows: PairDraft[];
  firstLabel: string;
  secondLabel: string;
  firstPlaceholder: string;
  secondPlaceholder: string;
  addLabel: string;
  onChange: (rows: PairDraft[]) => void;
}) {
  const update = (key: number, change: Partial<PairDraft>) => (
    onChange(rows.map(row => (row.key === key ? { ...row, ...change } : row)))
  );
  return (
    <div className="sl-metric-trial-field is-stacked">
      {rows.map(row => (
        <div key={row.key} className="sl-rule-pair">
          <Input
            aria-label={firstLabel}
            value={row.first}
            maxLength={2000}
            placeholder={firstPlaceholder}
            onChange={event => update(row.key, { first: event.target.value })}
          />
          <Input
            aria-label={secondLabel}
            value={row.second}
            maxLength={2000}
            placeholder={secondPlaceholder}
            onChange={event => update(row.key, { second: event.target.value })}
          />
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Xoá dòng"
            onClick={() => onChange(rows.filter(item => item.key !== row.key))}
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => onChange([...rows, { key: draftKey(), first: '', second: '' }])}
      >
        <Plus data-icon="inline-start" /> {addLabel}
      </Button>
    </div>
  );
}

/** Starting values for a new rule; the conditions stay empty because the threshold is the expert's to set. */
export type ExpertRuleDraft = {
  name: string;
  datasetId: number | null;
  glossaryTermIds: number[];
  example: { question: string; intent: string } | null;
};

type ExpertRuleEditorProps = {
  rule: ExpertRule | null;
  draft?: ExpertRuleDraft | null;
  datasets: ExpertRuleDatasetOption[];
  onCancel: () => void;
  onSaved: (ruleId: number) => void;
};

/** Writes a new rule or the next draft of an existing one; saving always leaves a draft for a second reviewer. */
export function ExpertRuleEditor({ rule, draft, datasets, onCancel, onSaved }: ExpertRuleEditorProps) {
  const draftDatasetId = datasets.some(item => item.id === draft?.datasetId) ? draft?.datasetId : undefined;
  const [datasetId, setDatasetId] = useState<number | null>(
    rule?.dataset_id ?? draftDatasetId ?? datasets[0]?.id ?? null,
  );
  const [name, setName] = useState(rule?.name ?? draft?.name ?? '');
  const [conditions, setConditions] = useState<ConditionDraft[]>(() => (
    rule?.conditions.map(condition => ({
      key: draftKey(),
      columnId: String(condition.field_ref.column_dictionary_id),
      operator: condition.operator,
      valueText: conditionValueText(condition.value),
    })) ?? [{ key: draftKey(), columnId: '', operator: 'equals', valueText: '' }]
  ));
  const [exceptions, setExceptions] = useState<PairDraft[]>(() => (
    rule?.exceptions.map(item => ({ key: draftKey(), first: item.when, second: item.outcome })) ?? []
  ));
  const [examples, setExamples] = useState<PairDraft[]>(() => (
    rule?.examples.map(item => ({ key: draftKey(), first: item.question, second: item.intent }))
    ?? [{ key: draftKey(), first: draft?.example?.question ?? '', second: draft?.example?.intent ?? '' }]
  ));
  const dataset = datasets.find(item => item.id === datasetId);
  const [glossaryTermIds, setGlossaryTermIds] = useState<number[]>(() => (
    (rule ? rule.glossary_terms.map(term => term.id) : draft?.glossaryTermIds ?? [])
      .filter(id => dataset?.glossary_terms.some(term => term.id === id))
  ));
  const droppedTerms = (rule?.glossary_terms ?? []).length - glossaryTermIds.length;
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  // A rule builds on its terms: it inherits their approved metrics, and the columns they name are offered first.
  const selectedTerms = (dataset?.glossary_terms ?? []).filter(term => glossaryTermIds.includes(term.id));
  const inheritedMetricIds = [...new Set(selectedTerms.flatMap(term => term.metric_ids))]
    .filter(id => dataset?.metrics.some(metric => metric.id === id));
  const termColumns = new Set(selectedTerms.flatMap(term => term.column_names));
  const columns = dataset?.columns ?? [];
  const columnItems = [...columns]
    .sort((first, second) => Number(termColumns.has(second.column_name)) - Number(termColumns.has(first.column_name)))
    .map(column => ({ value: String(column.id), label: column.display_name || column.column_name }));
  const datasetItems = datasets.map(item => ({ value: String(item.id), label: item.name }));

  const changeDataset = (value: string) => {
    setDatasetId(Number(value));
    setConditions(current => current.map(condition => ({ ...condition, columnId: '' })));
    setGlossaryTermIds([]);
  };
  const updateCondition = (key: number, change: Partial<ConditionDraft>) => setConditions(current => (
    current.map(condition => (condition.key === key ? { ...condition, ...change } : condition))
  ));
  const addCondition = () => setConditions(current => (
    [...current, { key: draftKey(), columnId: '', operator: 'equals', valueText: '' }]
  ));

  const save = async () => {
    if (datasetId === null) return;
    if (glossaryTermIds.length === 0) {
      setSaveError('Chọn ít nhất một thuật ngữ mà rule này dựa trên.');
      return;
    }
    const builtConditions: ExpertRuleCondition[] = [];
    for (const draft of conditions) {
      const column = columns.find(item => String(item.id) === draft.columnId);
      if (!column) {
        setSaveError('Chọn cột cho mọi điều kiện.');
        return;
      }
      const built = buildCondition(draft, column);
      if (typeof built === 'string') {
        setSaveError(built);
        return;
      }
      builtConditions.push(built);
    }
    const filledPairs = (rows: PairDraft[]) => rows.filter(row => row.first.trim() || row.second.trim());
    const payload: ExpertRulePayload = {
      schema_version: 2,
      name: name.trim(),
      dataset_id: datasetId,
      conditions: builtConditions,
      exceptions: filledPairs(exceptions).map(row => ({ when: row.first.trim(), outcome: row.second.trim() })),
      examples: filledPairs(examples).map(row => ({ question: row.first.trim(), intent: row.second.trim() })),
      glossary_term_ids: glossaryTermIds,
      metric_ids: inheritedMetricIds,
    };
    if (payload.examples.length === 0) {
      setSaveError('Thêm ít nhất một câu hỏi mẫu.');
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      const response = rule
        ? await requestJson<{ rule: { id: number } }>(
          expertRulesApi.draft(rule.id), 'PUT', { ...payload, expected_revision: rule.lifecycle_version },
        )
        : await requestJson<{ rule: { id: number } }>(expertRulesApi.rules, 'POST', payload);
      onSaved(response.rule.id);
    } catch (failure) {
      setSaveError(expertRuleErrorMessage(failure instanceof Error ? failure.message : 'Không lưu được rule.'));
      setSaving(false);
    }
  };

  return (
    <div className="sl-metrics-definition">
      <div className="sl-metric-trial-config">
        <span className="sl-metric-trial-label">Dataset</span>
        {rule ? <span className="sl-rule-static">{rule.dataset_name}</span> : (
          <OptionSelect
            label="Dataset"
            items={datasetItems}
            value={datasetId === null ? null : String(datasetId)}
            className="sl-rule-wide"
            onChange={changeDataset}
          />
        )}
        <span className="sl-metric-trial-label">Tên rule</span>
        <Input
          aria-label="Tên rule"
          className="sl-rule-wide"
          value={name}
          maxLength={255}
          placeholder="Ví dụ: Ngày nắng nóng"
          onChange={event => setName(event.target.value)}
        />
        <span className="sl-metric-trial-label">Thuật ngữ</span>
        <ReferencePicker
          label="Thêm thuật ngữ"
          available={dataset?.glossary_terms ?? []}
          selectedIds={glossaryTermIds}
          onChange={setGlossaryTermIds}
        />
        <span className="sl-metric-trial-label">Metric</span>
        <div className="sl-metric-trial-field">
          {inheritedMetricIds.length === 0 ? (
            <span className="sl-metric-muted">Lấy từ thuật ngữ đã chọn.</span>
          ) : inheritedMetricIds.map(id => (
            <span key={id} className="sl-metric-token is-static">
              {dataset?.metrics.find(metric => metric.id === id)?.name ?? `#${id}`}
            </span>
          ))}
        </div>
        <span className="sl-metric-trial-label">Khi nào áp dụng</span>
        <div className="sl-metric-trial-field is-stacked">
          {conditions.map(draft => {
            const column = columns.find(item => String(item.id) === draft.columnId);
            const kind = columnValueKind(column?.data_type);
            const listOperator = LIST_OPERATORS.includes(draft.operator);
            return (
              <div key={draft.key} className="sl-rule-condition">
                <OptionSelect
                  label="Cột"
                  items={columnItems}
                  value={draft.columnId || null}
                  placeholder="Chọn cột"
                  onChange={columnId => updateCondition(draft.key, { columnId })}
                />
                <OptionSelect
                  label="Phép so sánh"
                  items={OPERATOR_ITEMS}
                  value={draft.operator}
                  onChange={operator => updateCondition(draft.key, { operator: operator as ExpertRuleOperator })}
                />
                {VALUELESS_OPERATORS.includes(draft.operator) ? <span /> : kind === 'boolean' && !listOperator ? (
                  <OptionSelect
                    label="Giá trị"
                    items={BOOLEAN_ITEMS}
                    value={draft.valueText || null}
                    placeholder="Chọn"
                    onChange={valueText => updateCondition(draft.key, { valueText })}
                  />
                ) : (
                  <Input
                    aria-label="Giá trị"
                    className="h-7"
                    inputMode={kind === 'number' && !listOperator ? 'decimal' : undefined}
                    value={draft.valueText}
                    placeholder={listOperator ? 'Các giá trị, cách nhau bởi dấu phẩy' : 'Giá trị'}
                    onChange={event => updateCondition(draft.key, { valueText: event.target.value })}
                  />
                )}
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Xoá điều kiện"
                  disabled={conditions.length === 1}
                  onClick={() => setConditions(current => current.filter(item => item.key !== draft.key))}
                >
                  <Trash2 />
                </Button>
              </div>
            );
          })}
          <Button variant="ghost" size="sm" className="self-start" onClick={addCondition}>
            <Plus data-icon="inline-start" /> Thêm điều kiện (và)
          </Button>
        </div>
        <span className="sl-metric-trial-label">Ngoại lệ</span>
        <PairRows
          rows={exceptions}
          firstLabel="Khi"
          secondLabel="Thì"
          firstPlaceholder="Khi… (ví dụ: trạm đang bảo trì)"
          secondPlaceholder="Thì… (ví dụ: bỏ qua số liệu ngày đó)"
          addLabel="Thêm ngoại lệ"
          onChange={setExceptions}
        />
        <span className="sl-metric-trial-label">Câu hỏi mẫu</span>
        <PairRows
          rows={examples}
          firstLabel="Câu hỏi"
          secondLabel="Cách hiểu"
          firstPlaceholder="Người dùng hỏi… (ví dụ: tháng này có mấy ngày nắng nóng?)"
          secondPlaceholder="Cần hiểu là… (ví dụ: đếm số ngày thỏa rule)"
          addLabel="Thêm câu hỏi mẫu"
          onChange={setExamples}
        />
      </div>
      {droppedTerms > 0 ? (
        <p className="sl-metric-muted">Đã bỏ {droppedTerms} thuật ngữ không còn được duyệt.</p>
      ) : null}
      {saveError ? <div className="sl-metric-error" role="alert"><AlertCircle /> {saveError}</div> : null}
      <div className="sl-metrics-actions">
        <Button
          disabled={saving || !name.trim() || datasetId === null || glossaryTermIds.length === 0}
          onClick={() => void save()}
        >
          {saving ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null}
          {rule ? 'Lưu bản nháp mới' : 'Tạo bản nháp'}
        </Button>
        <Button variant="outline" disabled={saving} onClick={onCancel}>Huỷ</Button>
      </div>
    </div>
  );
}

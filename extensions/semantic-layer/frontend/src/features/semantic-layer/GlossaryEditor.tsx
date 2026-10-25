import React, { useState } from 'react';
import { AlertCircle, LoaderCircle, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { requestJson, semanticLayerApi } from './api';
import { OptionSelect } from './ExpertRuleEditor';
import type { GlossaryDatasetOption, GlossaryLink, GlossaryReviewTerm, GlossaryTermPayload } from './types';

/** A link row: the dataset, then `dataset`, `column:<name>` or `metric:<id>` for what in it the term names. */
type LinkDraft = { key: number; datasetId: string; target: string };

let nextLinkKey = 1;
const emptyLink = (): LinkDraft => ({ key: nextLinkKey++, datasetId: '', target: '' });

function linkTarget(link: GlossaryLink): string {
  if (link.kind === 'column') return `column:${link.column_name}`;
  return link.kind === 'metric' ? `metric:${link.metric_id}` : 'dataset';
}

function buildLink(draft: LinkDraft): GlossaryTermPayload['links'][number] {
  const datasetId = Number(draft.datasetId);
  const value = draft.target.slice(draft.target.indexOf(':') + 1);
  if (draft.target.startsWith('column:')) {
    return { kind: 'column', dataset_id: datasetId, column_name: value, metric_id: null };
  }
  if (draft.target.startsWith('metric:')) {
    return { kind: 'metric', dataset_id: datasetId, column_name: null, metric_id: Number(value) };
  }
  return { kind: 'dataset', dataset_id: datasetId, column_name: null, metric_id: null };
}

const GLOSSARY_ERRORS: Array<[string, string]> = [
  ['already exists', 'Đã có thuật ngữ cùng tên.'],
  ['changed; refresh', 'Thuật ngữ vừa được thay đổi ở nơi khác; tải lại rồi thử lại.'],
  ['cannot approve', 'Người soạn thuật ngữ không thể tự duyệt; cần một quản trị viên khác duyệt.'],
  ['Duplicate glossary link', 'Có hai liên kết giống nhau.'],
  ['At least one glossary link', 'Thêm ít nhất một liên kết.'],
  ['Invalid glossary link', 'Có liên kết không còn hợp lệ: cột hoặc metric đã bị xoá hay đổi.'],
  ['only approved metrics', 'Thuật ngữ chỉ được gắn metric đã duyệt.'],
  ['synonym cannot duplicate', 'Từ đồng nghĩa không được trùng tên thuật ngữ.'],
  ['definition must be', 'Nhập định nghĩa.'],
  ['canonical_name must be', 'Nhập tên thuật ngữ.'],
  ['too long', 'Nội dung quá dài.'],
];

/** Shows a backend glossary error in Vietnamese; messages the backend already writes in Vietnamese pass through. */
export function glossaryErrorMessage(message: string): string {
  return GLOSSARY_ERRORS.find(([fragment]) => message.includes(fragment))?.[1] ?? message;
}

/** Starting values for a new term, such as the one AI Agent proposed for a question it could not resolve. */
export type GlossaryDraft = {
  name: string;
  definition: string;
  synonyms: string[];
  link: { datasetId: number; target: string } | null;
};

type GlossaryEditorProps = {
  term: GlossaryReviewTerm | null;
  draft?: GlossaryDraft | null;
  datasets: GlossaryDatasetOption[];
  onCancel: () => void;
  onSaved: (termId: number) => void;
};

/** Writes a new term or the next draft of an existing one; saving always leaves a draft to approve. */
export function GlossaryEditor({ term, draft, datasets, onCancel, onSaved }: GlossaryEditorProps) {
  const revision = term?.current_revision ?? null;
  const [name, setName] = useState(term?.canonical_name ?? draft?.name ?? '');
  const [definition, setDefinition] = useState(revision?.definition ?? draft?.definition ?? '');
  const [synonyms, setSynonyms] = useState((revision?.synonyms ?? draft?.synonyms ?? []).join(', '));
  const [links, setLinks] = useState<LinkDraft[]>(() => {
    const savedLinks = revision?.links ?? [];
    if (savedLinks.length === 0 && draft?.link) {
      return [{ key: nextLinkKey++, datasetId: String(draft.link.datasetId), target: draft.link.target }];
    }
    if (savedLinks.length === 0) return [emptyLink()];
    return savedLinks.map(link => (
      { key: nextLinkKey++, datasetId: String(link.dataset_id), target: linkTarget(link) }
    ));
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const datasetItems = datasets.map(dataset => ({ value: String(dataset.id), label: dataset.name }));
  const targetItems = (datasetId: string) => {
    const dataset = datasets.find(item => String(item.id) === datasetId);
    if (!dataset) return [];
    return [
      { value: 'dataset', label: 'Cả dataset' },
      ...dataset.metrics.map(metric => ({ value: `metric:${metric.id}`, label: `Metric: ${metric.name}` })),
      ...dataset.columns.map(column => ({ value: `column:${column.column_name}`, label: `Cột: ${column.name}` })),
    ];
  };
  const updateLink = (key: number, change: Partial<LinkDraft>) => setLinks(current => (
    current.map(link => (link.key === key ? { ...link, ...change } : link))
  ));

  const save = async () => {
    const filledLinks = links.filter(link => link.datasetId && link.target);
    if (filledLinks.length === 0) {
      setSaveError('Thêm ít nhất một liên kết tới dataset, cột hoặc metric.');
      return;
    }
    const payload: GlossaryTermPayload = {
      canonical_name: name.trim(),
      definition: definition.trim(),
      synonyms: synonyms.split(',').map(value => value.trim()).filter(Boolean),
      owner_id: term?.owner_id ?? null,
      steward_id: term?.steward_id ?? null,
      provenance: revision?.provenance ?? 'manual',
      links: filledLinks.map(buildLink),
    };
    setSaving(true);
    setSaveError('');
    try {
      const response = term && revision
        ? await requestJson<{ term: { id: number } }>(
          semanticLayerApi.glossaryDraft(term.id), 'PUT', { ...payload, expected_revision: revision.revision_number },
        )
        : await requestJson<{ term: { id: number } }>(semanticLayerApi.glossary, 'POST', payload);
      onSaved(response.term.id);
    } catch (failure) {
      setSaveError(glossaryErrorMessage(failure instanceof Error ? failure.message : 'Không lưu được thuật ngữ.'));
      setSaving(false);
    }
  };

  return (
    <div className="sl-metrics-definition">
      <div className="sl-metric-trial-config">
        <span className="sl-metric-trial-label">Tên thuật ngữ</span>
        {term ? <span className="sl-rule-static">{term.canonical_name}</span> : (
          <Input
            aria-label="Tên thuật ngữ"
            className="sl-rule-wide"
            value={name}
            maxLength={255}
            placeholder="Ví dụ: Nắng nóng"
            onChange={event => setName(event.target.value)}
          />
        )}
        <span className="sl-metric-trial-label">Định nghĩa</span>
        <Textarea
          aria-label="Định nghĩa"
          className="sl-glossary-definition-input"
          value={definition}
          maxLength={10000}
          placeholder="Thuật ngữ này nghĩa là gì với người dùng nghiệp vụ"
          onChange={event => setDefinition(event.target.value)}
        />
        <span className="sl-metric-trial-label">Từ đồng nghĩa</span>
        <Input
          aria-label="Từ đồng nghĩa"
          className="sl-rule-wide"
          value={synonyms}
          placeholder="Cách nhau bởi dấu phẩy, ví dụ: trời nóng, oi bức"
          onChange={event => setSynonyms(event.target.value)}
        />
        <span className="sl-metric-trial-label">Liên kết</span>
        <div className="sl-metric-trial-field is-stacked">
          {links.map(link => (
            <div key={link.key} className="sl-rule-pair">
              <OptionSelect
                label="Dataset"
                items={datasetItems}
                value={link.datasetId || null}
                placeholder="Chọn dataset"
                onChange={datasetId => updateLink(link.key, { datasetId, target: '' })}
              />
              <OptionSelect
                label="Cột hoặc metric"
                items={targetItems(link.datasetId)}
                value={link.target || null}
                placeholder="Chọn cột hoặc metric"
                onChange={target => updateLink(link.key, { target })}
              />
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Xoá liên kết"
                disabled={links.length === 1}
                onClick={() => setLinks(current => current.filter(item => item.key !== link.key))}
              >
                <Trash2 />
              </Button>
            </div>
          ))}
          <Button
            variant="ghost"
            size="sm"
            className="self-start"
            onClick={() => setLinks(current => [...current, emptyLink()])}
          >
            <Plus data-icon="inline-start" /> Thêm liên kết
          </Button>
        </div>
      </div>
      {saveError ? <div className="sl-metric-error" role="alert"><AlertCircle /> {saveError}</div> : null}
      <div className="sl-metrics-actions">
        <Button disabled={saving || !name.trim() || !definition.trim()} onClick={() => void save()}>
          {saving ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null}
          {term ? 'Lưu bản nháp mới' : 'Tạo bản nháp'}
        </Button>
        <Button variant="outline" disabled={saving} onClick={onCancel}>Huỷ</Button>
      </div>
    </div>
  );
}

import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Ban, DatabaseZap, ExternalLink, Inbox, LoaderCircle, RotateCcw, Save } from 'lucide-react';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { requestJson, semanticLayerApi } from './api';
import { formatTime } from './MetricDefinitionPanel';
import { ReviewDecisionDialog } from './ReviewDecisionDialog';
import type { DatasetProposal, ProposedMetric } from './types';

const STATUS_LABELS: Record<DatasetProposal['status'], string> = {
  pending: 'Chờ duyệt',
  created: 'Đã tạo dataset',
  rejected: 'Đã từ chối',
};

const REJECT_TEXT = {
  title: 'Từ chối đề xuất',
  description: 'AI Agent sẽ không dùng dataset này. Lý do được lưu cùng đề xuất.',
  reasonLabel: 'Lý do từ chối',
  confirmLabel: 'Từ chối',
  reasonRequired: true,
  destructive: true,
};

type Draft = { name: string; label: string; description: string; sql: string; metric: ProposedMetric };

const draftOf = (proposal: DatasetProposal): Draft => ({
  name: proposal.name,
  label: proposal.label,
  description: proposal.description ?? '',
  sql: proposal.sql,
  metric: { ...proposal.metric, unit: proposal.metric.unit ?? '' },
});

const METRIC_FIELDS: Array<{ key: keyof ProposedMetric; label: string }> = [
  { key: 'label', label: 'Tên metric' },
  { key: 'metric_name', label: 'Tên kỹ thuật' },
  { key: 'expression', label: 'Công thức' },
  { key: 'unit', label: 'Đơn vị' },
];

function ProposalDetail({ proposal, busy, onSave, onCreate, onReject }: {
  proposal: DatasetProposal;
  busy: boolean;
  onSave: (draft: Draft) => Promise<boolean>;
  onCreate: (draft: Draft, changed: boolean) => void;
  onReject: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(proposal));
  useEffect(() => setDraft(draftOf(proposal)), [proposal]);
  const pending = proposal.status === 'pending';
  const changed = JSON.stringify(draft) !== JSON.stringify(draftOf(proposal));
  const setMetric = (key: keyof ProposedMetric, value: string) => (
    setDraft(current => ({ ...current, metric: { ...current.metric, [key]: value } }))
  );

  return (
    <>
      <header className="sl-metrics-detail-heading">
        <div className="sl-metrics-title">
          <h3>{proposal.label}</h3>
          {proposal.question ? <p className="sl-question-understood">Từ câu hỏi: {proposal.question}</p> : null}
          <p>
            <span className={`sl-proposal-status is-${proposal.status}`}>{STATUS_LABELS[proposal.status]}</span>
            AI Agent đề xuất khi trả lời {proposal.proposer_name ?? 'người dùng'} · {formatTime(proposal.created_on)}
            {proposal.reviewer_name ? <> · xử lý bởi {proposal.reviewer_name}, {formatTime(proposal.reviewed_on)}</> : null}
          </p>
        </div>
        {pending ? (
          <div className="sl-metrics-actions">
            {busy ? <LoaderCircle className="sl-spin sl-question-busy" /> : null}
            <Button variant="outline" disabled={busy} onClick={onReject}>
              <Ban data-icon="inline-start" /> Từ chối
            </Button>
            <Button variant="outline" disabled={busy || !changed} onClick={() => void onSave(draft)}>
              <Save data-icon="inline-start" /> Lưu thay đổi
            </Button>
            <Button disabled={busy} onClick={() => onCreate(draft, changed)}>
              <DatabaseZap data-icon="inline-start" /> Tạo dataset
            </Button>
          </div>
        ) : proposal.dataset_id ? (
          <div className="sl-metrics-actions">
            <a
              className={buttonVariants({ variant: 'outline' })}
              href={`/explore/?datasource_type=table&datasource_id=${proposal.dataset_id}`}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink data-icon="inline-start" /> Mở dataset
            </a>
          </div>
        ) : null}
      </header>
      <div className="sl-metrics-definition sl-proposal">
        {proposal.review_note ? <p className="sl-proposal-note">Lý do từ chối: {proposal.review_note}</p> : null}
        <section className="sl-metrics-section">
          <h4>Dataset ảo</h4>
          <div className="sl-proposal-fields">
            <label className="sl-metric-decision-field">
              Tên hiển thị
              <Input value={draft.label} disabled={!pending || busy}
                onChange={event => setDraft({ ...draft, label: event.target.value })} />
            </label>
            <label className="sl-metric-decision-field">
              Tên bảng trong Superset
              <Input value={draft.name} disabled={!pending || busy}
                onChange={event => setDraft({ ...draft, name: event.target.value })} />
            </label>
          </div>
          <label className="sl-metric-decision-field">
            Mô tả
            <Textarea value={draft.description} disabled={!pending || busy} className="min-h-14"
              onChange={event => setDraft({ ...draft, description: event.target.value })} />
          </label>
          <label className="sl-metric-decision-field">
            SQL (chỉ đọc các dataset cơ sở: {proposal.sources.map(source => source.name).join(', ')})
            <Textarea value={draft.sql} disabled={!pending || busy} spellCheck={false} className="sl-proposal-sql"
              onChange={event => setDraft({ ...draft, sql: event.target.value })} />
          </label>
        </section>
        <section className="sl-metrics-section">
          <h4>Metric trả lời câu hỏi</h4>
          <div className="sl-proposal-fields">
            {METRIC_FIELDS.map(field => (
              <label key={field.key} className="sl-metric-decision-field">
                {field.label}
                <Input value={draft.metric[field.key] ?? ''} disabled={!pending || busy}
                  onChange={event => setMetric(field.key, event.target.value)} />
              </label>
            ))}
          </div>
          <label className="sl-metric-decision-field">
            Định nghĩa nghiệp vụ
            <Textarea value={draft.metric.definition} disabled={!pending || busy} className="min-h-14"
              onChange={event => setMetric('definition', event.target.value)} />
          </label>
          {pending ? (
            <p className="sl-metric-muted">
              Tạo dataset sẽ chạy SQL để Superset đọc các cột, lưu dataset là bảng tổng hợp trong Data Dictionary và
              đưa metric vào mục Metrics ở trạng thái chờ duyệt.
            </p>
          ) : null}
        </section>
      </div>
    </>
  );
}

/** Datasets the AI Agent drafted over base datasets because no aggregate dataset could answer a question. */
export function DatasetProposalReview() {
  const [proposals, setProposals] = useState<DatasetProposal[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [rejecting, setRejecting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setProposals((await requestJson<{ proposals: DatasetProposal[] }>(semanticLayerApi.datasetProposals, 'GET')).proposals);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được đề xuất dataset.');
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const selected = proposals?.find(proposal => proposal.id === selectedId) ?? proposals?.[0] ?? null;

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      setError('');
      await load();
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không lưu được.');
      return false;
    } finally {
      setBusy(false);
    }
  };
  const save = (proposal: DatasetProposal, draft: Draft) => act(
    () => requestJson(semanticLayerApi.datasetProposal(proposal.id), 'PUT', draft),
  );
  // Unsaved edits are saved first, so the dataset is created from what the administrator sees.
  const create = async (proposal: DatasetProposal, draft: Draft, changed: boolean) => {
    if (changed && !(await save(proposal, draft))) return;
    await act(() => requestJson(semanticLayerApi.datasetProposalCreate(proposal.id), 'POST', {}));
  };
  const reject = async (reason: string) => {
    if (!selected) return;
    if (await act(() => requestJson(semanticLayerApi.datasetProposalReject(selected.id), 'POST', { reason }))) {
      setRejecting(false);
    }
  };

  return (
    <div className="sl-metrics sl-question-review">
      <aside className="sl-metrics-browser" aria-label="Danh sách đề xuất dataset">
        <div className="sl-metrics-browser-filters">
          <div className="sl-metrics-search">
            <span className="sl-proposal-count">
              {proposals ? `${proposals.filter(item => item.status === 'pending').length} đề xuất chờ duyệt` : ''}
            </span>
            <Button variant="ghost" size="icon" aria-label="Tải lại" disabled={loading} onClick={() => void load()}>
              {loading ? <LoaderCircle className="sl-spin" /> : <RotateCcw />}
            </Button>
          </div>
        </div>
        <div className="sl-metrics-list">
          {proposals === null && loading ? (
            <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải đề xuất…</p>
          ) : (proposals ?? []).length === 0 ? (
            <p className="sl-metric-muted sl-question-list-empty">Chưa có đề xuất dataset nào.</p>
          ) : (proposals ?? []).map(proposal => (
            <button
              key={proposal.id}
              type="button"
              className={`sl-metrics-item sl-question-item${selected?.id === proposal.id ? ' is-selected' : ''}`}
              onClick={() => setSelectedId(proposal.id)}
            >
              <span className="sl-question-item-text">{proposal.label}</span>
              <span className="sl-question-item-meta">
                {STATUS_LABELS[proposal.status]}
                <span>{formatTime(proposal.created_on)}</span>
              </span>
            </button>
          ))}
        </div>
      </aside>
      <section className="sl-metrics-detail" aria-label="Chi tiết đề xuất">
        {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
        {selected ? (
          <ProposalDetail
            proposal={selected}
            busy={busy}
            onSave={draft => save(selected, draft)}
            onCreate={(draft, changed) => void create(selected, draft, changed)}
            onReject={() => setRejecting(true)}
          />
        ) : (
          <div className="sl-question-empty">
            <Inbox aria-hidden="true" />
            <p>Khi không bảng tổng hợp nào trả lời được câu hỏi, AI Agent soạn dataset từ bảng cơ sở và gửi về đây.</p>
          </div>
        )}
      </section>
      <ReviewDecisionDialog
        text={rejecting ? REJECT_TEXT : null}
        subject={selected?.label ?? ''}
        reasonMaxLength={2000}
        busy={busy}
        onConfirm={reason => void reject(reason)}
        onClose={() => setRejecting(false)}
      />
    </div>
  );
}

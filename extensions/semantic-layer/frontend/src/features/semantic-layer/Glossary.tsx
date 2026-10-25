import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Ban, Check, ChevronRight, LoaderCircle, Pencil, Plus, RotateCcw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import { GlossaryEditor, glossaryErrorMessage } from './GlossaryEditor';
import { formatTime } from './MetricDefinitionPanel';
import { ReviewDecisionDialog } from './ReviewDecisionDialog';
import type { ReviewDecisionText } from './ReviewDecisionDialog';
import type {
  GlossaryAuditEvent, GlossaryDatasetOption, GlossaryLink, GlossaryReviewTerm, GlossaryState, GlossaryTermList,
} from './types';

const STATE_LABELS: Record<GlossaryState, string> = {
  draft: 'Chờ duyệt',
  approved: 'Đã duyệt',
  outdated: 'Hết hiệu lực',
  revoked: 'Đã thu hồi',
};

const STATE_ORDER: GlossaryState[] = ['draft', 'outdated', 'approved', 'revoked'];

const AUDIT_LABELS: Record<GlossaryAuditEvent['action'], string> = {
  created: 'tạo thuật ngữ',
  updated: 'sửa nội dung',
  approved: 'duyệt',
  revoked: 'thu hồi',
};

const AUDIT_CLASSES: Record<GlossaryAuditEvent['action'], string> = {
  created: 'is-candidate',
  updated: 'is-candidate',
  approved: 'is-approve',
  revoked: 'is-revoke',
};

type TermDecision = 'approve' | 'revoke';

const DECISION_TEXT: Record<TermDecision, ReviewDecisionText> = {
  approve: {
    title: 'Duyệt thuật ngữ',
    description: 'Sau khi duyệt, thuật ngữ được đưa vào semantic layer cho người dùng có quyền trên dataset liên kết.',
    reasonLabel: 'Ghi chú khi duyệt (không bắt buộc)',
    confirmLabel: 'Duyệt',
    reasonRequired: false,
  },
  revoke: {
    title: 'Thu hồi thuật ngữ',
    description: 'Thuật ngữ sẽ không được dùng nữa cho tới khi được sửa và duyệt lại.',
    reasonLabel: 'Lý do thu hồi (bắt buộc)',
    confirmLabel: 'Thu hồi',
    reasonRequired: true,
    destructive: true,
  },
};

const formatDate = (value: string | null | undefined) => formatTime(value ?? null).split(' ').pop() ?? '';

/** One line on who moved the term into its current state, or what it needs next. */
function reviewSummary(term: GlossaryReviewTerm, viewerId: number | null, secondReviewerRequired: boolean): string {
  switch (term.state) {
    case 'approved':
      return `Duyệt bởi ${term.approver_name ?? '—'} · ${formatDate(term.current_revision.approved_at)}`;
    case 'draft':
      if (term.author_id !== viewerId) return `Soạn bởi ${term.author_name ?? '—'} · chờ duyệt`;
      return secondReviewerRequired ? 'Bạn đã soạn · cần một quản trị viên khác duyệt' : 'Bạn đã soạn · chờ duyệt';
    case 'outdated':
      return 'Cột hoặc metric liên kết đã thay đổi · cần sửa và duyệt lại';
    default:
      return `Thu hồi bởi ${term.revoker_name ?? '—'} · ${formatDate(term.current_revision.revoked_at)}`;
  }
}

function linkLabel(link: GlossaryLink): string {
  const dataset = link.dataset_name ?? 'Dataset đã xoá';
  if (link.kind === 'dataset') return `Dataset: ${dataset}`;
  const kind = link.kind === 'metric' ? 'Metric' : 'Cột';
  return `${kind}: ${link.target_name ?? link.column_name ?? `#${link.metric_id}`} · ${dataset}`;
}

function TermHistory({ term, revision }: { term: GlossaryReviewTerm; revision: number }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<GlossaryAuditEvent[] | null>(null);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    setEntries(null);
    setLoadError('');
    requestJson<{ events: GlossaryAuditEvent[] }>(semanticLayerApi.glossaryAudit(term.id), 'GET')
      .then(payload => { if (active) setEntries([...payload.events].reverse()); })
      .catch(reason => {
        if (active) setLoadError(reason instanceof Error ? reason.message : 'Không tải được lịch sử.');
      });
    return () => { active = false; };
  }, [open, term.id, revision]);

  return (
    <section className="sl-metrics-section">
      <button type="button" className="sl-metrics-disclosure" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ChevronRight /> Lịch sử duyệt
      </button>
      {!open ? null : loadError ? (
        <div className="sl-metric-error" role="alert"><AlertCircle /> {loadError}</div>
      ) : entries === null ? (
        <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải lịch sử…</p>
      ) : (
        <ol className="sl-metrics-history">
          {entries.map(entry => (
            <li key={entry.id} className={AUDIT_CLASSES[entry.action]}>
              <div>
                <strong>{entry.actor_name ?? 'Người dùng đã xoá'}</strong> {AUDIT_LABELS[entry.action]}
                {entry.action === 'created' || entry.action === 'updated' ? ` (bản ${entry.revision_number})` : ''}
              </div>
              <time>{formatTime(entry.created_at)}</time>
              {entry.reason ? <blockquote>{entry.reason}</blockquote> : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function TermDetail({ term, historyRevision }: { term: GlossaryReviewTerm; historyRevision: number }) {
  const revision = term.current_revision;
  return (
    <div className="sl-metrics-definition" role="tabpanel">
      <section className="sl-metrics-section">
        <h4>Định nghĩa</h4>
        <p className="sl-glossary-definition">{revision.definition}</p>
      </section>
      {revision.synonyms.length > 0 ? (
        <section className="sl-metrics-section">
          <h4>Từ đồng nghĩa</h4>
          <div className="sl-metric-trial-field">
            {revision.synonyms.map(synonym => (
              <span key={synonym} className="sl-metric-token is-static">{synonym}</span>
            ))}
          </div>
        </section>
      ) : null}
      <section className="sl-metrics-section">
        <h4>Liên kết</h4>
        <div className="sl-metric-trial-field">
          {revision.links.map(link => (
            <span key={linkLabel(link)} className="sl-metric-token is-static">{linkLabel(link)}</span>
          ))}
        </div>
      </section>
      <TermHistory term={term} revision={historyRevision} />
    </div>
  );
}

/** Admin workspace for the business glossary: write a draft term, approve it, revoke it with a reason. */
export function Glossary() {
  const [termList, setTermList] = useState<GlossaryTermList>(
    { terms: [], current_user_id: null, require_second_reviewer: false },
  );
  const [datasets, setDatasets] = useState<GlossaryDatasetOption[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editing, setEditing] = useState<'new' | 'existing' | null>(null);
  const [stateFilter, setStateFilter] = useState<GlossaryState | 'all'>('all');
  const [searchText, setSearchText] = useState('');
  const [loading, setLoading] = useState(true);
  const [openDecision, setOpenDecision] = useState<TermDecision | null>(null);
  const [deciding, setDeciding] = useState(false);
  // Bumped after every change so an open history fetches the new events.
  const [historyRevision, setHistoryRevision] = useState(0);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [terms, options] = await Promise.all([
        requestJson<GlossaryTermList>(semanticLayerApi.glossary, 'GET'),
        requestJson<{ datasets: GlossaryDatasetOption[] }>(semanticLayerApi.glossaryOptions, 'GET'),
      ]);
      setTermList(terms);
      setDatasets(options.datasets);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được danh sách thuật ngữ.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const stateCounts = useMemo(() => {
    const counts = new Map<GlossaryState, number>();
    termList.terms.forEach(term => counts.set(term.state, (counts.get(term.state) ?? 0) + 1));
    return counts;
  }, [termList]);
  const visibleTerms = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    const matches = (term: GlossaryReviewTerm) => [term.canonical_name, ...term.current_revision.synonyms]
      .some(name => name.toLowerCase().includes(query));
    const stateMatches = (term: GlossaryReviewTerm) => stateFilter === 'all' || term.state === stateFilter;
    return termList.terms.filter(term => stateMatches(term) && (!query || matches(term)));
  }, [termList, stateFilter, searchText]);

  const selectedTerm = termList.terms.find(term => term.id === selectedId) ?? visibleTerms[0] ?? null;
  const stateItems = [
    { value: 'all', label: `Mọi trạng thái (${termList.terms.length})` },
    ...STATE_ORDER.map(state => ({ value: state, label: `${STATE_LABELS[state]} (${stateCounts.get(state) ?? 0})` })),
  ];

  const refreshAfterChange = async (termId: number | null) => {
    if (termId !== null) setSelectedId(termId);
    await load();
    setHistoryRevision(revision => revision + 1);
  };

  const decide = async (decision: TermDecision, reason: string) => {
    if (!selectedTerm) return;
    const endpoint = (decision === 'approve' ? semanticLayerApi.glossaryApprove : semanticLayerApi.glossaryRevoke)(
      selectedTerm.id,
    );
    setDeciding(true);
    setError('');
    try {
      const body = { expected_revision: selectedTerm.current_revision.revision_number, reason: reason || null };
      await requestJson(endpoint, 'POST', body);
      setOpenDecision(null);
      await refreshAfterChange(selectedTerm.id);
    } catch (failure) {
      setOpenDecision(null);
      setError(glossaryErrorMessage(failure instanceof Error ? failure.message : 'Thao tác không thành công.'));
    } finally {
      setDeciding(false);
    }
  };

  const state = selectedTerm?.state;
  const approvalBlocked = state === 'draft' && termList.require_second_reviewer
    && selectedTerm?.author_id === termList.current_user_id;
  const editorTerm = editing === 'existing' ? selectedTerm : null;
  const isSelected = (term: GlossaryReviewTerm) => editing !== 'new' && selectedTerm?.id === term.id;

  return (
    <div className="sl-metrics">
      <aside className="sl-metrics-browser" aria-label="Danh sách thuật ngữ">
        <div className="sl-metrics-browser-filters">
          <div className="sl-metrics-search">
            <Search />
            <Input
              aria-label="Tìm thuật ngữ"
              placeholder="Tìm thuật ngữ hoặc từ đồng nghĩa"
              value={searchText}
              onChange={event => setSearchText(event.target.value)}
            />
            <Button variant="ghost" size="icon" aria-label="Tải lại" disabled={loading} onClick={() => void load()}>
              {loading ? <LoaderCircle className="sl-spin" /> : <RotateCcw />}
            </Button>
          </div>
          <Select
            items={stateItems}
            value={stateFilter}
            onValueChange={value => setStateFilter(value as GlossaryState | 'all')}
          >
            <SelectTrigger aria-label="Lọc theo trạng thái" className="sl-metrics-filter-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              <SelectGroup>
                {stateItems.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Button variant="outline" disabled={datasets.length === 0} onClick={() => setEditing('new')}>
            <Plus data-icon="inline-start" /> Tạo thuật ngữ
          </Button>
        </div>
        <div className="sl-metrics-list">
          {loading && termList.terms.length === 0 ? (
            <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải thuật ngữ…</p>
          ) : visibleTerms.length === 0 ? (
            <p className="sl-metric-muted">
              {termList.terms.length === 0
                ? 'Chưa có thuật ngữ nào. Bấm "Tạo thuật ngữ" để bắt đầu.'
                : 'Không có thuật ngữ nào khớp bộ lọc.'}
            </p>
          ) : visibleTerms.map(term => (
            <button
              key={term.id}
              type="button"
              className={`sl-metrics-item${isSelected(term) ? ' is-selected' : ''}`}
              onClick={() => { setSelectedId(term.id); setEditing(null); }}
            >
              <span className={`sl-metrics-dot is-${term.state}`} title={STATE_LABELS[term.state]} />
              <span className="sl-metrics-item-name">{term.canonical_name}</span>
            </button>
          ))}
        </div>
      </aside>
      <section className="sl-metrics-detail" aria-label="Chi tiết thuật ngữ">
        {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
        {editing === 'new' || (editing === 'existing' && editorTerm) ? (
          <>
            <header className="sl-metrics-detail-heading is-editing">
              <div className="sl-metrics-title">
                <h3>{editorTerm ? `Sửa: ${editorTerm.canonical_name}` : 'Thuật ngữ mới'}</h3>
                <p>Lưu xong, thuật ngữ ở trạng thái chờ duyệt và chỉ có hiệu lực sau khi được duyệt.</p>
              </div>
            </header>
            <GlossaryEditor
              key={editorTerm?.id ?? 'new'}
              term={editorTerm}
              datasets={datasets}
              onCancel={() => setEditing(null)}
              onSaved={termId => { setEditing(null); void refreshAfterChange(termId); }}
            />
          </>
        ) : !selectedTerm ? (
          <p className="sl-metric-muted sl-rule-empty">Chọn một thuật ngữ để xem chi tiết.</p>
        ) : (
          <>
            <header className="sl-metrics-detail-heading">
              <div className="sl-metrics-title">
                <h3>
                  {selectedTerm.canonical_name}{' '}
                  <span className={`sl-metric-state is-${selectedTerm.state}`}>{STATE_LABELS[selectedTerm.state]}</span>
                </h3>
                <p>{reviewSummary(selectedTerm, termList.current_user_id, termList.require_second_reviewer)}</p>
              </div>
              <div className="sl-metrics-actions">
                <Button variant="outline" disabled={deciding} onClick={() => setEditing('existing')}>
                  <Pencil data-icon="inline-start" /> Sửa
                </Button>
                {state === 'draft' ? (
                  <Button
                    disabled={deciding || approvalBlocked}
                    title={approvalBlocked ? 'Người soạn thuật ngữ không thể tự duyệt.' : undefined}
                    onClick={() => setOpenDecision('approve')}
                  >
                    <Check data-icon="inline-start" /> Duyệt
                  </Button>
                ) : null}
                {state === 'approved' || state === 'outdated' ? (
                  <Button variant="outline" disabled={deciding} onClick={() => setOpenDecision('revoke')}>
                    <Ban data-icon="inline-start" /> Thu hồi
                  </Button>
                ) : null}
              </div>
            </header>
            <TermDetail key={selectedTerm.id} term={selectedTerm} historyRevision={historyRevision} />
          </>
        )}
      </section>
      <ReviewDecisionDialog
        text={openDecision === null ? null : DECISION_TEXT[openDecision]}
        subject={selectedTerm?.canonical_name ?? ''}
        reasonMaxLength={512}
        busy={deciding}
        onConfirm={reason => { if (openDecision) void decide(openDecision, reason); }}
        onClose={() => setOpenDecision(null)}
      />
    </div>
  );
}

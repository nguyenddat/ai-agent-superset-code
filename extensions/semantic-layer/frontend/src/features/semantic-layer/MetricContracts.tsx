import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Ban, Check, FilePlus2, LoaderCircle, RotateCcw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import { MetricDecisionDialog } from './MetricDecisionDialog';
import type { MetricDecision } from './MetricDecisionDialog';
import { formatTime, MetricDefinitionPanel } from './MetricDefinitionPanel';
import { MetricTrial } from './MetricTrial';
import type { MetricContractResponse, MetricReviewItem, MetricReviewList, MetricReviewState } from './types';

const STATE_LABELS: Record<MetricReviewState, string> = {
  not_started: 'Chưa duyệt',
  ineligible: 'Không đủ điều kiện',
  candidate: 'Chờ duyệt',
  approved: 'Đã duyệt',
  outdated: 'Hết hiệu lực',
  revoked: 'Đã thu hồi',
};

const STATE_ORDER: MetricReviewState[] = ['candidate', 'outdated', 'not_started', 'approved', 'revoked', 'ineligible'];

type DetailTab = 'definition' | 'trial';

const metricKey = (metric: MetricReviewItem) => `${metric.dataset_id}:${metric.metric_id}`;
const metricLabel = (metric: MetricReviewItem) => metric.verbose_name || metric.metric_name;

const formatDate = (value: string | null) => formatTime(value).split(' ').pop() ?? '';

/** One line on who moved the metric into its current state, or what it needs next. */
function reviewSummary(metric: MetricReviewItem, viewerId: number | null, secondReviewerRequired: boolean): string {
  const contract = metric.contract;
  switch (metric.state) {
    case 'approved':
      return `Duyệt bởi ${contract?.approver_name ?? '—'} · ${formatDate(contract?.approved_at ?? null)}`;
    case 'candidate':
      if (contract?.owner_id !== viewerId) return `Đề xuất bởi ${contract?.owner_name ?? '—'} · chờ duyệt`;
      return `Bạn đã đề xuất · ${secondReviewerRequired ? 'cần một quản trị viên khác duyệt' : 'chờ duyệt'}`;
    case 'revoked':
      return `Thu hồi bởi ${contract?.revoker_name ?? '—'} · ${formatDate(contract?.revoked_at ?? null)}`;
    case 'outdated':
      return 'Công thức đã đổi sau lần duyệt · cần đề xuất lại';
    case 'not_started':
      return metric.definition ? 'Chưa đề xuất' : 'Chưa có định nghĩa nghiệp vụ';
    default:
      return 'Chưa thể duyệt';
  }
}

function StateBadge({ state }: { state: MetricReviewState }) {
  return <span className={`sl-metric-state is-${state}`}>{STATE_LABELS[state]}</span>;
}

function FilterSelect({ label, items, value, onChange }: {
  label: string;
  items: Array<{ value: string; label: string }>;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select items={items} value={value} onValueChange={selected => onChange(String(selected))}>
      <SelectTrigger aria-label={label} className="sl-metrics-filter-select"><SelectValue /></SelectTrigger>
      <SelectContent alignItemWithTrigger={false}>
        <SelectGroup>
          {items.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

type MetricContractsProps = { databaseId: number | null };

/** Admin workspace listing every saved metric with its review state: propose, approve, revoke and try each metric. */
export function MetricContracts({ databaseId }: MetricContractsProps) {
  const [reviewList, setReviewList] = useState<MetricReviewList>(
    { datasets: [], metrics: [], users: [], current_user_id: null, require_second_reviewer: false },
  );
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<MetricReviewState | 'all'>('all');
  const [datasetFilter, setDatasetFilter] = useState('all');
  const [searchText, setSearchText] = useState('');
  const [activeTab, setActiveTab] = useState<DetailTab>('definition');
  const [loading, setLoading] = useState(true);
  const [openDecision, setOpenDecision] = useState<MetricDecision | null>(null);
  const [deciding, setDeciding] = useState(false);
  // Bumped after every change so the history tab fetches the new events.
  const [historyRevision, setHistoryRevision] = useState(0);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (databaseId === null) return;
    setLoading(true);
    setError('');
    try {
      setReviewList(await requestJson<MetricReviewList>(semanticLayerApi.metricContracts(databaseId), 'GET'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được danh sách metric.');
    } finally {
      setLoading(false);
    }
  }, [databaseId]);
  useEffect(() => { void load(); }, [load]);

  const datasetById = useMemo(() => new Map(reviewList.datasets.map(dataset => [dataset.id, dataset])), [reviewList]);
  const stateCounts = useMemo(() => {
    const counts = new Map<MetricReviewState, number>();
    reviewList.metrics.forEach(metric => counts.set(metric.state, (counts.get(metric.state) ?? 0) + 1));
    return counts;
  }, [reviewList]);
  const visibleMetrics = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    return reviewList.metrics.filter(metric => (
      (stateFilter === 'all' || metric.state === stateFilter)
      && (datasetFilter === 'all' || String(metric.dataset_id) === datasetFilter)
      && (!query || `${metric.metric_name} ${metric.verbose_name ?? ''}`.toLowerCase().includes(query))
    ));
  }, [reviewList, stateFilter, datasetFilter, searchText]);
  const metricGroups = useMemo(() => reviewList.datasets
    .map(dataset => ({ dataset, metrics: visibleMetrics.filter(metric => metric.dataset_id === dataset.id) }))
    .filter(group => group.metrics.length > 0), [reviewList, visibleMetrics]);

  const selectedMetric = reviewList.metrics.find(metric => metricKey(metric) === selectedKey)
    ?? visibleMetrics[0] ?? null;
  const selectedMetricKey = selectedMetric ? metricKey(selectedMetric) : null;
  const stateItems = [
    { value: 'all', label: `Mọi trạng thái (${reviewList.metrics.length})` },
    ...STATE_ORDER.map(state => ({ value: state, label: `${STATE_LABELS[state]} (${stateCounts.get(state) ?? 0})` })),
  ];
  const metricDatasets = reviewList.datasets.filter(dataset => (
    reviewList.metrics.some(metric => metric.dataset_id === dataset.id)
  ));
  const datasetItems = [
    { value: 'all', label: 'Mọi dataset' },
    ...metricDatasets.map(dataset => ({ value: String(dataset.id), label: dataset.name })),
  ];

  const refreshAfterChange = async () => {
    setSelectedKey(selectedMetricKey);
    await load();
    setHistoryRevision(revision => revision + 1);
  };

  const decide = async (decision: MetricDecision, reason: string) => {
    if (!selectedMetric) return;
    const { dataset_id: datasetId, metric_id: metricId } = selectedMetric;
    const endpoints: Record<MetricDecision, string> = {
      candidate: semanticLayerApi.metricContractCandidate(datasetId, metricId),
      approve: semanticLayerApi.metricContractApprove(datasetId, metricId),
      revoke: semanticLayerApi.metricContractRevoke(datasetId, metricId),
    };
    setDeciding(true);
    setError('');
    try {
      await requestJson<MetricContractResponse>(endpoints[decision], 'POST', { reason: reason || null });
      setOpenDecision(null);
      await refreshAfterChange();
    } catch (failure) {
      setOpenDecision(null);
      setError(failure instanceof Error ? failure.message : 'Thao tác không thành công.');
    } finally {
      setDeciding(false);
    }
  };

  if (databaseId === null) return <p className="sl-metric-muted">Chọn database để xem metric.</p>;

  const state = selectedMetric?.state;
  const canPropose = state === 'not_started' || state === 'outdated' || state === 'revoked';
  const canRevoke = state === 'candidate' || state === 'approved' || state === 'outdated';
  const hasDefinition = Boolean(selectedMetric?.definition);
  const proposedByViewer = state === 'candidate' && selectedMetric?.contract?.owner_id === reviewList.current_user_id;
  const approvalBlocked = proposedByViewer && reviewList.require_second_reviewer;
  const canTry = state === 'approved' || state === 'candidate';
  const visibleTab: DetailTab = canTry ? activeTab : 'definition';
  const summary = selectedMetric
    ? reviewSummary(selectedMetric, reviewList.current_user_id, reviewList.require_second_reviewer)
    : '';

  return (
    <div className="sl-metrics">
      <aside className="sl-metrics-browser" aria-label="Danh sách metric">
        <div className="sl-metrics-browser-filters">
          <div className="sl-metrics-search">
            <Search />
            <Input
              aria-label="Tìm metric"
              placeholder="Tìm metric"
              value={searchText}
              onChange={event => setSearchText(event.target.value)}
            />
            <Button variant="ghost" size="icon" aria-label="Tải lại" disabled={loading} onClick={() => void load()}>
              {loading ? <LoaderCircle className="sl-spin" /> : <RotateCcw />}
            </Button>
          </div>
          <FilterSelect
            label="Lọc theo trạng thái"
            items={stateItems}
            value={stateFilter}
            onChange={value => setStateFilter(value as MetricReviewState | 'all')}
          />
          {metricDatasets.length > 1 ? (
            <FilterSelect
              label="Lọc theo dataset"
              items={datasetItems}
              value={datasetFilter}
              onChange={setDatasetFilter}
            />
          ) : null}
        </div>
        <div className="sl-metrics-list">
          {loading && reviewList.metrics.length === 0 ? (
            <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải metric…</p>
          ) : metricGroups.length === 0 ? (
            <p className="sl-metric-muted">Không có metric nào khớp bộ lọc.</p>
          ) : metricGroups.map(({ dataset, metrics }) => (
            <div key={dataset.id} className="sl-metrics-group">
              <h4 title={dataset.name}>{dataset.name}</h4>
              {metrics.map(metric => (
                <button
                  key={metricKey(metric)}
                  type="button"
                  className={`sl-metrics-item${selectedMetricKey === metricKey(metric) ? ' is-selected' : ''}`}
                  onClick={() => setSelectedKey(metricKey(metric))}
                >
                  <span className={`sl-metrics-dot is-${metric.state}`} title={STATE_LABELS[metric.state]} />
                  <span className="sl-metrics-item-name">{metricLabel(metric)}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>
      <section className="sl-metrics-detail" aria-label="Chi tiết metric">
        {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
        {!selectedMetric ? <p className="sl-metric-muted">Chọn một metric để xem chi tiết.</p> : (
          <>
            <header className="sl-metrics-detail-heading">
              <div className="sl-metrics-title">
                <h3>{metricLabel(selectedMetric)} <StateBadge state={selectedMetric.state} /></h3>
                <p><code>{selectedMetric.metric_name}</code> · {summary}</p>
              </div>
              <div className="sl-metrics-actions">
                {canPropose ? (
                  <Button
                    disabled={deciding || !hasDefinition}
                    title={hasDefinition ? undefined : 'Nhập định nghĩa nghiệp vụ trước khi đề xuất.'}
                    onClick={() => setOpenDecision('candidate')}
                  >
                    <FilePlus2 data-icon="inline-start" /> Tạo bản đề xuất
                  </Button>
                ) : null}
                {state === 'candidate' ? (
                  <Button
                    disabled={deciding || approvalBlocked}
                    title={approvalBlocked ? 'Người đề xuất không thể tự duyệt.' : undefined}
                    onClick={() => setOpenDecision('approve')}
                  >
                    <Check data-icon="inline-start" /> Duyệt
                  </Button>
                ) : null}
                {canRevoke ? (
                  <Button variant="outline" disabled={deciding} onClick={() => setOpenDecision('revoke')}>
                    <Ban data-icon="inline-start" /> Thu hồi
                  </Button>
                ) : null}
              </div>
            </header>
            <div className="sl-metrics-tabs" role="tablist" aria-label="Nội dung metric">
              <button
                type="button"
                role="tab"
                aria-selected={visibleTab === 'definition'}
                onClick={() => setActiveTab('definition')}
              >
                Định nghĩa
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={visibleTab === 'trial'}
                disabled={!canTry}
                title={canTry ? undefined : 'Chỉ chạy thử được metric đang chờ duyệt hoặc đã duyệt.'}
                onClick={() => setActiveTab('trial')}
              >
                Chạy thử
              </button>
            </div>
            {visibleTab === 'trial' ? (
              <MetricTrial
                key={selectedMetricKey}
                metric={selectedMetric}
                dataset={datasetById.get(selectedMetric.dataset_id)}
              />
            ) : (
              <MetricDefinitionPanel
                key={selectedMetricKey}
                metric={selectedMetric}
                users={reviewList.users}
                historyRevision={historyRevision}
                onDefinitionSaved={() => void refreshAfterChange()}
              />
            )}
          </>
        )}
      </section>
      <MetricDecisionDialog
        decision={openDecision}
        metricLabel={selectedMetric ? metricLabel(selectedMetric) : ''}
        busy={deciding}
        onConfirm={reason => { if (openDecision) void decide(openDecision, reason); }}
        onClose={() => setOpenDecision(null)}
      />
    </div>
  );
}

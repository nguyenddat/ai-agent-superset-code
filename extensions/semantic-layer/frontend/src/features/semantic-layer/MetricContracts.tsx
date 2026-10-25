import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Ban, Check, FilePlus2, LoaderCircle, RotateCcw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import { MetricTrial } from './MetricTrial';
import type {
  MetricContractResponse, MetricFormula, MetricReviewItem, MetricReviewList, MetricReviewState,
} from './types';

const STATE_LABELS: Record<MetricReviewState, string> = {
  not_started: 'Chưa duyệt',
  ineligible: 'Không đủ điều kiện',
  candidate: 'Chờ duyệt',
  approved: 'Đã duyệt',
  outdated: 'Hết hiệu lực',
  revoked: 'Đã thu hồi',
};

const STATE_HINTS: Record<MetricReviewState, string> = {
  not_started: 'Metric đủ điều kiện nhưng chưa được đề xuất.',
  ineligible: 'Công thức nằm ngoài dạng được hỗ trợ nên chưa thể duyệt.',
  candidate: 'Bản đề xuất đang chờ người duyệt xác nhận công thức.',
  approved: 'Công thức đã được duyệt; AI Agent và người dùng có thể truy vấn metric này.',
  outdated: 'Metric đã bị sửa sau khi đề xuất hoặc duyệt; cần đề xuất và duyệt lại.',
  revoked: 'Bản duyệt đã bị thu hồi; tạo bản đề xuất mới để dùng lại.',
};

const STATE_ORDER: MetricReviewState[] = ['candidate', 'outdated', 'not_started', 'approved', 'revoked', 'ineligible'];

type ContractAction = 'candidate' | 'approve' | 'revoke';
type DetailTab = 'definition' | 'trial';

const metricKey = (metric: MetricReviewItem) => `${metric.dataset_id}:${metric.metric_id}`;
const metricLabel = (metric: MetricReviewItem) => metric.verbose_name || metric.metric_name;
const formatTime = (value: string | null) => (value ? new Date(value).toLocaleString('vi-VN') : '');

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

function FormulaParts({ formula }: { formula: MetricFormula }) {
  const parts = [
    { label: 'Phép tổng hợp', value: formula.aggregation },
    { label: 'Giá trị đo', value: formula.measure_column ?? formula.measure_constant ?? '—' },
    { label: 'Điều kiện lọc dòng', value: formula.condition ?? 'Không có' },
  ];
  return (
    <div className="sl-metrics-formula-parts">
      {parts.map(part => <div key={part.label}><span>{part.label}</span><code>{part.value}</code></div>)}
    </div>
  );
}

type MetricContractsProps = { databaseId: number | null };

/** Admin workspace listing every saved metric with its review state: propose, approve, revoke and try each metric. */
export function MetricContracts({ databaseId }: MetricContractsProps) {
  const [reviewList, setReviewList] = useState<MetricReviewList>({ datasets: [], metrics: [] });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<MetricReviewState | 'all'>('all');
  const [datasetFilter, setDatasetFilter] = useState('all');
  const [searchText, setSearchText] = useState('');
  const [activeTab, setActiveTab] = useState<DetailTab>('definition');
  const [loading, setLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState<ContractAction | null>(null);
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

  const runAction = async (action: ContractAction) => {
    if (!selectedMetric) return;
    const confirmMessage = `Thu hồi bản duyệt của metric "${metricLabel(selectedMetric)}"?`;
    if (action === 'revoke' && !window.confirm(confirmMessage)) return;
    const { dataset_id: datasetId, metric_id: metricId } = selectedMetric;
    const endpoints: Record<ContractAction, string> = {
      candidate: semanticLayerApi.metricContractCandidate(datasetId, metricId),
      approve: semanticLayerApi.metricContractApprove(datasetId, metricId),
      revoke: semanticLayerApi.metricContractRevoke(datasetId, metricId),
    };
    setPendingAction(action);
    setError('');
    try {
      await requestJson<MetricContractResponse>(endpoints[action], 'POST', {});
      setSelectedKey(selectedMetricKey);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Thao tác không thành công.');
    } finally {
      setPendingAction(null);
    }
  };

  if (databaseId === null) return <p className="sl-metric-muted">Chọn database để xem metric.</p>;

  const contract = selectedMetric?.contract ?? null;
  const canPropose = selectedMetric ? ['not_started', 'outdated', 'revoked'].includes(selectedMetric.state) : false;
  const canRevoke = selectedMetric ? ['candidate', 'approved', 'outdated'].includes(selectedMetric.state) : false;
  const canTry = selectedMetric?.state === 'approved';
  const visibleTab: DetailTab = canTry ? activeTab : 'definition';
  const actionIcon = (action: ContractAction, icon: React.ReactNode) => (
    pendingAction === action ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : icon
  );
  const history = contract ? [
    { label: 'Đề xuất', person: contract.owner_name, time: null },
    { label: 'Duyệt', person: contract.approver_name, time: contract.approved_at },
    { label: 'Thu hồi', person: contract.revoker_name, time: contract.revoked_at },
  ].filter(entry => entry.person) : [];

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
                <p><code>{selectedMetric.metric_name}</code> · {datasetById.get(selectedMetric.dataset_id)?.name}</p>
              </div>
              <div className="sl-metrics-actions">
                {canPropose ? (
                  <Button disabled={pendingAction !== null} onClick={() => void runAction('candidate')}>
                    {actionIcon('candidate', <FilePlus2 data-icon="inline-start" />)} Tạo bản đề xuất
                  </Button>
                ) : null}
                {selectedMetric.state === 'candidate' ? (
                  <Button disabled={pendingAction !== null} onClick={() => void runAction('approve')}>
                    {actionIcon('approve', <Check data-icon="inline-start" />)} Duyệt
                  </Button>
                ) : null}
                {canRevoke ? (
                  <Button variant="outline" disabled={pendingAction !== null} onClick={() => void runAction('revoke')}>
                    {actionIcon('revoke', <Ban data-icon="inline-start" />)} Thu hồi
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
                title={canTry ? undefined : 'Chỉ chạy thử được metric đã duyệt.'}
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
              <div className="sl-metrics-definition" role="tabpanel">
                <p className="sl-metrics-hint">{STATE_HINTS[selectedMetric.state]}</p>
                {selectedMetric.ineligibility ? (
                  <div className="sl-metric-warning" role="note">
                    <AlertCircle />
                    <div><strong>Lý do chưa đủ điều kiện</strong><span>{selectedMetric.ineligibility}</span></div>
                  </div>
                ) : null}
                {selectedMetric.description ? (
                  <section className="sl-metrics-section">
                    <h4>Mô tả</h4>
                    <p className="sl-metrics-description">{selectedMetric.description}</p>
                  </section>
                ) : null}
                <section className="sl-metrics-section">
                  <h4>Công thức</h4>
                  {selectedMetric.formula ? <FormulaParts formula={selectedMetric.formula} /> : null}
                  <pre className="sl-metrics-expression">{selectedMetric.expression || '—'}</pre>
                </section>
                {history.length > 0 ? (
                  <section className="sl-metrics-section">
                    <h4>Lịch sử duyệt</h4>
                    <ol className="sl-metrics-history">
                      {history.map(entry => (
                        <li key={entry.label}>
                          <strong>{entry.label}</strong> bởi {entry.person}
                          {entry.time ? <span> · {formatTime(entry.time)}</span> : null}
                        </li>
                      ))}
                    </ol>
                  </section>
                ) : null}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

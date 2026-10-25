import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Ban, Check, FilePlus2, LoaderCircle, RotateCcw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
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

const STATE_HINTS: Record<MetricReviewState, string> = {
  not_started: 'Metric đủ điều kiện nhưng chưa có ai đề xuất. Tạo bản đề xuất để bắt đầu duyệt.',
  ineligible: 'Công thức metric nằm ngoài dạng được hỗ trợ nên chưa thể đưa vào quy trình duyệt.',
  candidate: 'Đã có bản đề xuất, đang chờ người duyệt xác nhận công thức.',
  approved: 'Công thức đã được duyệt. AI Agent và người dùng có thể truy vấn metric này một cách an toàn.',
  outdated: 'Metric đã bị sửa sau khi đề xuất hoặc duyệt. Cần tạo bản đề xuất mới và duyệt lại.',
  revoked: 'Bản duyệt đã bị thu hồi. Tạo bản đề xuất mới nếu muốn dùng lại metric này.',
};

const STATE_ORDER: MetricReviewState[] = ['candidate', 'outdated', 'not_started', 'approved', 'revoked', 'ineligible'];

type ContractAction = 'candidate' | 'approve' | 'revoke';

const metricKey = (metric: MetricReviewItem) => `${metric.dataset_id}:${metric.metric_id}`;
const metricLabel = (metric: MetricReviewItem) => metric.verbose_name || metric.metric_name;
const formatTime = (value: string | null) => (value ? new Date(value).toLocaleString('vi-VN') : '');

function StateBadge({ state }: { state: MetricReviewState }) {
  return <span className={`sl-metric-state is-${state}`}>{STATE_LABELS[state]}</span>;
}

type MetricContractsProps = { databaseId: number | null };

/** Admin workspace listing every saved metric with its review state: propose, approve, revoke and try each metric. */
export function MetricContracts({ databaseId }: MetricContractsProps) {
  const [reviewList, setReviewList] = useState<MetricReviewList>({ datasets: [], metrics: [] });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<MetricReviewState | 'all'>('all');
  const [datasetFilter, setDatasetFilter] = useState('all');
  const [searchText, setSearchText] = useState('');
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
  const datasetItems = [
    { value: 'all', label: 'Tất cả dataset' },
    ...reviewList.datasets.map(dataset => ({ value: String(dataset.id), label: dataset.name })),
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
  const formula = selectedMetric?.formula ?? null;
  const canPropose = selectedMetric ? ['not_started', 'outdated', 'revoked'].includes(selectedMetric.state) : false;
  const canRevoke = selectedMetric ? ['candidate', 'approved', 'outdated'].includes(selectedMetric.state) : false;
  const actionIcon = (action: ContractAction, icon: React.ReactNode) => (
    pendingAction === action ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : icon
  );

  return (
    <div className="sl-metrics">
      <header className="sl-metrics-toolbar">
        <div className="sl-metrics-heading">
          <h3>Metrics</h3>
          <p>Duyệt công thức metric trước khi AI Agent và người dùng truy vấn chúng.</p>
        </div>
        <Button variant="ghost" size="sm" disabled={loading} onClick={() => void load()}>
          <RotateCcw data-icon="inline-start" /> Tải lại
        </Button>
      </header>
      <div className="sl-metrics-filters">
        <div className="sl-metrics-chips" role="group" aria-label="Lọc theo trạng thái">
          <button
            type="button"
            className={`sl-metrics-chip${stateFilter === 'all' ? ' is-active' : ''}`}
            onClick={() => setStateFilter('all')}
          >
            Tất cả <span>{reviewList.metrics.length}</span>
          </button>
          {STATE_ORDER.map(state => (
            <button
              key={state}
              type="button"
              className={`sl-metrics-chip is-${state}${stateFilter === state ? ' is-active' : ''}`}
              onClick={() => setStateFilter(current => current === state ? 'all' : state)}
            >
              {STATE_LABELS[state]} <span>{stateCounts.get(state) ?? 0}</span>
            </button>
          ))}
        </div>
        <div className="sl-metrics-search">
          <Search />
          <Input
            aria-label="Tìm metric"
            placeholder="Tìm metric"
            value={searchText}
            onChange={event => setSearchText(event.target.value)}
          />
        </div>
        <Select items={datasetItems} value={datasetFilter} onValueChange={value => setDatasetFilter(String(value))}>
          <SelectTrigger aria-label="Lọc theo dataset" className="sl-metrics-dataset-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            <SelectGroup>
              {datasetItems.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
      <div className="sl-metrics-layout">
        <section className="sl-metrics-list" aria-label="Danh sách metric">
          {loading && reviewList.metrics.length === 0 ? (
            <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải metric…</p>
          ) : metricGroups.length === 0 ? (
            <p className="sl-metric-muted">Không có metric nào khớp bộ lọc.</p>
          ) : metricGroups.map(({ dataset, metrics }) => (
            <div key={dataset.id} className="sl-metrics-group">
              <h4>{dataset.name}</h4>
              {metrics.map(metric => (
                <button
                  key={metricKey(metric)}
                  type="button"
                  className={`sl-metrics-item${selectedMetricKey === metricKey(metric) ? ' is-selected' : ''}`}
                  onClick={() => setSelectedKey(metricKey(metric))}
                >
                  <span className="sl-metrics-item-name">
                    <strong>{metricLabel(metric)}</strong>
                    {metric.verbose_name ? <small>{metric.metric_name}</small> : null}
                  </span>
                  <StateBadge state={metric.state} />
                </button>
              ))}
            </div>
          ))}
        </section>
        <section className="sl-metrics-detail" aria-label="Chi tiết metric">
          {!selectedMetric ? <p className="sl-metric-muted">Chọn một metric để xem chi tiết.</p> : (
            <>
              <header className="sl-metrics-detail-heading">
                <div>
                  <h3>{metricLabel(selectedMetric)}</h3>
                  <p>
                    <code>{selectedMetric.metric_name}</code> · {datasetById.get(selectedMetric.dataset_id)?.name}
                  </p>
                </div>
                <StateBadge state={selectedMetric.state} />
              </header>
              <p className="sl-metrics-hint">{STATE_HINTS[selectedMetric.state]}</p>
              {selectedMetric.description ? (
                <p className="sl-metrics-description">{selectedMetric.description}</p>
              ) : null}
              {selectedMetric.ineligibility ? (
                <div className="sl-metric-warning" role="note">
                  <AlertCircle />
                  <div><strong>Lý do chưa đủ điều kiện</strong><span>{selectedMetric.ineligibility}</span></div>
                </div>
              ) : null}
              <section className="sl-metrics-formula" aria-label="Công thức">
                <h4>Công thức</h4>
                {formula ? (
                  <dl>
                    <div><dt>Phép tổng hợp</dt><dd>{formula.aggregation}</dd></div>
                    <div>
                      <dt>Giá trị đo</dt><dd><code>{formula.measure_column ?? formula.measure_constant}</code></dd>
                    </div>
                    <div>
                      <dt>Điều kiện lọc dòng</dt>
                      <dd>{formula.condition ? <code>{formula.condition}</code> : 'Không có'}</dd>
                    </div>
                  </dl>
                ) : null}
                <pre className="sl-metrics-expression">{selectedMetric.expression || '—'}</pre>
              </section>
              {contract ? (
                <dl className="sl-metrics-people">
                  <div><dt>Người đề xuất</dt><dd>{contract.owner_name ?? '—'}</dd></div>
                  {contract.approver_name ? (
                    <div>
                      <dt>Người duyệt</dt><dd>{contract.approver_name} · {formatTime(contract.approved_at)}</dd>
                    </div>
                  ) : null}
                  {contract.revoker_name ? (
                    <div>
                      <dt>Người thu hồi</dt><dd>{contract.revoker_name} · {formatTime(contract.revoked_at)}</dd>
                    </div>
                  ) : null}
                </dl>
              ) : null}
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
              {selectedMetric.state === 'approved' ? (
                <MetricTrial
                  key={selectedMetricKey}
                  metric={selectedMetric}
                  dataset={datasetById.get(selectedMetric.dataset_id)}
                />
              ) : null}
            </>
          )}
        </section>
      </div>
    </div>
  );
}

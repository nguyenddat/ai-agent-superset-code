import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle, BookOpen, Check, Inbox, LoaderCircle, Plus, RotateCcw, Ruler, Search, Undo2, UserRound,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { agentDefinitionsApi, requestJson } from './api';
import { requestCreation } from './creationRequest';
import { formatTime } from './MetricDefinitionPanel';
import type { AgentDefinitionKind, AgentDefinitionReviewStatus, AgentUserDefinition } from './types';

const STATUS_LABELS: Record<AgentDefinitionReviewStatus, string> = {
  pending: 'Chưa xem',
  promoted: 'Đã có định nghĩa chung',
  ignored: 'Giữ là cách hiểu cá nhân',
};

const STATUS_ORDER: AgentDefinitionReviewStatus[] = ['pending', 'promoted', 'ignored'];

const KIND_TEXT: Record<AgentDefinitionKind, { label: string; createLabel: string; Icon: LucideIcon }> = {
  glossary: { label: 'Thuật ngữ', createLabel: 'Tạo thuật ngữ chung', Icon: BookOpen },
  expert_rule: { label: 'Khái niệm định tính', createLabel: 'Tạo expert rule chung', Icon: Ruler },
};

type StatusFilter = AgentDefinitionReviewStatus | 'all';

/** Every user's definitions of one concept: the same kind and the same name, ignoring case and spacing. */
type ConceptGroup = {
  key: string;
  kind: AgentDefinitionKind;
  name: string;
  concept: string | null;
  definitions: AgentUserDefinition[];
  userCount: number;
  /** Not yet looked at while any user's definition is new or was changed since. */
  status: AgentDefinitionReviewStatus;
  updatedOn: string | null;
};

const normalizedName = (name: string) => name.trim().replace(/\s+/g, ' ').toLocaleLowerCase('vi');

function groupStatus(definitions: AgentUserDefinition[]): AgentDefinitionReviewStatus {
  if (definitions.some(item => item.review_status === 'pending')) return 'pending';
  return definitions.some(item => item.review_status === 'promoted') ? 'promoted' : 'ignored';
}

function conceptGroups(definitions: AgentUserDefinition[]): ConceptGroup[] {
  const byKey = new Map<string, AgentUserDefinition[]>();
  definitions.forEach(definition => {
    const key = `${definition.kind}:${normalizedName(definition.name)}`;
    byKey.set(key, [...(byKey.get(key) ?? []), definition]);
  });
  return [...byKey.entries()].map(([key, items]) => ({
    key,
    kind: items[0].kind,
    name: items[0].name,
    concept: items.find(item => item.concept)?.concept ?? null,
    definitions: items,
    userCount: new Set(items.map(item => item.user_id)).size,
    status: groupStatus(items),
    updatedOn: items.map(item => item.updated_on ?? '').sort().reverse()[0] || null,
  })).sort((first, second) => (
    second.userCount - first.userCount || (second.updatedOn ?? '').localeCompare(first.updatedOn ?? '')
  ));
}

function ConceptDetail({ group, busy, onCreate, onSettle }: {
  group: ConceptGroup;
  busy: boolean;
  onCreate: () => void;
  onSettle: (status: AgentDefinitionReviewStatus) => void;
}) {
  const { label, createLabel } = KIND_TEXT[group.kind];
  const open = group.status === 'pending';
  return (
    <>
      <header className="sl-metrics-detail-heading">
        <div className="sl-metrics-title">
          <h3>{group.name}</h3>
          {group.concept && normalizedName(group.concept) !== normalizedName(group.name) ? (
            <p className="sl-question-understood">Khái niệm trong câu hỏi: “{group.concept}”</p>
          ) : null}
          <p>
            <span className="sl-question-kind">{label}</span>
            {group.userCount} người dùng · {group.definitions.length} cách hiểu · {STATUS_LABELS[group.status]}
          </p>
        </div>
        <div className="sl-metrics-actions">
          {busy ? <LoaderCircle className="sl-spin sl-question-busy" /> : null}
          {open ? (
            <>
              <Button variant="outline" disabled={busy} onClick={() => onSettle('ignored')}>
                <UserRound data-icon="inline-start" /> Giữ là cách hiểu cá nhân
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => onSettle('promoted')}>
                <Check data-icon="inline-start" /> Đã có định nghĩa chung
              </Button>
              <Button disabled={busy} onClick={onCreate}>
                <Plus data-icon="inline-start" /> {createLabel}
              </Button>
            </>
          ) : (
            <Button variant="outline" disabled={busy} onClick={() => onSettle('pending')}>
              <Undo2 data-icon="inline-start" /> Mở lại
            </Button>
          )}
        </div>
      </header>
      <div className="sl-metrics-definition">
        <p className="sl-definition-review-note">
          Đây là cách hiểu riêng của từng người; AI Agent chỉ dùng cho chính người đó trên dashboard tương ứng. Khi
          nhiều người cùng hỏi về một khái niệm, nên tạo định nghĩa chung với ngưỡng do chuyên gia nghiệp vụ xác định.
          Định nghĩa chung đã duyệt luôn được ưu tiên hơn cách hiểu cá nhân.
        </p>
        <section className="sl-metrics-section">
          <h4>Cách hiểu của người dùng</h4>
          <ul className="sl-definition-review-list">
            {group.definitions.map(definition => (
              <li key={definition.id}>
                <p className="sl-definition-review-text">{definition.definition}</p>
                {definition.question ? <q>{definition.question}</q> : null}
                <span className="sl-definition-review-meta">
                  {definition.defined_by ?? 'Không rõ người dùng'}
                  {definition.dashboard_title ? ` · ${definition.dashboard_title}` : ''}
                  {` · ${formatTime(definition.updated_on)}`}
                  {definition.review_status !== group.status ? ` · ${STATUS_LABELS[definition.review_status]}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}

/**
 * What users defined concepts to mean for themselves, grouped by concept. It is a signal of what people ask about:
 * the administrator covers a popular concept with a shared term or rule, or leaves it as each user's own sense.
 */
export function DefinitionReview() {
  const [filter, setFilter] = useState<StatusFilter>('pending');
  const [definitions, setDefinitions] = useState<AgentUserDefinition[] | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [searchText, setSearchText] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const body = await requestJson<{ definitions: AgentUserDefinition[] }>(agentDefinitionsApi.review, 'GET');
      setDefinitions(body.definitions);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được cách hiểu của người dùng.');
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const groups = useMemo(() => conceptGroups(definitions ?? []), [definitions]);
  const visibleGroups = useMemo(() => {
    const query = normalizedName(searchText);
    return groups.filter(group => (filter === 'all' || group.status === filter) && (!query || [
      group.name, group.concept ?? '', ...group.definitions.map(item => item.definition),
    ].some(text => normalizedName(text).includes(query))));
  }, [groups, filter, searchText]);
  const selectedGroup = visibleGroups.find(group => group.key === selectedKey) ?? visibleGroups[0] ?? null;

  const filterItems = [
    ...STATUS_ORDER.map(status => ({
      value: status,
      label: `${STATUS_LABELS[status]} (${groups.filter(group => group.status === status).length})`,
    })),
    { value: 'all', label: `Mọi trạng thái (${groups.length})` },
  ];

  const settle = async (group: ConceptGroup, status: AgentDefinitionReviewStatus) => {
    setBusy(true);
    try {
      await requestJson(agentDefinitionsApi.review, 'PUT', { ids: group.definitions.map(item => item.id), status });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không lưu được cách xử lý.');
    } finally {
      setBusy(false);
    }
  };

  const create = (group: ConceptGroup) => requestCreation({
    kind: group.kind,
    name: group.name,
    concept: group.concept,
    definitionIds: group.definitions.map(item => item.id),
    userCount: group.userCount,
    exampleQuestion: group.definitions.find(item => item.question)?.question ?? null,
  });

  return (
    <div className="sl-metrics sl-question-review">
      <aside className="sl-metrics-browser" aria-label="Danh sách khái niệm">
        <div className="sl-metrics-browser-filters">
          <div className="sl-metrics-search">
            <Search />
            <Input
              aria-label="Tìm khái niệm"
              placeholder="Tìm khái niệm"
              value={searchText}
              onChange={event => setSearchText(event.target.value)}
            />
            <Button variant="ghost" size="icon" aria-label="Tải lại" disabled={loading} onClick={() => void load()}>
              {loading ? <LoaderCircle className="sl-spin" /> : <RotateCcw />}
            </Button>
          </div>
          <Select items={filterItems} value={filter} onValueChange={value => setFilter(value as StatusFilter)}>
            <SelectTrigger aria-label="Lọc theo cách xử lý" className="sl-metrics-filter-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              <SelectGroup>
                {filterItems.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <div className="sl-metrics-list">
          {definitions === null && loading ? (
            <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải…</p>
          ) : visibleGroups.length === 0 ? (
            <p className="sl-metric-muted sl-question-list-empty">
              {searchText.trim() ? 'Không có khái niệm nào khớp từ khoá.' : 'Không có khái niệm nào trong mục này.'}
            </p>
          ) : visibleGroups.map(group => {
            const { label, Icon } = KIND_TEXT[group.kind];
            return (
              <button
                key={group.key}
                type="button"
                data-kind={group.kind}
                className={`sl-metrics-item sl-question-item${selectedGroup?.key === group.key ? ' is-selected' : ''}`}
                onClick={() => setSelectedKey(group.key)}
              >
                <span className="sl-question-item-text">{group.name}</span>
                <span className="sl-question-item-meta">
                  <span className="sl-definition-review-kind"><Icon aria-hidden="true" /> {label}</span>
                  <span>{group.userCount} người dùng</span>
                </span>
              </button>
            );
          })}
        </div>
      </aside>
      <section className="sl-metrics-detail" aria-label="Chi tiết khái niệm">
        {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
        {selectedGroup ? (
          <ConceptDetail
            group={selectedGroup}
            busy={busy}
            onCreate={() => create(selectedGroup)}
            onSettle={status => void settle(selectedGroup, status)}
          />
        ) : (
          <div className="sl-question-empty">
            <Inbox aria-hidden="true" />
            <p>
              {filter === 'pending' && !searchText.trim() ? 'Không còn cách hiểu nào chưa xem.' : 'Chọn một khái niệm.'}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

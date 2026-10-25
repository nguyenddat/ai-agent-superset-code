import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Ban, Check, Inbox, LoaderCircle, Plus, RotateCcw, Search, Sigma, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { agentQuestionsApi, requestJson } from './api';
import { requestCreation } from './creationRequest';
import { formatTime } from './MetricDefinitionPanel';
import type { AgentReviewQuestion, AgentReviewQuestionList, QuestionHandlingStatus } from './types';

const HANDLING_LABELS: Record<QuestionHandlingStatus, string> = {
  pending: 'Chưa xử lý',
  to_create: 'Đang tạo mới',
  created: 'Đã tạo mới',
  ignored: 'Bỏ qua',
};

const HANDLING_ORDER: QuestionHandlingStatus[] = ['pending', 'to_create', 'created', 'ignored'];


type HandlingFilter = QuestionHandlingStatus | 'all';

const askedText = (question: AgentReviewQuestion) => question.rewritten_question || question.question;

const askedClock = (isoTime: string | null) => (
  isoTime ? new Date(isoTime).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) : ''
);

/** "Hôm nay", "Hôm qua" or the date, so the list reads as a timeline of what users asked. */
function dayLabel(isoTime: string | null): string {
  if (!isoTime) return 'Không rõ ngày';
  const askedDay = new Date(isoTime);
  const today = new Date();
  const daysAgo = Math.round(
    (new Date(today.toDateString()).getTime() - new Date(askedDay.toDateString()).getTime()) / 86_400_000,
  );
  if (daysAgo === 0) return 'Hôm nay';
  if (daysAgo === 1) return 'Hôm qua';
  return askedDay.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

/** The one line that tells the administrator what the proposed metric measures. */
function proposalSummary(question: AgentReviewQuestion): string {
  const { metric } = question.suggestions;
  return metric ? `${metric.definition}${metric.unit ? ` (${metric.unit})` : ''}` : '';
}

function QuestionDetail({ question, busy, onCreate, onHandle }: {
  question: AgentReviewQuestion;
  busy: boolean;
  onCreate: () => void;
  onHandle: (status: QuestionHandlingStatus) => void;
}) {
  const { handling } = question;
  const open = handling.status === 'pending' || handling.status === 'to_create';
  const rewritten = question.rewritten_question && question.rewritten_question !== question.question;
  const foundNames = [...question.glossary_terms, ...question.metrics, ...question.expert_rules].map(item => item.name);
  const kindLabel = question.requires_expert_rule === null ? null
    : question.requires_expert_rule ? 'Định tính' : 'Định lượng';
  return (
    <>
      <header className="sl-metrics-detail-heading">
        <div className="sl-metrics-title">
          <h3>{question.question}</h3>
          {rewritten ? <p className="sl-question-understood">Hiểu là: {question.rewritten_question}</p> : null}
          <p>
            {kindLabel ? (
              <span className={`sl-question-kind${question.requires_expert_rule ? ' is-qualitative' : ''}`}>
                {kindLabel}
              </span>
            ) : null}
            {question.asked_by ?? 'Không rõ người hỏi'} · {formatTime(question.asked_on)}
            {handling.handled_by ? (
              <> · {HANDLING_LABELS[handling.status]} bởi {handling.handled_by}, {formatTime(handling.handled_on)}</>
            ) : null}
          </p>
        </div>
        <div className="sl-metrics-actions">
          {busy ? <LoaderCircle className="sl-spin sl-question-busy" /> : null}
          {open ? (
            <Button variant="outline" disabled={busy} onClick={() => onHandle('ignored')}>
              <Ban data-icon="inline-start" /> Bỏ qua
            </Button>
          ) : (
            <Button variant="outline" disabled={busy} onClick={() => onHandle('pending')}>
              <Undo2 data-icon="inline-start" /> Mở lại
            </Button>
          )}
          {handling.status === 'to_create' ? (
            <Button disabled={busy} onClick={() => onHandle('created')}>
              <Check data-icon="inline-start" /> Hoàn tất
            </Button>
          ) : null}
        </div>
      </header>
      <div className="sl-metrics-definition">
        <section className="sl-metrics-section">
          <h4>Metric cần tạo</h4>
          <ul className="sl-question-proposals">
            <li data-kind="metric">
              <span className="sl-question-kind-icon"><Sigma aria-hidden="true" /></span>
              <div className="sl-question-proposal-body">
                <span className="sl-question-proposal-kind">Metric</span>
                <strong>{question.suggestions.metric?.name || 'Chưa có tên đề xuất'}</strong>
                <p>{proposalSummary(question)}</p>
              </div>
              {open ? (
                <Button variant="outline" size="sm" disabled={busy} onClick={onCreate}>
                  <Plus data-icon="inline-start" /> Tạo mới
                </Button>
              ) : null}
            </li>
          </ul>
        </section>
        {foundNames.length > 0 ? (
          <p className="sl-question-found"><span>Đã có</span> {foundNames.join(' · ')}</p>
        ) : null}
      </div>
    </>
  );
}

/**
 * Questions no approved metric could answer: the administrator adds the metric or ignores the question. Concepts users
 * define for themselves are reviewed separately; they need no administrator to answer a question.
 */
export function MissingMetricReview() {
  const [filter, setFilter] = useState<HandlingFilter>('pending');
  const [reviewList, setReviewList] = useState<AgentReviewQuestionList | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [searchText, setSearchText] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReviewList(await requestJson<AgentReviewQuestionList>(agentQuestionsApi.review(filter, 'metric'), 'GET'));
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được câu hỏi.');
    }
    setLoading(false);
  }, [filter]);

  useEffect(() => { void load(); }, [load]);

  const visibleQuestions = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    const questions = reviewList?.questions ?? [];
    if (!query) return questions;
    return questions.filter(question => [question.question, question.rewritten_question ?? '']
      .some(text => text.toLowerCase().includes(query)));
  }, [reviewList, searchText]);
  const questionGroups = useMemo(() => {
    const groups = new Map<string, AgentReviewQuestion[]>();
    visibleQuestions.forEach(question => {
      const day = dayLabel(question.asked_on);
      groups.set(day, [...(groups.get(day) ?? []), question]);
    });
    return [...groups.entries()];
  }, [visibleQuestions]);
  const selectedQuestion = visibleQuestions.find(question => question.id === selectedId)
    ?? visibleQuestions[0] ?? null;
  const isSelected = (question: AgentReviewQuestion) => selectedQuestion?.id === question.id;

  const counts = reviewList?.counts;
  const total = counts ? Object.values(counts).reduce((sum, count) => sum + count, 0) : 0;
  const filterItems = [
    ...HANDLING_ORDER.map(status => (
      { value: status, label: `${HANDLING_LABELS[status]} (${counts?.[status] ?? 0})` }
    )),
    { value: 'all', label: `Mọi trạng thái (${total})` },
  ];

  const saveHandling = async (question: AgentReviewQuestion, status: QuestionHandlingStatus) => {
    setBusy(true);
    try {
      await requestJson(agentQuestionsApi.handling(question.id), 'PUT', { status });
      await load();
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không lưu được cách xử lý.');
      return false;
    } finally {
      setBusy(false);
    }
  };

  // Creating the metric marks the question "Đang tạo mới", then opens the metrics module with the proposal.
  const create = async (question: AgentReviewQuestion) => {
    if (question.handling.status === 'pending' && !(await saveHandling(question, 'to_create'))) return;
    const handling = { ...question.handling, status: 'to_create' as const };
    requestCreation({ kind: 'metric', question: { ...question, handling } });
  };

  return (
    <div className="sl-metrics sl-question-review">
      <aside className="sl-metrics-browser" aria-label="Danh sách câu hỏi">
        <div className="sl-metrics-browser-filters">
          <div className="sl-metrics-search">
            <Search />
            <Input
              aria-label="Tìm câu hỏi"
              placeholder="Tìm câu hỏi"
              value={searchText}
              onChange={event => setSearchText(event.target.value)}
            />
            <Button variant="ghost" size="icon" aria-label="Tải lại" disabled={loading} onClick={() => void load()}>
              {loading ? <LoaderCircle className="sl-spin" /> : <RotateCcw />}
            </Button>
          </div>
          <Select items={filterItems} value={filter} onValueChange={value => setFilter(value as HandlingFilter)}>
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
          {reviewList === null && loading ? (
            <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải câu hỏi…</p>
          ) : questionGroups.length === 0 ? (
            <p className="sl-metric-muted sl-question-list-empty">
              {searchText.trim() ? 'Không có câu hỏi nào khớp từ khoá.' : 'Không có câu hỏi nào trong mục này.'}
            </p>
          ) : questionGroups.map(([day, questions]) => (
            <div key={day} className="sl-metrics-group">
              <h4>{day}</h4>
              {questions.map(question => (
                <button
                  key={question.id}
                  type="button"
                  className={`sl-metrics-item sl-question-item${isSelected(question) ? ' is-selected' : ''}`}
                  onClick={() => setSelectedId(question.id)}
                >
                  <span className="sl-question-item-text">{askedText(question)}</span>
                  <span className="sl-question-item-meta">
                    {question.suggestions.metric?.name ?? 'Thiếu metric'}
                    <span>{askedClock(question.asked_on)}</span>
                  </span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>
      <section className="sl-metrics-detail" aria-label="Chi tiết câu hỏi">
        {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
        {selectedQuestion ? (
          <QuestionDetail
            question={selectedQuestion}
            busy={busy}
            onCreate={() => void create(selectedQuestion)}
            onHandle={status => void saveHandling(selectedQuestion, status)}
          />
        ) : (
          <div className="sl-question-empty">
            <Inbox aria-hidden="true" />
            <p>
              {filter === 'pending' && !searchText.trim() ? 'Không còn câu hỏi nào thiếu metric chờ xử lý.'
                : 'Chọn một câu hỏi.'}
            </p>
          </div>
        )}
      </section>
    </div>
  );
}

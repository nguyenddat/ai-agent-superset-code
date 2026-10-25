import React, { useEffect, useRef, useState } from 'react';
import { Check, ChevronRight, CornerDownRight, LoaderCircle, MessageCircleQuestion, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ChatStreamEvent, ClarificationState, ConfirmedDefinition, DefinitionDraft, DefinitionKind, MissingKind,
  QuestionStatus, StoredTurn, UsedDefinition,
} from '../../../shared/api/chat';

const TOOL_LABELS: Record<string, string> = {
  rewrite_question: 'Viết lại câu hỏi',
  load_semantic_catalog: 'Tải dữ liệu quản trị nghiệp vụ',
  identify_glossary_terms: 'Xác định thuật ngữ',
  identify_metrics: 'Xác định metric',
  identify_expert_rules: 'Phân loại câu hỏi và xác định expert rule',
  propose_missing_items: 'Đề xuất phần còn thiếu',
};

const MISSING_LABELS: Record<MissingKind, string> = {
  glossary: 'thuật ngữ',
  metric: 'metric',
  expert_rule: 'expert rule',
};

export const DEFINITION_KIND_LABELS: Record<DefinitionKind, string> = {
  glossary: 'Thuật ngữ',
  expert_rule: 'Cách hiểu khái niệm',
};

export type ToolCall = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  status: 'running' | 'ok' | 'error';
  result?: unknown;
  error?: string;
  durationMs?: number;
};

export type Turn = {
  id: number;
  question: string;
  toolCalls: ToolCall[];
  answer: string;
  state: 'streaming' | 'done' | 'stopped' | 'error';
  error?: string;
  outcome?: { status: QuestionStatus; missing: MissingKind[] };
  questionId?: number;
  /** The questions the agent asks the user about concepts it could not find, and what the user did with them. */
  clarifications: DefinitionDraft[];
  clarificationState: ClarificationState | null;
  /** Set on the answer given again after a confirmation: the question it answers again. */
  retryOf: number | null;
  usedDefinitions: UsedDefinition[];
};

function ToolCallBlock({ toolCall }: { toolCall: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const label = TOOL_LABELS[toolCall.name];
  const toggle = () => setExpanded(value => !value);
  return (
    <div className={`ai-tool-call is-${toolCall.status}`}>
      <button type="button" className="ai-tool-call-header" aria-expanded={expanded} onClick={toggle}>
        <ChevronRight className="ai-tool-call-chevron" aria-hidden="true" />
        <span className="ai-tool-call-status" aria-hidden="true">
          {toolCall.status === 'running' && <LoaderCircle className="ai-spin" />}
          {toolCall.status === 'ok' && <Check />}
          {toolCall.status === 'error' && <X />}
        </span>
        <code className="ai-tool-call-name">{toolCall.name}</code>
        {label && <span className="ai-tool-call-label">{label}</span>}
        {toolCall.durationMs !== undefined && (
          <span className="ai-tool-call-duration">{(toolCall.durationMs / 1000).toFixed(1)}s</span>
        )}
      </button>
      {expanded && (
        <div className="ai-tool-call-body">
          <p className="ai-tool-call-caption">Đầu vào</p>
          <pre>{JSON.stringify(toolCall.arguments, null, 2)}</pre>
          {toolCall.status === 'ok' && <p className="ai-tool-call-caption">Kết quả</p>}
          {toolCall.status === 'ok' && <pre>{JSON.stringify(toolCall.result, null, 2)}</pre>}
          {toolCall.error && <p className="ai-tool-call-caption">Lỗi</p>}
          {toolCall.error && <pre className="is-error">{toolCall.error}</pre>}
        </div>
      )}
    </div>
  );
}

/**
 * The agent's steps. While they run only the current step shows, each new one sliding in over the last; once the
 * answer starts they fold into one line that opens the full list of tool calls.
 */
function ToolActivity({ toolCalls, running }: { toolCalls: ToolCall[]; running: boolean }) {
  const [expanded, setExpanded] = useState(false);
  if (toolCalls.length === 0) return null;
  if (running) {
    const current = toolCalls[toolCalls.length - 1];
    return (
      <div className="ai-tool-ticker" aria-live="polite">
        <div key={current.id} className={`ai-tool-ticker-line is-${current.status}`}>
          <span className="ai-tool-call-status" aria-hidden="true">
            {current.status === 'running' && <LoaderCircle className="ai-spin" />}
            {current.status === 'ok' && <Check />}
            {current.status === 'error' && <X />}
          </span>
          <span className="ai-tool-ticker-label">
            {TOOL_LABELS[current.name] ?? current.name}{current.status === 'running' ? '…' : ''}
          </span>
          <span className="ai-tool-ticker-step">Bước {toolCalls.length}</span>
        </div>
      </div>
    );
  }
  const failed = toolCalls.some(toolCall => toolCall.status === 'error');
  const totalMs = toolCalls.reduce((sum, toolCall) => sum + (toolCall.durationMs ?? 0), 0);
  return (
    <div className={`ai-tool-summary${failed ? ' is-error' : ''}`}>
      <button type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
        <span className="ai-tool-call-status" aria-hidden="true">{failed ? <X /> : <Check />}</span>
        Đã dùng {toolCalls.length} công cụ · {(totalMs / 1000).toFixed(1)}s
        <ChevronRight className="ai-tool-call-chevron" aria-hidden="true" />
      </button>
      {expanded && (
        <div className="ai-tool-summary-list">
          {toolCalls.map(toolCall => <ToolCallBlock key={toolCall.id} toolCall={toolCall} />)}
        </div>
      )}
    </div>
  );
}

function OutcomeBadge({ turn, outcome }: { turn: Turn; outcome: NonNullable<Turn['outcome']> }) {
  if (outcome.status === 'resolved') {
    return (
      <p className="ai-outcome is-resolved">
        {turn.usedDefinitions.length > 0
          ? `Đã xác định đủ, theo cách hiểu bạn đã xác nhận: ${turn.usedDefinitions.map(item => item.name).join(', ')}.`
          : 'Đã xác định đủ nội dung nghiệp vụ cho câu hỏi.'}
      </p>
    );
  }
  if (outcome.status === 'failed') return <p className="ai-outcome is-failed">Câu hỏi đã được ghi nhận là lỗi.</p>;
  // A missing term or rule the user is asked about is shown by the confirmation card instead.
  const askedKinds = new Set(turn.clarifications.map(item => item.kind));
  const metricMissing = outcome.missing.includes('metric');
  const unasked = outcome.missing.filter(kind => kind !== 'metric' && !askedKinds.has(kind));
  if (!metricMissing && unasked.length === 0) return null;
  return (
    <p className="ai-outcome is-review">
      {metricMissing ? 'Chưa có metric phù hợp; quản trị viên sẽ xem xét bổ sung. ' : ''}
      {unasked.length > 0 ? `Chưa xác định được ${unasked.map(kind => MISSING_LABELS[kind]).join(', ')}.` : ''}
    </p>
  );
}

type Answer = { choice: number | 'other' | null; ownWords: string };

function answeredDefinition(draft: DefinitionDraft, answer: Answer): string {
  if (answer.choice === 'other') return answer.ownWords.trim();
  return answer.choice === null ? '' : draft.options[answer.choice]?.definition ?? '';
}

/**
 * The agent asks the user what the concepts it could not find mean, one question at a time: the user picks one of the
 * suggested ways to understand each concept or writes their own, then sends every answer at once. The answers are kept
 * for all the user's conversations about the dashboard, and the question is answered again with them.
 */
function ClarificationCard({ turn, onConfirm, onDismiss }: {
  turn: Turn;
  onConfirm: (definitions: ConfirmedDefinition[]) => Promise<void>;
  onDismiss: () => Promise<void>;
}) {
  const drafts = turn.clarifications;
  const [answers, setAnswers] = useState<Answer[]>(() => drafts.map(() => ({ choice: null, ownWords: '' })));
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const ownWordsRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    setAnswers(drafts.map(() => ({ choice: null, ownWords: '' })));
    setStep(0);
  }, [drafts]);

  if (turn.clarificationState === 'confirmed' || turn.clarificationState === 'dismissed') {
    return (
      <p className="ai-clarification-settled">
        <Check aria-hidden="true" />
        {turn.clarificationState === 'confirmed'
          ? `Đã lưu cách hiểu của bạn: ${drafts.map(item => item.name).join(', ')}.`
          : 'Đã bỏ qua các câu hỏi xác nhận.'}
      </p>
    );
  }
  const draft = drafts[step];
  const answer = answers[step] ?? { choice: null, ownWords: '' };
  const lastStep = step === drafts.length - 1;
  const answered = (index: number) => answeredDefinition(drafts[index], answers[index]) !== '';
  const choose = (choice: Answer['choice']) => {
    setAnswers(current => current.map((item, index) => index === step ? { ...item, choice } : item));
    if (choice === 'other') window.setTimeout(() => ownWordsRef.current?.focus(), 0);
  };
  const writeOwnWords = (ownWords: string) => setAnswers(current => (
    current.map((item, index) => index === step ? { ...item, choice: 'other', ownWords } : item)
  ));
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };
  const submit = () => run(() => onConfirm(drafts.map((item, index) => ({
    kind: item.kind, concept: item.concept, name: item.name, definition: answeredDefinition(item, answers[index]),
  }))));
  const allAnswered = drafts.every((_, index) => answered(index));
  const next = () => {
    if (busy || !answered(step)) return;
    if (!lastStep) setStep(step + 1);
    else if (allAnswered) void submit();
  };
  const onKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (busy || event.target instanceof HTMLTextAreaElement || event.ctrlKey || event.metaKey || event.altKey) return;
    const number = Number(event.key);
    if (Number.isInteger(number) && number >= 1 && number <= draft.options.length + 1) {
      event.preventDefault();
      choose(number <= draft.options.length ? number - 1 : 'other');
    } else if (event.key === 'Enter') {
      event.preventDefault();
      next();
    }
  };
  return (
    <section className="ai-ask" aria-label="AI Agent hỏi lại bạn" onKeyDown={onKeyDown}>
      <header className="ai-ask-header">
        <MessageCircleQuestion aria-hidden="true" />
        <span>Cần bạn xác nhận</span>
        {drafts.length > 1 && (
          <nav className="ai-ask-steps" aria-label="Các câu hỏi">
            {drafts.map((item, index) => (
              <button
                key={`${item.kind}-${item.name}`}
                type="button"
                className={`ai-ask-step${index === step ? ' is-current' : ''}${answered(index) ? ' is-answered' : ''}`}
                aria-current={index === step ? 'step' : undefined}
                disabled={busy}
                onClick={() => setStep(index)}
              >
                {answered(index) && <Check aria-hidden="true" />}
                {item.name}
              </button>
            ))}
          </nav>
        )}
      </header>
      <p className="ai-ask-question">{draft.question}</p>
      <p className="ai-ask-kind">{DEFINITION_KIND_LABELS[draft.kind]}{draft.concept ? ` · “${draft.concept}”` : ''}</p>
      <div className="ai-ask-options" role="radiogroup" aria-label={draft.question}>
        {draft.options.map((option, index) => (
          <button
            key={option.label}
            type="button"
            role="radio"
            aria-checked={answer.choice === index}
            className={`ai-ask-option${answer.choice === index ? ' is-selected' : ''}`}
            disabled={busy}
            onClick={() => choose(index)}
          >
            <kbd>{index + 1}</kbd>
            <span className="ai-ask-option-text">
              <strong>{option.label}{index === 0 && <em> (Gợi ý)</em>}</strong>
              <span>{option.definition}</span>
            </span>
          </button>
        ))}
        <button
          type="button"
          role="radio"
          aria-checked={answer.choice === 'other'}
          className={`ai-ask-option${answer.choice === 'other' ? ' is-selected' : ''}`}
          disabled={busy}
          onClick={() => choose('other')}
        >
          <kbd>{draft.options.length + 1}</kbd>
          <span className="ai-ask-option-text"><strong>Khác</strong><span>Tự viết cách hiểu của bạn</span></span>
        </button>
        {answer.choice === 'other' && (
          <textarea
            ref={ownWordsRef}
            className="ai-ask-own-words"
            value={answer.ownWords}
            rows={2}
            maxLength={2000}
            placeholder={`Bạn hiểu “${draft.concept || draft.name}” là gì?`}
            aria-label="Cách hiểu của bạn"
            disabled={busy}
            onChange={event => writeOwnWords(event.target.value)}
          />
        )}
      </div>
      <footer className="ai-ask-actions">
        <button type="button" className="ai-button is-quiet" disabled={busy} onClick={() => void run(onDismiss)}>
          Bỏ qua
        </button>
        <span className="ai-ask-hint">Phím 1–{draft.options.length + 1} để chọn, Enter để tiếp</span>
        {step > 0 && (
          <button type="button" className="ai-button" disabled={busy} onClick={() => setStep(step - 1)}>
            Quay lại
          </button>
        )}
        <button
          type="button"
          className="ai-button is-primary"
          disabled={busy || !answered(step) || (lastStep && !allAnswered)}
          onClick={next}
        >
          {busy && <LoaderCircle className="ai-spin" aria-hidden="true" />}
          {lastStep ? 'Gửi câu trả lời' : `Tiếp (${step + 1}/${drafts.length})`}
        </button>
      </footer>
    </section>
  );
}

const markdownComponents = {
  table: ({ children }: { children?: React.ReactNode }) => (
    <div className="ai-chat-table-wrap"><table>{children}</table></div>
  ),
};

export type ClarificationHandlers = {
  onConfirm: (turn: Turn, definitions: ConfirmedDefinition[]) => Promise<void>;
  onDismiss: (turn: Turn) => Promise<void>;
};

export function TurnView(
  { turn, clarificationHandlers }: { turn: Turn; clarificationHandlers?: ClarificationHandlers },
) {
  return (
    <div className="ai-turn">
      {turn.retryOf === null ? (
        <div className="ai-user-message">{turn.question}</div>
      ) : (
        <p className="ai-retry-label">
          <CornerDownRight aria-hidden="true" /> Trả lời lại theo cách hiểu bạn vừa xác nhận
        </p>
      )}
      <div className="ai-assistant-message">
        <ToolActivity toolCalls={turn.toolCalls} running={turn.state === 'streaming' && !turn.answer} />
        {turn.answer && (
          <div className="ai-chat-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{turn.answer}</ReactMarkdown>
          </div>
        )}
        {turn.state === 'streaming' && !turn.answer && turn.toolCalls.length === 0 && (
          <p className="ai-thinking"><LoaderCircle className="ai-spin" aria-hidden="true" /> Đang xử lý…</p>
        )}
        {turn.state === 'streaming' && turn.answer && <span className="ai-caret" aria-hidden="true" />}
        {turn.error && <p className="ai-outcome is-failed">{turn.error}</p>}
        {turn.state === 'stopped' && <p className="ai-outcome">Đã dừng.</p>}
        {turn.outcome && <OutcomeBadge turn={turn} outcome={turn.outcome} />}
        {turn.clarifications.length > 0 && clarificationHandlers && turn.state !== 'streaming' ? (
          <ClarificationCard
            turn={turn}
            onConfirm={definitions => clarificationHandlers.onConfirm(turn, definitions)}
            onDismiss={() => clarificationHandlers.onDismiss(turn)}
          />
        ) : null}
      </div>
    </div>
  );
}

/** A turn saved on the server, shown again as it looked when it finished. */
export function turnFromStored(stored: StoredTurn): Turn {
  return {
    id: stored.id,
    question: stored.question,
    toolCalls: stored.tool_calls.map(({ duration_ms: durationMs, ...toolCall }) => ({ ...toolCall, durationMs })),
    answer: stored.answer,
    state: stored.error ? 'error' : 'done',
    error: stored.error ?? undefined,
    outcome: { status: stored.status, missing: stored.missing },
    questionId: stored.id,
    clarifications: stored.clarifications,
    clarificationState: stored.clarification_state,
    retryOf: stored.retry_of,
    usedDefinitions: [],
  };
}

/** A question just sent; `retryOf` when it answers an earlier question again. */
export function newTurn(question: string, retryOf: number | null = null): Turn {
  return {
    id: Date.now(), question, toolCalls: [], answer: '', state: 'streaming', clarifications: [],
    clarificationState: null, retryOf, usedDefinitions: [],
  };
}

/** Fold one streamed event into the turn it belongs to. */
export function applyStreamEvent(turn: Turn, event: ChatStreamEvent): Turn {
  switch (event.name) {
    case 'tool_start':
      return { ...turn, toolCalls: [...turn.toolCalls, { ...event.data, status: 'running' }] };
    case 'tool_end': {
      const { id, status, result, error, duration_ms: durationMs } = event.data;
      const toolCalls = turn.toolCalls.map(toolCall => toolCall.id === id
        ? { ...toolCall, status, result, error, durationMs }
        : toolCall);
      return { ...turn, toolCalls };
    }
    case 'token':
      return { ...turn, answer: turn.answer + event.data.text };
    case 'error':
      return { ...turn, error: event.data.message };
    case 'done': {
      const { question_id: questionId, status, missing, clarifications, user_definitions: used } = event.data;
      return {
        ...turn,
        state: turn.error ? 'error' : 'done',
        outcome: { status, missing },
        questionId: questionId ?? undefined,
        clarifications,
        clarificationState: clarifications.length > 0 ? 'pending' : null,
        usedDefinitions: used,
      };
    }
    default:
      return turn;
  }
}

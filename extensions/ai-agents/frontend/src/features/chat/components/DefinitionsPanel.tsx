import React, { useState } from 'react';
import { BookMarked, Check, LoaderCircle, Pencil, Trash2, X } from 'lucide-react';
import { UserDefinition } from '../../../shared/api/chat';
import { DEFINITION_KIND_LABELS } from './ChatTurn';
import { OPERATOR_LABELS, shownCell } from './QueryResultView';

/** What the agent applies for a qualitative concept: its stored conditions, or that it reads the words each time. */
function DefinitionConditions({ definition }: { definition: UserDefinition }) {
  if (definition.kind !== 'expert_rule') return null;
  if (!definition.conditions) {
    return <span className="ai-definition-note">Chưa chuyển được thành điều kiện; AI Agent hiểu theo lời mô tả.</span>;
  }
  return (
    <ul className="ai-definition-conditions" aria-label="Điều kiện áp dụng">
      {definition.conditions.filters.map(condition => {
        const operator = OPERATOR_LABELS[condition.operator as keyof typeof OPERATOR_LABELS] ?? condition.operator;
        const value = Array.isArray(condition.value)
          ? condition.value.map(item => shownCell(item)).join(', ')
          : shownCell(condition.value);
        return <li key={`${condition.column}${condition.operator}`}>{condition.label} {operator} {value}</li>;
      })}
    </ul>
  );
}

function DefinitionItem({ definition, onSave, onDelete }: {
  definition: UserDefinition;
  onSave: (change: { name: string; definition: string }) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(definition.name);
  const [text, setText] = useState(definition.definition);
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };
  const startEditing = () => {
    setName(definition.name);
    setText(definition.definition);
    setEditing(true);
  };

  return (
    <li className="ai-definition">
      <div className="ai-definition-heading">
        <span className="ai-clarification-kind">{DEFINITION_KIND_LABELS[definition.kind]}</span>
        {editing ? null : (
          <span className="ai-definition-actions">
            <button type="button" title="Sửa" aria-label={`Sửa ${definition.name}`} onClick={startEditing}>
              <Pencil aria-hidden="true" />
            </button>
            <button
              type="button"
              title="Xoá"
              aria-label={`Xoá ${definition.name}`}
              disabled={busy}
              onClick={() => {
                if (window.confirm(`Xoá cách hiểu “${definition.name}”? AI Agent sẽ hỏi lại khi gặp khái niệm này.`)) {
                  void run(onDelete);
                }
              }}
            >
              <Trash2 aria-hidden="true" />
            </button>
          </span>
        )}
      </div>
      {editing ? (
        <div className="ai-clarification-item">
          <input value={name} maxLength={200} aria-label="Tên" onChange={event => setName(event.target.value)} />
          <textarea
            value={text}
            rows={3}
            maxLength={2000}
            aria-label="Định nghĩa"
            onChange={event => setText(event.target.value)}
          />
          <div className="ai-clarification-actions">
            <button type="button" className="ai-button" disabled={busy} onClick={() => setEditing(false)}>
              <X aria-hidden="true" /> Huỷ
            </button>
            <button
              type="button"
              className="ai-button is-primary"
              disabled={busy || !name.trim() || !text.trim()}
              onClick={() => void run(async () => {
                await onSave({ name: name.trim(), definition: text.trim() });
                setEditing(false);
              })}
            >
              {busy ? <LoaderCircle className="ai-spin" aria-hidden="true" /> : <Check aria-hidden="true" />} Lưu
            </button>
          </div>
        </div>
      ) : (
        <>
          <strong>{definition.name}</strong>
          <p>{definition.definition}</p>
          <DefinitionConditions definition={definition} />
          {definition.review_status === 'promoted' ? (
            <span className="ai-definition-note">Đã có định nghĩa chung của nghiệp vụ cho khái niệm này.</span>
          ) : null}
        </>
      )}
    </li>
  );
}

/** The definitions the user confirmed in this conversation, which the agent uses for every later question in it. */
export function DefinitionsPanel({ definitions, onSave, onDelete, onClose }: {
  definitions: UserDefinition[];
  onSave: (definition: UserDefinition, change: { name: string; definition: string }) => Promise<void>;
  onDelete: (definition: UserDefinition) => Promise<void>;
  onClose: () => void;
}) {
  return (
    <aside className="ai-definitions-panel" aria-label="Cách hiểu của bạn">
      <header>
        <div>
          <h2>Cách hiểu của bạn</h2>
          <p>
            AI Agent dùng các cách hiểu này cho mọi cuộc trò chuyện của bạn trên dashboard này, trừ khi nghiệp vụ đã có
            định nghĩa chung.
          </p>
        </div>
        <button type="button" className="ai-chat-icon-button" aria-label="Đóng" onClick={onClose}>
          <X aria-hidden="true" />
        </button>
      </header>
      {definitions.length === 0 ? (
        <div className="ai-definitions-empty">
          <BookMarked aria-hidden="true" />
          <p>Chưa có định nghĩa nào. Khi AI Agent chưa rõ một khái niệm, nó sẽ hỏi bạn ngay trong cuộc trò chuyện.</p>
        </div>
      ) : (
        <ul>
          {definitions.map(definition => (
            <DefinitionItem
              key={definition.id}
              definition={definition}
              onSave={change => onSave(definition, change)}
              onDelete={() => onDelete(definition)}
            />
          ))}
        </ul>
      )}
    </aside>
  );
}

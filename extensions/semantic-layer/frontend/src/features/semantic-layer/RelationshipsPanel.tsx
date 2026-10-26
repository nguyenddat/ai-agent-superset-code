import React, { useEffect, useState } from 'react';
import { AlertCircle, ArrowRight, Check, LoaderCircle, Search, ShieldCheck, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { requestJson, semanticLayerApi } from './api';
import type {
  RelationshipContractView, RelationshipRow, RelationshipSource, RelationshipSuggestion, RelationshipsResponse,
} from './types';

type RelationshipsPanelProps = {
  datasetId: number;
  /** Unsaved dictionary edits; applying a suggestion writes the dictionary, so it waits until they are saved. */
  dictionaryDirty: boolean;
  disabled: boolean;
  onDictionaryChanged: () => void;
};

type RowAction = 'contract/candidate' | 'verify' | 'contract/approve' | 'contract/revoke';

const SOURCE_LABELS: Record<RelationshipSource, string> = { database: 'Database', dictionary: 'Từ điển', naming: 'Tên cột' };
const CARDINALITY_LABELS = { many_to_one: 'n : 1', one_to_one: '1 : 1' } as const;
const countFormat = new Intl.NumberFormat('vi-VN');
const percentFormat = new Intl.NumberFormat('vi-VN', { style: 'percent', maximumFractionDigits: 2 });

function contractState(contract: RelationshipContractView | null): { key: string; label: string } {
  if (!contract) return { key: 'not_started', label: 'Chưa đề nghị' };
  if (contract.status === 'approved') return contract.current ? { key: 'approved', label: 'Đã duyệt' } : { key: 'outdated', label: 'Hết hiệu lực' };
  if (contract.status === 'revoked') return { key: 'revoked', label: 'Đã thu hồi' };
  return { key: 'candidate', label: 'Chờ duyệt' };
}

function VerificationCell({ contract }: { contract: RelationshipContractView | null }) {
  const verification = contract?.verification;
  if (!verification) return <span className="is-muted">Chưa kiểm tra</span>;
  return (
    <div className="sl-relationship-check">
      <span className={verification.target_unique ? 'is-ok' : 'is-bad'} title="Cột đích giữ mỗi giá trị một lần">
        {verification.target_unique ? <Check /> : <X />}{verification.target_unique ? 'Duy nhất' : 'Đích lặp'}
      </span>
      <span className={verification.type_match ? 'is-ok' : 'is-bad'} title="Kiểu dữ liệu hai đầu so sánh được">
        {verification.type_match ? <Check /> : <X />}{verification.type_match ? 'Kiểu khớp' : 'Kiểu lệch'}
      </span>
      {verification.target_unique ? (
        <span
          className={verification.orphans ? 'is-warning' : 'is-ok'}
          title={`${countFormat.format(verification.references)} tham chiếu, ${percentFormat.format(verification.orphan_ratio)} không có ở bảng đích${verification.orphan_samples.length ? `. Ví dụ: ${verification.orphan_samples.join(', ')}` : ''}`}
        >
          Mồ côi {countFormat.format(verification.orphans)}/{countFormat.format(verification.references)}
        </span>
      ) : null}
    </div>
  );
}

export function RelationshipsPanel({ datasetId, dictionaryDirty, disabled, onDictionaryChanged }: RelationshipsPanelProps) {
  const [data, setData] = useState<RelationshipsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);

  const load = async (suggest = false) => {
    setError('');
    try {
      const response = await requestJson<RelationshipsResponse>(semanticLayerApi.relationships(datasetId, suggest), 'GET');
      // A plain reload keeps the suggestions already found, minus the ones now declared.
      setData(current => (suggest || !current?.suggestions ? response : {
        ...response,
        suggestions: current.suggestions.filter(item => !response.outgoing.some(row => (
          row.from_column === item.from_column && row.to_dataset_id === item.to_dataset_id && row.to_column === item.to_column
        ))),
        suggestion_note: current.suggestion_note,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được quan hệ.');
    }
  };

  useEffect(() => {
    setData(null);
    setLoading(true);
    void load().finally(() => setLoading(false));
  }, [datasetId]);

  const findSuggestions = async () => {
    setSuggesting(true);
    await load(true);
    setSuggesting(false);
  };

  const runAction = async (row: RelationshipRow, action: RowAction) => {
    setBusy(`${row.column_id}:${action}`);
    setError('');
    try {
      await requestJson(semanticLayerApi.relationshipAction(datasetId, row.column_id, action), 'POST', action === 'contract/candidate' ? { source: row.contract?.source ?? 'dictionary' } : {});
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Thao tác không thành công.');
    } finally {
      setBusy(null);
    }
  };

  const applySuggestion = async (suggestion: RelationshipSuggestion) => {
    const key = `${suggestion.from_column}>${suggestion.to_dataset_id}.${suggestion.to_column}`;
    setBusy(key);
    setError('');
    try {
      await requestJson(semanticLayerApi.relationshipApply(datasetId), 'POST', {
        from_column: suggestion.from_column,
        to_dataset_id: suggestion.to_dataset_id,
        to_column: suggestion.to_column,
        source: suggestion.sources[0],
      });
      await load();
      onDictionaryChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không dùng được gợi ý.');
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <div className="sl-dictionary-state"><LoaderCircle className="sl-spin" /><span>Đang tải quan hệ…</span></div>;

  const actionButton = (row: RelationshipRow, action: RowAction, label: string, extra: { disabled?: boolean; title?: string; variant?: 'outline' | 'default' } = {}) => {
    const running = busy === `${row.column_id}:${action}`;
    return (
      <Button size="sm" variant={extra.variant ?? 'outline'} disabled={disabled || busy !== null || extra.disabled} title={extra.title} onClick={() => void runAction(row, action)}>
        {running ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : null}{label}
      </Button>
    );
  };

  const rowActions = (row: RelationshipRow) => {
    if (row.problem) return null;
    const contract = row.contract;
    const state = contractState(contract).key;
    if (state === 'approved') return actionButton(row, 'contract/revoke', 'Thu hồi');
    if (state === 'candidate') {
      const passed = contract?.verification?.passed === true;
      return (
        <>
          {actionButton(row, 'verify', contract?.verification ? 'Kiểm tra lại' : 'Kiểm tra')}
          {actionButton(row, 'contract/approve', 'Duyệt', {
            variant: 'default', disabled: !passed,
            title: passed ? undefined : 'Cần kiểm tra dữ liệu đạt: cột đích duy nhất và kiểu khớp',
          })}
        </>
      );
    }
    return actionButton(row, 'contract/candidate', state === 'outdated' ? 'Tạo lại đề nghị' : 'Tạo đề nghị');
  };

  const outgoing = data?.outgoing ?? [];
  const incoming = data?.incoming ?? [];
  const suggestions = data?.suggestions;

  return (
    <div className="sl-relationships">
      <div className="sl-time-semantics-header">
        <p>Quan hệ giữa các base table. Chỉ quan hệ <strong>đã duyệt</strong> mới được AI Agent dùng để nối bảng khi tự sinh truy vấn.</p>
        <Button variant="outline" disabled={disabled || suggesting || !data?.is_base} onClick={() => void findSuggestions()} title="Đọc khoá ngoại của database và so tên cột với khoá của các base table khác">
          {suggesting ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <Search data-icon="inline-start" />}
          {suggesting ? 'Đang tìm…' : 'Tìm quan hệ'}
        </Button>
      </div>
      {data && !data.is_base ? (
        <p className="sl-time-semantics-note is-warning">Schema link chỉ dùng base table. Dataset này chưa được phân loại là Base dataset (tab Thông tin chung), nên không tìm quan hệ cho nó.</p>
      ) : null}
      {error ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {error}</div> : null}

      {suggestions && data?.suggestion_note ? <p className="sl-time-semantics-note is-warning">{data.suggestion_note}</p> : null}
      {suggestions?.length && dictionaryDirty ? (
        <p className="sl-time-semantics-note is-warning">Có thay đổi chưa lưu trong data dictionary. Lưu trước khi dùng gợi ý.</p>
      ) : null}

      {/* One table for every group, so the columns line up from one group to the next. */}
      <table className="sl-time-semantics-table sl-relationships-table">
        <thead>
          <tr>
            <th scope="col" className="is-link">Quan hệ</th>
            <th scope="col" className="is-cardinality">Bản số</th>
            <th scope="col" className="is-source">Nguồn</th>
            <th scope="col" className="is-check">Kiểm chứng dữ liệu</th>
            <th scope="col" className="is-state">Trạng thái</th>
            <th scope="col" className="is-actions"><span className="sl-visually-hidden">Thao tác</span></th>
          </tr>
        </thead>
        <tbody>
          <tr className="sl-relationships-group"><th colSpan={6} scope="rowgroup">Đi ra · {outgoing.length}</th></tr>
          {outgoing.map(row => {
            const state = contractState(row.contract);
            return (
              <tr key={`out-${row.column_id}`}>
                <td>
                  <div className="sl-relationship-link">
                    <code>{row.from_column}</code><ArrowRight /><code>{row.to_dataset_name}.{row.to_column}</code>
                  </div>
                  {row.problem ? <span className="sl-relationship-problem">{row.problem}</span> : null}
                </td>
                <td>{row.cardinality ? CARDINALITY_LABELS[row.cardinality] : '—'}</td>
                <td>{row.contract?.source ? SOURCE_LABELS[row.contract.source] : '—'}</td>
                <td><VerificationCell contract={row.contract} /></td>
                <td>
                  <span className={`sl-metric-state is-${state.key}`}>{state.key === 'approved' ? <ShieldCheck className="sl-inline-icon" /> : null}{state.label}</span>
                </td>
                <td><div className="sl-relationship-actions">{rowActions(row)}</div></td>
              </tr>
            );
          })}
          {outgoing.length === 0 ? (
            <tr><td colSpan={6} className="sl-relationships-empty">Chưa khai báo quan hệ nào đi ra từ bảng này. Bấm “Tìm quan hệ” để nhận gợi ý.</td></tr>
          ) : null}

          {suggestions ? (
            <tr className="sl-relationships-group"><th colSpan={6} scope="rowgroup">Gợi ý chưa khai báo · {suggestions.length}</th></tr>
          ) : null}
          {suggestions?.map(item => {
            const key = `${item.from_column}>${item.to_dataset_id}.${item.to_column}`;
            return (
              <tr key={`suggest-${key}`}>
                <td>
                  <div className="sl-relationship-link"><code>{item.from_column}</code><ArrowRight /><code>{item.to_dataset_name}.{item.to_column}</code></div>
                  {item.replaces ? <span className="sl-relationship-problem">Cột này đang khai báo trỏ tới bảng khác; dùng gợi ý sẽ thay quan hệ đó.</span> : null}
                </td>
                <td>—</td>
                <td>{item.sources.map(source => <span key={source} className="sl-relationship-source">{SOURCE_LABELS[source]}</span>)}</td>
                <td><span className="is-muted">Kiểm tra sau khi dùng gợi ý</span></td>
                <td><span className="sl-metric-state is-not_started">Gợi ý</span></td>
                <td>
                  <div className="sl-relationship-actions">
                    <Button size="sm" variant="outline" disabled={disabled || dictionaryDirty || busy !== null} onClick={() => void applySuggestion(item)}>
                      {busy === key ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : null}Dùng gợi ý
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
          {suggestions && suggestions.length === 0 ? (
            <tr><td colSpan={6} className="sl-relationships-empty">Không có gợi ý mới: các quan hệ tìm được đều đã khai báo.</td></tr>
          ) : null}

          <tr className="sl-relationships-group"><th colSpan={6} scope="rowgroup">Đi vào · {incoming.length}</th></tr>
          {incoming.map(row => {
            const state = contractState(row.contract);
            return (
              <tr key={`in-${row.column_id}`}>
                <td>
                  <div className="sl-relationship-link"><code>{row.from_dataset_name}.{row.from_column}</code><ArrowRight /><code>{row.to_column}</code></div>
                </td>
                <td>{row.cardinality ? CARDINALITY_LABELS[row.cardinality] : '—'}</td>
                <td>{row.contract?.source ? SOURCE_LABELS[row.contract.source] : '—'}</td>
                <td><VerificationCell contract={row.contract} /></td>
                <td><span className={`sl-metric-state is-${state.key}`}>{state.key === 'approved' ? <ShieldCheck className="sl-inline-icon" /> : null}{state.label}</span></td>
                <td><span className="sl-relationships-hint">Quản lý ở bảng {row.from_dataset_name}</span></td>
              </tr>
            );
          })}
          {incoming.length === 0 ? (
            <tr><td colSpan={6} className="sl-relationships-empty">Chưa có bảng nào khai báo trỏ tới bảng này.</td></tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

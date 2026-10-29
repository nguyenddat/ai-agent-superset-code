import React, { useEffect, useState } from 'react';
import { FlaskConical, LoaderCircle, Route } from 'lucide-react';
import { AnalysisTrace as Trace, GraphView, analyzeGoal, getSchemaGraph } from '../../shared/api/schemaLink';
import { AnalysisTrace } from './AnalysisTrace';
import { SchemaGraphView } from './SchemaGraphView';

/**
 * Goals written by hand for the sample warehouse, until linking from a question exists. Tables are named by dataset
 * ID, as the schema graph lists them: 13 values, 15 observations, 10 cities, 14 data loads.
 */
const PRESETS: Array<{ label: string; goal: unknown }> = [
  {
    label: 'Nhiệt độ trung bình theo giờ ở Hà Nội ngày 25/10',
    goal: {
      measures: [{ indicator: 'nhiet_do_c' }],
      group_by: [{ dataset_id: 15, column: 'thoi_diem_quan_sat', time_grain: 'hour' }],
      filters: [
        { dataset_id: 10, column: 'ten_thanh_pho', operator: '==', value: 'Ha Noi' },
        { dataset_id: 15, column: 'thoi_diem_quan_sat', operator: '==', value: '2026-10-25' },
      ],
      row_kinds: [{ dataset_id: 15, value: 'DU_BAO_GIO' }],
    },
  },
  {
    label: 'Số lần nạp dữ liệu thất bại',
    goal: {
      measures: [{ dataset_id: 14, aggregation: 'COUNT' }],
      filters: [{ dataset_id: 14, column: 'trang_thai', operator: '==', value: 'THAT_BAI' }],
    },
  },
  {
    label: 'Số quan sát hiện tại theo thành phố',
    goal: {
      measures: [{ dataset_id: 15, aggregation: 'COUNT' }],
      group_by: [{ dataset_id: 10, column: 'ten_thanh_pho' }],
      row_kinds: [{ dataset_id: 15, value: 'HIEN_TAI' }],
    },
  },
  {
    label: 'Lượng mưa theo giờ (phải dừng: dữ liệu mưa theo ngày)',
    goal: {
      measures: [{ indicator: 'tong_luong_mua_mm' }],
      group_by: [{ dataset_id: 15, column: 'thoi_diem_quan_sat', time_grain: 'hour' }],
      row_kinds: [{ dataset_id: 15, value: 'DU_BAO_NGAY' }],
    },
  },
  {
    label: 'Nhiệt độ không chọn loại dòng (phải dừng: bảng trộn grain)',
    goal: {
      measures: [{ indicator: 'nhiet_do_c' }],
      filters: [{ dataset_id: 10, column: 'ten_thanh_pho', operator: '==', value: 'Ha Noi' }],
    },
  },
];

const pretty = (value: unknown) => JSON.stringify(value, null, 2);

export function SchemaLinkLab() {
  const [databaseId, setDatabaseId] = useState(1);
  const [goalText, setGoalText] = useState(pretty(PRESETS[0].goal));
  const [graph, setGraph] = useState<GraphView | null>(null);
  const [graphError, setGraphError] = useState('');
  const [trace, setTrace] = useState<Trace | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setGraph(null);
    setGraphError('');
    getSchemaGraph(databaseId)
      .then(view => { if (active) setGraph(view); })
      .catch(reason => {
        if (active) setGraphError(reason instanceof Error ? reason.message : 'Không đọc được đồ thị.');
      });
    return () => { active = false; };
  }, [databaseId]);

  const choosePreset = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const preset = PRESETS[Number(event.target.value)];
    if (!preset) return;
    setGoalText(pretty(preset.goal));
    setTrace(null);
  };

  const run = async () => {
    setError('');
    let goal: unknown;
    try {
      goal = JSON.parse(goalText);
    } catch {
      setError('Mục tiêu không phải JSON hợp lệ.');
      return;
    }
    setRunning(true);
    try {
      setTrace(await analyzeGoal(databaseId, goal));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không phân tích được.');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="ai-lab">
      <header className="ai-lab-header">
        <span className="ai-chat-mark" aria-hidden="true"><FlaskConical /></span>
        <div>
          <h1>Thử phân tích dữ liệu</h1>
          <p>
            Viết mục tiêu bằng tay để xem schema link tìm bảng, dựng đồ thị và chọn đường join trên base table. Câu hỏi
            tự nhiên sẽ được chuyển thành mục tiêu ở bước sau; SQL ở đây chỉ được dựng, chưa chạy.
          </p>
        </div>
      </header>
      <div className="ai-lab-input">
        <div className="ai-lab-controls">
          <label>
            Database ID
            <input
              type="number" min={1} value={databaseId}
              onChange={event => setDatabaseId(Number(event.target.value) || 1)}
            />
          </label>
          <label className="ai-lab-preset">
            Mẫu
            <select onChange={choosePreset}>
              {PRESETS.map((preset, index) => <option key={preset.label} value={index}>{preset.label}</option>)}
            </select>
          </label>
          <button type="button" className="ai-lab-run" disabled={running} onClick={() => void run()}>
            {running ? <LoaderCircle className="ai-spin" aria-hidden="true" /> : <Route aria-hidden="true" />}
            {running ? 'Đang phân tích…' : 'Phân tích'}
          </button>
        </div>
        <textarea
          aria-label="Mục tiêu (JSON)" spellCheck={false} value={goalText}
          onChange={event => setGoalText(event.target.value)}
        />
        {error ? <p className="ai-page-state is-error" role="alert">{error}</p> : null}
      </div>
      {trace && graph ? <AnalysisTrace trace={trace} fallbackGraph={graph} /> : null}
      {!trace && graph ? (
        <SchemaGraphView
          view={graph}
          caption={`Đồ thị schema · ${graph.tables.length} base table, ${graph.edges.length} quan hệ đã duyệt`}
        />
      ) : null}
      {graphError ? <p className="ai-page-state is-error" role="alert">{graphError}</p> : null}
      {!graph && !graphError ? (
        <p className="ai-page-state"><LoaderCircle className="ai-spin" aria-hidden="true" /> Đang đọc đồ thị…</p>
      ) : null}
    </div>
  );
}

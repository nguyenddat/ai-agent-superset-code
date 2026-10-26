import React, { useEffect, useState } from 'react';
import { AlertCircle, LoaderCircle, Plus, ScanSearch, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import type { ColumnDictionary, DatasetDictionary, DatasetGrain, Grain, GrainProfile, GrainProfileResponse } from './types';

export type TimeSemantics = Pick<DatasetDictionary, 'time_column' | 'row_kind_column' | 'grains'>;

type TimeSemanticsFieldsProps = {
  datasetId: number;
  columns: ColumnDictionary[];
  value: TimeSemantics;
  disabled: boolean;
  onChange: (value: TimeSemantics) => void;
};

export const GRAIN_LABELS: Record<Grain, string> = {
  instant: 'Thời điểm lẻ',
  hour: 'Giờ',
  day: 'Ngày',
  week: 'Tuần',
  month: 'Tháng',
  quarter: 'Quý',
  year: 'Năm',
};
const grainItems = (Object.keys(GRAIN_LABELS) as Grain[]).map(grain => ({ label: GRAIN_LABELS[grain], value: grain }));
const countFormat = new Intl.NumberFormat('vi-VN');

function shownMoment(value: string | null): string {
  const moment = value ? /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(value) : null;
  if (!moment) return value ?? '—';
  const day = `${moment[3]}/${moment[2]}/${moment[1]}`;
  return moment[4] === undefined || (moment[4] === '00' && moment[5] === '00') ? day : `${day} ${moment[4]}:${moment[5]}`;
}

function profileText(profile: GrainProfile): string {
  const span = `${shownMoment(profile.first_moment)} – ${shownMoment(profile.last_moment)}`;
  return `${countFormat.format(profile.row_count)} dòng · ${span}`;
}

/** Grains for the profiled kinds of rows: a kind already declared keeps its label and grain, a new one takes the
 * suggestion, and a declared kind the data no longer holds stays until the administrator removes it. */
function mergedGrains(current: DatasetGrain[], profiles: GrainProfile[]): DatasetGrain[] {
  const declared = new Map(current.map(item => [item.row_kind_value, item]));
  const profiled = profiles.map(profile => declared.get(profile.row_kind_value) ?? {
    row_kind_value: profile.row_kind_value,
    label: null,
    grain: profile.suggested_grain ?? 'day',
  });
  const profiledValues = new Set(profiles.map(profile => profile.row_kind_value));
  return [...profiled, ...current.filter(item => !profiledValues.has(item.row_kind_value))];
}

export function TimeSemanticsFields({ datasetId, columns, value, disabled, onChange }: TimeSemanticsFieldsProps) {
  const [profiles, setProfiles] = useState<GrainProfile[]>([]);
  const [tooManyKinds, setTooManyKinds] = useState(false);
  const [profiling, setProfiling] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [newRowKind, setNewRowKind] = useState('');

  // A profile describes one choice of columns; another choice needs its own.
  useEffect(() => {
    setProfiles([]);
    setTooManyKinds(false);
    setProfileError('');
  }, [datasetId, value.time_column, value.row_kind_column]);

  const temporalColumns = columns.filter(column => column.temporal_kind !== null);
  const timeColumnItems: Array<{ label: string; value: string | null }> = [
    { label: 'Chưa chọn', value: null },
    ...temporalColumns.map(column => ({ label: column.column_name, value: column.column_name })),
  ];
  const rowKindItems: Array<{ label: string; value: string | null }> = [
    { label: 'Không có (cả bảng một grain)', value: null },
    ...columns
      .filter(column => column.temporal_kind === null && column.column_name !== value.time_column)
      .map(column => ({ label: column.column_name, value: column.column_name })),
  ];
  const profileByValue = new Map(profiles.map(profile => [profile.row_kind_value, profile]));
  const byRowKind = value.row_kind_column !== null;

  const setTimeColumn = (timeColumn: string | null) => {
    // Kinds of rows and grains are read on the time column, so they go when it does.
    onChange(timeColumn === null
      ? { time_column: null, row_kind_column: null, grains: [] }
      : { ...value, time_column: timeColumn });
  };
  const setRowKindColumn = (rowKindColumn: string | null) => {
    // Grains name values of the row kind column, so another column starts a new list.
    onChange({ ...value, row_kind_column: rowKindColumn, grains: [] });
  };
  const setGrain = (index: number, changes: Partial<DatasetGrain>) => {
    onChange({ ...value, grains: value.grains.map((item, position) => (position === index ? { ...item, ...changes } : item)) });
  };
  const removeGrain = (index: number) => {
    onChange({ ...value, grains: value.grains.filter((_item, position) => position !== index) });
  };
  const addRowKind = () => {
    const rowKind = newRowKind.trim();
    if (!rowKind || value.grains.some(item => item.row_kind_value === rowKind)) return;
    onChange({ ...value, grains: [...value.grains, { row_kind_value: rowKind, label: null, grain: 'day' }] });
    setNewRowKind('');
  };

  const detectGrain = async () => {
    const temporalKind = columns.find(column => column.column_name === value.time_column)?.temporal_kind;
    if (!value.time_column || !temporalKind || profiling) return;
    setProfiling(true);
    setProfileError('');
    try {
      const response = await requestJson<GrainProfileResponse>(
        semanticLayerApi.grainProfile(datasetId, value.time_column, temporalKind, value.row_kind_column), 'GET',
      );
      setProfiles(response.profiles);
      setTooManyKinds(response.too_many_kinds);
      onChange({ ...value, grains: mergedGrains(value.grains, response.profiles) });
    } catch (reason) {
      setProfileError(reason instanceof Error ? reason.message : 'Không đọc được dữ liệu để gợi ý grain.');
    } finally {
      setProfiling(false);
    }
  };

  return (
    <div className="sl-time-semantics">
      <div className="sl-time-semantics-header">
        <p>Một dòng dữ liệu ứng với khoảng thời gian nào. AI Agent dựa vào đây để lọc trọn ngày và gom theo giờ, ngày, tháng.</p>
        <Button
          variant="outline"
          disabled={disabled || profiling || !value.time_column}
          onClick={() => void detectGrain()}
          title="Đọc dữ liệu (chỉ đọc) để gợi ý grain cho từng loại dòng; chỉ có hiệu lực khi bấm Lưu thay đổi"
        >
          {profiling ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <ScanSearch data-icon="inline-start" />}
          {profiling ? 'Đang đọc dữ liệu…' : 'Phát hiện grain'}
        </Button>
      </div>
      <div className="sl-time-semantics-columns">
        <Field>
          <FieldLabel>Cột thời gian chính</FieldLabel>
          <Select items={timeColumnItems} value={value.time_column} disabled={disabled} onValueChange={setTimeColumn}>
            <SelectTrigger aria-label="Cột thời gian chính" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              <SelectGroup>
                {timeColumnItems.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel title="Cột mà giá trị của nó tách các dòng có grain khác nhau, ví dụ loai_quan_sat">Cột phân loại dòng</FieldLabel>
          <Select items={rowKindItems} value={value.row_kind_column} disabled={disabled || !value.time_column} onValueChange={setRowKindColumn}>
            <SelectTrigger aria-label="Cột phân loại dòng" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              <SelectGroup>
                {rowKindItems.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
      </div>
      {temporalColumns.length === 0 ? (
        <p className="sl-time-semantics-note">Dataset chưa có cột nào được đánh dấu là cột thời gian. Chọn kiểu thời gian ở chi tiết của cột trong bảng bên dưới.</p>
      ) : null}
      {profileError ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {profileError}</div> : null}
      {tooManyKinds ? (
        <p className="sl-time-semantics-note is-warning">Cột phân loại có hơn 20 giá trị nên không giống một cột phân loại dòng; chỉ 20 giá trị đầu được hiện.</p>
      ) : null}
      {value.time_column ? (
        <table className="sl-time-semantics-table">
          <thead>
            <tr>
              {byRowKind ? <th scope="col" className="is-kind">Loại dòng</th> : null}
              {byRowKind ? <th scope="col" className="is-label">Nhãn nghiệp vụ</th> : null}
              <th scope="col" className="is-grain">Grain</th>
              <th scope="col">Dữ liệu</th>
              <th scope="col" className="is-action"><span className="sl-visually-hidden">Xoá</span></th>
            </tr>
          </thead>
          <tbody>
            {value.grains.map((item, index) => {
              const profile = profileByValue.get(item.row_kind_value);
              const disagrees = profile?.suggested_grain && profile.suggested_grain !== item.grain;
              return (
                <tr key={item.row_kind_value ?? 'all'}>
                  {byRowKind ? <th scope="row"><code>{item.row_kind_value}</code></th> : null}
                  {byRowKind ? (
                    <td>
                      <Input
                        aria-label={`Nhãn của ${item.row_kind_value}`}
                        disabled={disabled}
                        placeholder={item.row_kind_value ?? ''}
                        value={item.label ?? ''}
                        onChange={event => setGrain(index, { label: event.target.value || null })}
                      />
                    </td>
                  ) : null}
                  <td>
                    <Select items={grainItems} value={item.grain} disabled={disabled} onValueChange={grain => grain && setGrain(index, { grain })}>
                      <SelectTrigger aria-label={`Grain của ${item.row_kind_value ?? 'dataset'}`} className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent alignItemWithTrigger={false}>
                        <SelectGroup>
                          {grainItems.map(grain => <SelectItem key={grain.value} value={grain.value}>{grain.label}</SelectItem>)}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </td>
                  <td>
                    <div className="sl-time-semantics-profile">
                      {profile ? (
                        <>
                          <span>{profileText(profile)}</span>
                          {profile.suggested_grain ? (
                            <span className={disagrees ? 'is-warning' : undefined}>Gợi ý: {GRAIN_LABELS[profile.suggested_grain]}</span>
                          ) : null}
                        </>
                      ) : (
                        <span className="is-muted">{profiles.length ? 'Không còn trong dữ liệu' : 'Bấm “Phát hiện grain” để xem'}</span>
                      )}
                    </div>
                  </td>
                  <td>
                    <Button variant="ghost" size="icon" aria-label={`Xoá grain của ${item.row_kind_value ?? 'dataset'}`} disabled={disabled} onClick={() => removeGrain(index)}>
                      <Trash2 />
                    </Button>
                  </td>
                </tr>
              );
            })}
            {value.grains.length === 0 ? (
              <tr>
                <td colSpan={byRowKind ? 5 : 3} className="sl-time-semantics-empty">
                  Chưa khai báo grain. Bấm “Phát hiện grain” để đọc dữ liệu và nhận gợi ý{byRowKind ? ', hoặc thêm loại dòng bên dưới.' : '.'}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      ) : null}
      {value.time_column && !byRowKind && value.grains.length === 0 ? (
        <Button variant="outline" size="sm" disabled={disabled} onClick={() => onChange({ ...value, grains: [{ row_kind_value: null, label: null, grain: 'day' }] })}>
          <Plus data-icon="inline-start" /> Khai báo grain thủ công
        </Button>
      ) : null}
      {byRowKind ? (
        <div className="sl-time-semantics-add">
          <Input
            aria-label="Giá trị loại dòng mới"
            disabled={disabled}
            placeholder={`Giá trị của ${value.row_kind_column}`}
            value={newRowKind}
            onChange={event => setNewRowKind(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter') addRowKind(); }}
          />
          <Button variant="outline" size="sm" disabled={disabled || !newRowKind.trim()} onClick={addRowKind}>
            <Plus data-icon="inline-start" /> Thêm loại dòng
          </Button>
        </div>
      ) : null}
    </div>
  );
}

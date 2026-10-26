import React, { useEffect, useState } from 'react';
import { AlertCircle, ListChecks, LoaderCircle, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import type { ColumnDictionary, IndicatorAggregation, IndicatorModel, IndicatorsResponse } from './types';

type IndicatorsPanelProps = {
  datasetId: number;
  columns: ColumnDictionary[];
  value: IndicatorModel | null;
  disabled: boolean;
  onChange: (value: IndicatorModel | null) => void;
};

type CatalogModel = Extract<IndicatorModel, { kind: 'catalog' }>;
type CatalogField = 'key_column' | 'code_column' | 'name_column' | 'unit_column' | 'value_kind_column' | 'aggregation_column';

const KIND_ITEMS: Array<{ label: string; value: IndicatorModel['kind'] | null }> = [
  { label: 'Không phải bảng chỉ số', value: null },
  { label: 'Bảng giá trị theo chỉ số', value: 'values' },
  { label: 'Bảng danh mục chỉ số', value: 'catalog' },
];
const CATALOG_FIELDS: Array<{ field: CatalogField; label: string; required: boolean }> = [
  { field: 'key_column', label: 'Cột khoá', required: true },
  { field: 'code_column', label: 'Cột mã chỉ số', required: true },
  { field: 'name_column', label: 'Cột tên chỉ số', required: true },
  { field: 'unit_column', label: 'Cột đơn vị', required: false },
  { field: 'value_kind_column', label: 'Cột kiểu giá trị', required: false },
  { field: 'aggregation_column', label: 'Cột cách tổng hợp', required: false },
];
const AGGREGATION_ITEMS: Array<{ label: string; value: IndicatorAggregation }> = [
  { label: 'Trung bình (AVG)', value: 'AVG' },
  { label: 'Tổng (SUM)', value: 'SUM' },
  { label: 'Nhỏ nhất (MIN)', value: 'MIN' },
  { label: 'Lớn nhất (MAX)', value: 'MAX' },
  { label: 'Đếm (COUNT)', value: 'COUNT' },
  { label: 'Không gộp được', value: 'NONE' },
];

function ColumnSelect({ label, value, columns, required, disabled, onChange }: {
  label: string; value: string | null; columns: ColumnDictionary[]; required: boolean; disabled: boolean;
  onChange: (value: string | null) => void;
}) {
  const items: Array<{ label: string; value: string | null }> = [
    { label: required ? 'Chọn cột' : 'Không có', value: null },
    ...columns.map(column => ({ label: column.column_name, value: column.column_name })),
  ];
  return (
    <Select items={items} value={value || null} disabled={disabled} onValueChange={onChange}>
      <SelectTrigger aria-label={label} className="w-full"><SelectValue /></SelectTrigger>
      <SelectContent alignItemWithTrigger={false}>
        <SelectGroup>
          {items.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

function newModel(kind: IndicatorModel['kind'], columns: ColumnDictionary[]): IndicatorModel {
  const key = columns.find(column => column.is_pk)?.column_name ?? '';
  if (kind === 'values') {
    return { kind, indicator_column: columns.find(column => column.is_fk)?.column_name ?? '', value_columns: {} };
  }
  return {
    kind, key_column: key, code_column: '', name_column: '', unit_column: null, value_kind_column: null,
    aggregation_column: null, aggregation_map: {},
  };
}

export function IndicatorsPanel({ datasetId, columns, value, disabled, onChange }: IndicatorsPanelProps) {
  const [preview, setPreview] = useState<IndicatorsResponse | null>(null);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');
  const [newKind, setNewKind] = useState('');

  useEffect(() => {
    setPreview(null);
    setError('');
  }, [datasetId, value?.kind]);

  const readIndicators = async (model: CatalogModel) => {
    setReading(true);
    setError('');
    try {
      setPreview(await requestJson<IndicatorsResponse>(semanticLayerApi.indicators(datasetId, model), 'GET'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không đọc được danh sách chỉ số.');
    } finally {
      setReading(false);
    }
  };

  const kindSelect = (
    <Field className="sl-indicators-kind">
      <FieldLabel>Loại bảng</FieldLabel>
      <Select items={KIND_ITEMS} value={value?.kind ?? null} disabled={disabled} onValueChange={kind => onChange(kind ? newModel(kind, columns) : null)}>
        <SelectTrigger aria-label="Loại bảng chỉ số" className="w-full"><SelectValue /></SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          <SelectGroup>
            {KIND_ITEMS.map(item => <SelectItem key={item.value ?? 'none'} value={item.value}>{item.label}</SelectItem>)}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  );

  return (
    <div className="sl-time-semantics sl-indicators">
      <div className="sl-time-semantics-header">
        <p>
          Bảng lưu giá trị theo từng chỉ số (dạng key-value) và bảng danh mục đặt tên các chỉ số. AI Agent dựa vào đây để
          tìm “nhiệt độ” là giá trị nào, đơn vị gì và tổng hợp ra sao.
        </p>
      </div>
      {kindSelect}
      {error ? <div className="sl-dictionary-save-error" role="alert"><AlertCircle /> {error}</div> : null}

      {value?.kind === 'values' ? (
        <>
          <div className="sl-time-semantics-columns">
            <Field>
              <FieldLabel title="Cột cho biết dòng là giá trị của chỉ số nào; nối tới bảng danh mục bằng một quan hệ đã duyệt">Cột chỉ số</FieldLabel>
              <ColumnSelect label="Cột chỉ số" value={value.indicator_column} columns={columns} required disabled={disabled} onChange={column => onChange({ ...value, indicator_column: column ?? '' })} />
            </Field>
          </div>
          <table className="sl-time-semantics-table">
            <thead>
              <tr>
                <th scope="col" className="is-kind">Kiểu giá trị</th>
                <th scope="col">Cột giữ giá trị</th>
                <th scope="col" className="is-action"><span className="sl-visually-hidden">Xoá</span></th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(value.value_columns).map(([code, column]) => (
                <tr key={code}>
                  <th scope="row"><code>{code}</code></th>
                  <td>
                    <ColumnSelect label={`Cột giá trị ${code}`} value={column} columns={columns} required disabled={disabled} onChange={next => onChange({ ...value, value_columns: { ...value.value_columns, [code]: next ?? '' } })} />
                  </td>
                  <td>
                    <Button variant="ghost" size="icon" aria-label={`Xoá kiểu ${code}`} disabled={disabled} onClick={() => {
                      const { [code]: _removed, ...rest } = value.value_columns;
                      onChange({ ...value, value_columns: rest });
                    }}><Trash2 /></Button>
                  </td>
                </tr>
              ))}
              {Object.keys(value.value_columns).length === 0 ? (
                <tr><td colSpan={3} className="sl-time-semantics-empty">Thêm mỗi kiểu giá trị (như SO, DUNG_SAI, CHU ở cột kiểu giá trị của bảng danh mục) cùng cột giữ giá trị của kiểu đó.</td></tr>
              ) : null}
            </tbody>
          </table>
          <div className="sl-time-semantics-add">
            <Input aria-label="Kiểu giá trị mới" disabled={disabled} placeholder="Mã kiểu giá trị, ví dụ SO" value={newKind} onChange={event => setNewKind(event.target.value)} />
            <Button variant="outline" size="sm" disabled={disabled || !newKind.trim() || newKind.trim() in value.value_columns} onClick={() => {
              onChange({ ...value, value_columns: { ...value.value_columns, [newKind.trim()]: '' } });
              setNewKind('');
            }}><Plus data-icon="inline-start" /> Thêm kiểu giá trị</Button>
          </div>
        </>
      ) : null}

      {value?.kind === 'catalog' ? (
        <>
          <div className="sl-indicators-catalog">
            {CATALOG_FIELDS.map(({ field, label, required }) => (
              <Field key={field}>
                <FieldLabel>{label}</FieldLabel>
                <ColumnSelect label={label} value={value[field]} columns={columns} required={required} disabled={disabled} onChange={column => onChange({ ...value, [field]: required ? column ?? '' : column })} />
              </Field>
            ))}
          </div>
          <div>
            <Button variant="outline" disabled={disabled || reading || !value.key_column || !value.code_column || !value.name_column} onClick={() => void readIndicators(value)}>
              {reading ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : <ListChecks data-icon="inline-start" />}
              {reading ? 'Đang đọc…' : 'Đọc danh sách chỉ số'}
            </Button>
          </div>
          {preview && value.aggregation_column && preview.aggregation_codes.length ? (
            <table className="sl-time-semantics-table sl-indicators-map">
              <thead>
                <tr>
                  <th scope="col" className="is-kind">Mã cách tổng hợp</th>
                  <th scope="col">Phép gộp SQL</th>
                </tr>
              </thead>
              <tbody>
                {preview.aggregation_codes.map(code => (
                  <tr key={code}>
                    <th scope="row"><code>{code}</code></th>
                    <td>
                      <Select items={AGGREGATION_ITEMS} value={value.aggregation_map[code] ?? null} disabled={disabled} onValueChange={aggregation => aggregation && onChange({ ...value, aggregation_map: { ...value.aggregation_map, [code]: aggregation } })}>
                        <SelectTrigger aria-label={`Phép gộp của ${code}`} className={value.aggregation_map[code] ? 'w-full' : 'w-full is-unmapped'}><SelectValue placeholder="Chưa ánh xạ" /></SelectTrigger>
                        <SelectContent alignItemWithTrigger={false}>
                          <SelectGroup>
                            {AGGREGATION_ITEMS.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {preview ? (
            <table className="sl-time-semantics-table sl-indicators-list">
              <thead>
                <tr>
                  <th scope="col">Mã</th>
                  <th scope="col">Tên</th>
                  <th scope="col">Đơn vị</th>
                  <th scope="col">Kiểu giá trị</th>
                  <th scope="col">Tổng hợp</th>
                </tr>
              </thead>
              <tbody>
                {preview.indicators.map(indicator => {
                  const aggregation = indicator.aggregation_code ? value.aggregation_map[indicator.aggregation_code] : null;
                  return (
                    <tr key={String(indicator.key)}>
                      <td><code>{indicator.code}</code></td>
                      <td>{indicator.name}</td>
                      <td>{indicator.unit ?? '—'}</td>
                      <td>{indicator.value_kind ?? '—'}</td>
                      <td className={aggregation || !indicator.aggregation_code ? undefined : 'is-warning'}>
                        {aggregation ? AGGREGATION_ITEMS.find(item => item.value === aggregation)?.label : indicator.aggregation_code ? `${indicator.aggregation_code} · chưa ánh xạ` : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : null}
          {preview?.too_many ? <p className="sl-time-semantics-note is-warning">Bảng có hơn 500 chỉ số; chỉ 500 chỉ số đầu được hiện.</p> : null}
        </>
      ) : null}
    </div>
  );
}

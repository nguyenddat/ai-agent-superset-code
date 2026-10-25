import React, { useEffect, useState } from 'react';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { ReferenceDataset } from './types';

type ReferenceFieldsProps = {
  datasets: ReferenceDataset[];
  datasetId: number | null;
  columnName: string | null;
  /** The column being described; tables and columns with the same name are offered first. */
  sourceColumnName: string;
  sourceDatasetId: number;
  disabled?: boolean;
  onChange: (datasetId: number | null, columnName: string | null) => void;
};

/**
 * Foreign key target as two selects: the referenced table first, then one of its columns. A table picked without a
 * column stays local until a column is chosen, because the dictionary stores the target as a table/column pair.
 */
export function ReferenceFields({
  datasets,
  datasetId,
  columnName,
  sourceColumnName,
  sourceDatasetId,
  disabled = false,
  onChange,
}: ReferenceFieldsProps) {
  const [pendingDatasetId, setPendingDatasetId] = useState<number | null>(datasetId);
  useEffect(() => { setPendingDatasetId(datasetId); }, [datasetId]);

  const tableId = datasetId ?? pendingDatasetId;
  const table = datasets.find(dataset => dataset.id === tableId);
  const sorted = [...datasets].sort((a, b) => a.dataset_name.localeCompare(b.dataset_name));
  const hasSameName = (dataset: ReferenceDataset) => (
    dataset.id !== sourceDatasetId && dataset.columns.includes(sourceColumnName)
  );
  const suggested = sorted.filter(hasSameName);
  const others = sorted.filter(dataset => !hasSameName(dataset));
  const tableItems = [
    { label: 'Không tham chiếu', value: null as number | null },
    ...sorted.map(dataset => ({ label: dataset.dataset_name, value: dataset.id as number | null })),
  ];

  const isKey = (name: string) => !!(table?.key_columns?.[name]?.pk || table?.key_columns?.[name]?.unique);
  const availableColumns = (table?.columns ?? []).filter(name => !(table?.id === sourceDatasetId && name === sourceColumnName));
  const keyColumns = availableColumns.filter(isKey);
  const otherColumns = availableColumns.filter(name => !isKey(name));
  const columnItems = [
    { label: 'Chọn cột', value: null as string | null },
    ...availableColumns.map(name => ({ label: name, value: name as string | null })),
  ];

  const selectTable = (nextId: number | null) => {
    if (nextId === null) {
      setPendingDatasetId(null);
      onChange(null, null);
      return;
    }
    const next = datasets.find(dataset => dataset.id === nextId);
    // A column with the same name is the likely key, so it is filled in; otherwise the user picks the column next.
    const sameName = next && next.id !== sourceDatasetId && next.columns.includes(sourceColumnName) ? sourceColumnName : null;
    setPendingDatasetId(nextId);
    if (sameName) onChange(nextId, sameName);
    else if (datasetId !== null) onChange(null, null);
  };

  const renderTable = (dataset: ReferenceDataset) => (
    <SelectItem key={dataset.id} value={dataset.id}>
      <span className="sl-reference-item">
        <span className="sl-reference-item-name">{dataset.dataset_name}</span>
        {dataset.id === sourceDatasetId ? <span className="sl-reference-item-meta">bảng hiện tại</span> : null}
      </span>
    </SelectItem>
  );
  const renderColumn = (name: string) => (
    <SelectItem key={name} value={name}>
      <span className="sl-reference-item">
        <span className="sl-reference-item-name">{name}</span>
        {table?.key_columns?.[name]?.pk ? <span className="sl-reference-badge">PK</span> : isKey(name) ? <span className="sl-reference-badge">UQ</span> : null}
        {name === sourceColumnName ? <span className="sl-reference-item-meta">cùng tên</span> : null}
        <span className="sl-reference-item-meta is-type">{table?.column_types?.[name] ?? ''}</span>
      </span>
    </SelectItem>
  );

  return (
    <>
      <div className="sl-column-detail">
        <span>Reference table</span>
        <Select items={tableItems} value={tableId} disabled={disabled} onValueChange={value => selectTable(value)}>
          <SelectTrigger aria-label={`Bảng tham chiếu của ${sourceColumnName}`} className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="max-h-80 min-w-64">
            <SelectGroup>
              <SelectItem value={null}>Không tham chiếu</SelectItem>
            </SelectGroup>
            {suggested.length > 0 ? (
              <>
                <SelectSeparator />
                <SelectGroup>
                  <SelectLabel>Gợi ý · có cột {sourceColumnName}</SelectLabel>
                  {suggested.map(renderTable)}
                </SelectGroup>
              </>
            ) : null}
            <SelectSeparator />
            <SelectGroup>
              <SelectLabel>{suggested.length > 0 ? 'Bảng khác' : 'Bảng'}</SelectLabel>
              {others.map(renderTable)}
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>
      <div className="sl-column-detail">
        <span>Reference column</span>
        <Select items={columnItems} value={datasetId !== null ? columnName : null} disabled={disabled || !table} onValueChange={value => { if (table && value) onChange(table.id, value); }}>
          <SelectTrigger aria-label={`Cột tham chiếu của ${sourceColumnName}`} className="w-full">
            <SelectValue>{(value: string | null) => value ?? <span className="text-muted-foreground">{table ? 'Chọn cột' : 'Chọn bảng trước'}</span>}</SelectValue>
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="max-h-80 min-w-96">
            {keyColumns.length > 0 ? (
              <SelectGroup>
                <SelectLabel>Cột khóa</SelectLabel>
                {keyColumns.map(renderColumn)}
              </SelectGroup>
            ) : null}
            {keyColumns.length > 0 && otherColumns.length > 0 ? <SelectSeparator /> : null}
            {otherColumns.length > 0 ? (
              <SelectGroup>
                {keyColumns.length > 0 ? <SelectLabel>Cột khác</SelectLabel> : null}
                {otherColumns.map(renderColumn)}
              </SelectGroup>
            ) : null}
          </SelectContent>
        </Select>
      </div>
    </>
  );
}

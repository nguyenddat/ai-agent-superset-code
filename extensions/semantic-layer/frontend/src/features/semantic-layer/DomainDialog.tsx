import React, { useEffect, useMemo, useState } from 'react';
import { LoaderCircle, Search, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { requestJson, semanticLayerApi } from './api';
import { getDatasetName } from './datasets';
import type { BusinessDomain, DashboardDataset } from './types';

export const DOMAIN_COLORS = ['#2563eb', '#0d9488', '#d97706', '#db2777', '#7c3aed', '#059669', '#dc2626', '#0891b2'];
export const COLOR_NAMES: Record<string, string> = {
  '#2563eb': 'Xanh dương',
  '#0d9488': 'Xanh ngọc',
  '#d97706': 'Cam',
  '#db2777': 'Hồng',
  '#7c3aed': 'Tím',
  '#059669': 'Xanh lá',
  '#dc2626': 'Đỏ',
  '#0891b2': 'Xanh lơ',
};

type DomainDialogProps = {
  open: boolean;
  domain: BusinessDomain | null;
  /** Datasets grouped by their data-dictionary layer, in flow order. */
  groups: Array<{ label: string; datasets: DashboardDataset[] }>;
  usedColors: string[];
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
};

/** Creates or edits a business domain: its name, description, colour and member tables. */
export function DomainDialog({ open, domain, groups, usedColors, onOpenChange, onSaved }: DomainDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState(DOMAIN_COLORS[0]);
  const [datasetIds, setDatasetIds] = useState<number[]>([]);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setName(domain?.name ?? '');
    setDescription(domain?.description ?? '');
    setColor(domain?.color ?? DOMAIN_COLORS.find(item => !usedColors.includes(item)) ?? DOMAIN_COLORS[0]);
    setDatasetIds(domain?.dataset_ids ?? []);
    setSearch('');
    setError('');
  }, [open, domain]);

  const visibleGroups = useMemo(() => {
    const query = search.trim().toLowerCase();
    return groups
      .map(group => ({ ...group, datasets: group.datasets.filter(dataset => !query || getDatasetName(dataset).toLowerCase().includes(query)) }))
      .filter(group => group.datasets.length > 0);
  }, [groups, search]);

  const toggleDataset = (datasetId: number, checked: boolean) => {
    setDatasetIds(current => checked ? [...new Set([...current, datasetId])] : current.filter(id => id !== datasetId));
  };

  const save = async () => {
    if (!name.trim()) {
      setError('Nhập tên nghiệp vụ.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const body = { name: name.trim(), description: description.trim() || null, color, dataset_ids: datasetIds };
      if (domain) await requestJson(semanticLayerApi.businessDomain(domain.id), 'PUT', body);
      else await requestJson(semanticLayerApi.businessDomains, 'POST', body);
      onSaved();
      onOpenChange(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không lưu được nghiệp vụ.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!domain || !window.confirm(`Xóa nghiệp vụ "${domain.name}"? Các bảng vẫn được giữ nguyên.`)) return;
    setBusy(true);
    setError('');
    try {
      await requestJson(semanticLayerApi.businessDomain(domain.id), 'DELETE');
      onSaved();
      onOpenChange(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không xóa được nghiệp vụ.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={next => onOpenChange(next)}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{domain ? 'Sửa nghiệp vụ' : 'Thêm nghiệp vụ'}</DialogTitle>
          <DialogDescription>Gom các bảng theo nghiệp vụ. Một bảng có thể thuộc nhiều nghiệp vụ.</DialogDescription>
        </DialogHeader>
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="sl-domain-name">Tên nghiệp vụ</FieldLabel>
            <Input id="sl-domain-name" value={name} maxLength={255} placeholder="Ví dụ: Khám bệnh" onChange={event => setName(event.target.value)} />
          </Field>
          <Field>
            <FieldLabel htmlFor="sl-domain-description">Mô tả</FieldLabel>
            <Textarea id="sl-domain-description" rows={2} value={description} placeholder="Phạm vi và mục đích của nghiệp vụ" onChange={event => setDescription(event.target.value)} />
          </Field>
          <FieldSet>
            <FieldLegend variant="label">Màu</FieldLegend>
            <div className="flex gap-2">
              {DOMAIN_COLORS.map(item => (
                <button
                  key={item}
                  type="button"
                  aria-label={`Màu ${item}`}
                  aria-pressed={item === color}
                  className="sl-color-swatch"
                  style={{ background: item }}
                  onClick={() => setColor(item)}
                />
              ))}
            </div>
          </FieldSet>
          <FieldSet>
            <FieldLegend variant="label">Bảng ({datasetIds.length} đã chọn)</FieldLegend>
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input className="pl-8" value={search} placeholder="Tìm bảng…" onChange={event => setSearch(event.target.value)} />
            </div>
            <div className="sl-domain-dataset-list">
              {visibleGroups.map(group => (
                <div key={group.label} className="flex flex-col gap-1">
                  <span className="px-1 text-xs font-medium text-muted-foreground">{group.label}</span>
                  {group.datasets.map(dataset => (
                    <label key={dataset.id} className="flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 hover:bg-accent">
                      <Checkbox checked={datasetIds.includes(dataset.id)} onCheckedChange={checked => toggleDataset(dataset.id, checked)} />
                      <span className="truncate">{getDatasetName(dataset)}</span>
                    </label>
                  ))}
                </div>
              ))}
              {visibleGroups.length === 0 ? <span className="px-1 py-2 text-muted-foreground">Không có bảng phù hợp.</span> : null}
            </div>
          </FieldSet>
          {error ? <p role="alert" className="text-destructive">{error}</p> : null}
        </FieldGroup>
        <DialogFooter>
          {domain ? (
            <Button variant="destructive" className="sm:mr-auto" disabled={busy} onClick={() => void remove()}>
              <Trash2 data-icon="inline-start" /> Xóa
            </Button>
          ) : null}
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>Hủy</Button>
          <Button disabled={busy} onClick={() => void save()}>
            {busy ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : null}
            Lưu
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

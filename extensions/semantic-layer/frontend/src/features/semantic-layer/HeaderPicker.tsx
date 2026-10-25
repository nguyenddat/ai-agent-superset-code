import React, { useMemo } from 'react';
import type { LucideIcon } from 'lucide-react';
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

export type HeaderPickerItem = { value: number; label: string; group?: string };

type HeaderPickerProps = {
  ariaLabel: string;
  icon: LucideIcon;
  caption?: string;
  items: HeaderPickerItem[];
  value: number | null;
  onChange: (value: number) => void;
  disabled?: boolean;
  placeholder: string;
};

/**
 * Header selector built on shadcn Select. Base UI's Combobox popup never gets positioned under Superset's
 * React 17, so the pickers use Select; items that carry a group are listed under group headings.
 */
export function HeaderPicker({
  ariaLabel,
  icon: Icon,
  caption,
  items,
  value,
  onChange,
  disabled = false,
  placeholder,
}: HeaderPickerProps) {
  const groups = useMemo(() => {
    const byGroup = new Map<string, HeaderPickerItem[]>();
    for (const item of items) {
      const group = item.group ?? '';
      byGroup.set(group, [...(byGroup.get(group) ?? []), item]);
    }
    return [...byGroup];
  }, [items]);
  const selectItems = useMemo(
    () => [{ label: placeholder, value: null as number | null }, ...items.map(item => ({ label: item.label, value: item.value as number | null }))],
    [items, placeholder],
  );

  return (
    <Select items={selectItems} value={value} disabled={disabled} onValueChange={next => { if (next != null) onChange(next); }}>
      <SelectTrigger aria-label={ariaLabel} className="h-9 w-full min-w-0 bg-card">
        <Icon className="text-primary" />
        {caption ? <span className="shrink-0 border-r border-border pr-2 text-xs font-semibold text-muted-foreground max-md:hidden">{caption}</span> : null}
        <SelectValue className="min-w-0 truncate" />
      </SelectTrigger>
      <SelectContent alignItemWithTrigger={false} align="end" className="min-w-72">
        {groups.map(([group, groupItems], index) => (
          <SelectGroup key={group || 'items'}>
            {index > 0 ? <SelectSeparator /> : null}
            {group ? <SelectLabel>{group}</SelectLabel> : null}
            {groupItems.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}

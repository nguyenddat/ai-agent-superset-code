import React, { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, GripVertical, LoaderCircle, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import { layerLevels } from './datasets';
import { COLOR_NAMES, DOMAIN_COLORS } from './DomainDialog';
import type { DataLayer } from './types';

type DraftLayer = { key: string; id: number | null; name: string; description: string; color: string };
/** The layers of one level; `key` follows the level while it moves. */
type DraftLevel = { key: string; layers: DraftLayer[] };

/** What is being dragged: one layer, or a whole level. */
type Dragging = { kind: 'layer'; key: string } | { kind: 'level'; key: string };
/**
 * Where a drop would land: before a layer (or at the end of a level when `before` is null), or in the gap before the
 * level at `index`, which makes a new level for a layer and moves a dragged level there.
 */
type DropTarget = { kind: 'layer'; level: string; before: string | null } | { kind: 'gap'; index: number };

type LayersDialogProps = {
  open: boolean;
  layers: DataLayer[];
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
};

const colorItems = DOMAIN_COLORS.map(color => ({ label: COLOR_NAMES[color] ?? color, value: color }));

const toDraft = (layer: DataLayer): DraftLayer => ({
  key: `layer-${layer.id}`,
  id: layer.id,
  name: layer.name,
  description: layer.description ?? '',
  color: layer.color ?? DOMAIN_COLORS[0],
});

let draftSequence = 0;
const newKey = (prefix: string) => `${prefix}-new-${(draftSequence += 1)}`;

/** `levels` with the layer `key` taken out; a level left without layers goes too, since every level holds one. */
function withoutLayer(levels: DraftLevel[], key: string): { levels: DraftLevel[]; layer: DraftLayer | null } {
  const layer = levels.flatMap(level => level.layers).find(item => item.key === key) ?? null;
  const rest = levels.map(level => ({ ...level, layers: level.layers.filter(item => item.key !== key) }));
  return { levels: rest.filter(level => level.layers.length > 0), layer };
}

/** `levels` after dropping what is dragged on `target`. */
function dropped(levels: DraftLevel[], dragging: Dragging, target: DropTarget): DraftLevel[] {
  if (dragging.kind === 'level') {
    if (target.kind !== 'gap') return levels;
    const from = levels.findIndex(level => level.key === dragging.key);
    if (from < 0) return levels;
    const next = [...levels];
    const [moved] = next.splice(from, 1);
    next.splice(target.index > from ? target.index - 1 : target.index, 0, moved);
    return next;
  }
  const { levels: rest, layer } = withoutLayer(levels, dragging.key);
  if (!layer) return levels;
  if (target.kind === 'gap') {
    // The gap index counts levels before the layer left its own, which may have gone with it.
    const index = levels.slice(0, target.index).filter(level => rest.some(item => item.key === level.key)).length;
    const next = [...rest];
    next.splice(index, 0, { key: newKey('level'), layers: [layer] });
    return next;
  }
  // A level's only layer dropped back on it stays where it was.
  if (!rest.some(level => level.key === target.level)) return levels;
  return rest.map(level => {
    if (level.key !== target.level) return level;
    const at = target.before === null ? level.layers.length : level.layers.findIndex(item => item.key === target.before);
    const layers = [...level.layers];
    layers.splice(at < 0 ? layers.length : at, 0, layer);
    return { ...level, layers };
  });
}

const sameTarget = (a: DropTarget | null, b: DropTarget) => (
  a !== null && a.kind === b.kind && (a.kind === 'gap'
    ? a.index === (b as Extract<DropTarget, { kind: 'gap' }>).index
    : a.level === (b as Extract<DropTarget, { kind: 'layer' }>).level && a.before === (b as Extract<DropTarget, { kind: 'layer' }>).before)
);

/**
 * Edits the admin-defined data layers on their levels. Data flows from a level to the levels after it, so lineage
 * draws an FK into an earlier level as data flowing forward, and an FK between layers of one level as a relation.
 * Layers are dragged within or between levels, or into the gap between two levels to start a new one; a level is
 * dragged by its handle. Changes are applied together on save.
 */
export function LayersDialog({ open, layers, onOpenChange, onSaved }: LayersDialogProps) {
  const [levels, setLevels] = useState<DraftLevel[]>([]);
  const [dragging, setDragging] = useState<Dragging | null>(null);
  const [target, setTarget] = useState<DropTarget | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setLevels(layerLevels(layers).map(level => ({ key: `level-${level[0].level}`, layers: level.map(toDraft) })));
    setError('');
  }, [open, layers]);

  const layerCount = levels.reduce((sum, level) => sum + level.layers.length, 0);
  const update = (key: string, values: Partial<DraftLayer>) => {
    setLevels(current => current.map(level => ({ ...level, layers: level.layers.map(draft => (draft.key === key ? { ...draft, ...values } : draft)) })));
  };
  const remove = (key: string) => setLevels(current => withoutLayer(current, key).levels);
  const blankLayer = (): DraftLayer => ({
    key: newKey('layer'),
    id: null,
    name: '',
    description: '',
    color: DOMAIN_COLORS[layerCount % DOMAIN_COLORS.length],
  });
  const addLayer = (levelKey: string) => {
    setLevels(current => current.map(level => (level.key === levelKey ? { ...level, layers: [...level.layers, blankLayer()] } : level)));
  };
  const addLevel = () => setLevels(current => [...current, { key: newKey('level'), layers: [blankLayer()] }]);
  // Keyboard alternatives to dragging: a level moves up or down; a layer moves to the level before or after its own,
  // past the last level into a new one.
  const moveLevel = (index: number, offset: number) => setLevels(current => {
    const next = [...current];
    const [moved] = next.splice(index, 1);
    next.splice(index + offset, 0, moved);
    return next;
  });
  const moveLayer = (key: string, levelIndex: number, offset: number) => setLevels(current => {
    const destination = levelIndex + offset;
    if (destination >= current.length) return dropped(current, { kind: 'layer', key }, { kind: 'gap', index: current.length });
    if (destination < 0) return dropped(current, { kind: 'layer', key }, { kind: 'gap', index: 0 });
    return dropped(current, { kind: 'layer', key }, { kind: 'layer', level: current[destination].key, before: null });
  });

  const startDrag = (event: React.DragEvent, next: Dragging, image: HTMLElement | null) => {
    event.dataTransfer.effectAllowed = 'move';
    // Firefox only starts a drag that carries data.
    event.dataTransfer.setData('text/plain', next.key);
    if (image) event.dataTransfer.setDragImage(image, 16, 16);
    setDragging(next);
  };
  const endDrag = () => {
    setDragging(null);
    setTarget(null);
  };
  // A drop target accepts what it can take: layers land on levels and gaps, levels only in gaps.
  const over = (event: React.DragEvent, next: DropTarget) => {
    if (!dragging || (dragging.kind === 'level' && next.kind !== 'gap')) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = 'move';
    if (!sameTarget(target, next)) setTarget(next);
  };
  const drop = (event: React.DragEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (dragging && target) setLevels(current => dropped(current, dragging, target));
    endDrag();
  };

  const save = async () => {
    const drafts = levels.flatMap(level => level.layers);
    const names = drafts.map(draft => draft.name.trim());
    if (names.some(name => !name)) {
      setError('Mỗi tầng cần có tên.');
      return;
    }
    if (new Set(names).size !== names.length) {
      setError('Tên tầng không được trùng nhau.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const kept = new Set(drafts.map(draft => draft.id).filter((id): id is number => id !== null));
      for (const layer of layers) {
        if (!kept.has(layer.id)) await requestJson(semanticLayerApi.dataLayer(layer.id), 'DELETE');
      }
      const ids = new Map<string, number>();
      for (const draft of drafts) {
        const body = { name: draft.name.trim(), description: draft.description.trim() || null, color: draft.color };
        const original = layers.find(layer => layer.id === draft.id);
        if (draft.id === null) {
          const created = await requestJson<{ layer: DataLayer }>(semanticLayerApi.dataLayers, 'POST', body);
          ids.set(draft.key, created.layer.id);
        } else {
          if (!original || original.name !== body.name || (original.description ?? null) !== body.description || original.color !== body.color) {
            await requestJson(semanticLayerApi.dataLayer(draft.id), 'PUT', body);
          }
          ids.set(draft.key, draft.id);
        }
      }
      const order = levels.map(level => level.layers.map(draft => ids.get(draft.key) as number)).filter(level => level.length > 0);
      if (order.length > 0) await requestJson(semanticLayerApi.dataLayersOrder, 'PUT', { levels: order });
      onSaved();
      onOpenChange(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không lưu được tầng dữ liệu.');
      onSaved();
    } finally {
      setBusy(false);
    }
  };

  const gap = (index: number) => {
    const active = dragging !== null && target?.kind === 'gap' && target.index === index;
    return (
      <div
        key={`gap-${index}`}
        className={`sl-level-gap${dragging ? ' is-dragging' : ''}${active ? ' is-active' : ''}`}
        onDragOver={event => over(event, { kind: 'gap', index })}
        onDrop={drop}
      >
        {dragging ? <span>{dragging.kind === 'layer' ? 'Thả vào đây để tạo cấp mới' : 'Chuyển cấp tới đây'}</span> : null}
      </div>
    );
  };

  return (
    <Dialog open={open} onOpenChange={next => onOpenChange(next)}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Tầng dữ liệu</DialogTitle>
          <DialogDescription>
            Dữ liệu chảy từ cấp trên xuống cấp dưới. Các tầng song song, như Danh mục và Kỹ thuật, đặt chung một cấp.
            Kéo một tầng sang cấp khác hoặc vào khoảng giữa hai cấp để tạo cấp mới; kéo tay nắm của cấp để đổi thứ tự.
          </DialogDescription>
        </DialogHeader>
        <div className="sl-level-list">
          {levels.map((level, index) => {
            const levelTarget = dragging?.kind === 'layer' && target?.kind === 'layer' && target.level === level.key;
            return (
              <React.Fragment key={level.key}>
                {gap(index)}
                <section
                  className={`sl-level${levelTarget ? ' is-target' : ''}${dragging?.kind === 'level' && dragging.key === level.key ? ' is-dragged' : ''}`}
                  aria-label={`Cấp ${index + 1}`}
                  onDragOver={event => over(event, { kind: 'layer', level: level.key, before: null })}
                  onDrop={drop}
                >
                  <div className="sl-level-head">
                    <span
                      className="sl-level-grip"
                      draggable
                      title="Kéo để đổi thứ tự cấp"
                      onDragStart={event => startDrag(event, { kind: 'level', key: level.key }, event.currentTarget.closest('.sl-level'))}
                      onDragEnd={endDrag}
                    >
                      <GripVertical />
                    </span>
                    <strong>Cấp {index + 1}</strong>
                    <span className="sl-level-hint">
                      {index === 0 ? 'Nguồn' : `Nhận dữ liệu từ cấp ${index}`}
                      {level.layers.length > 1 ? ` · ${level.layers.length} tầng cùng cấp` : ''}
                    </span>
                    <span className="sl-level-actions">
                      <Button size="icon-xs" variant="ghost" aria-label={`Đưa cấp ${index + 1} lên trước`} disabled={index === 0} onClick={() => moveLevel(index, -1)}><ArrowUp /></Button>
                      <Button size="icon-xs" variant="ghost" aria-label={`Đưa cấp ${index + 1} xuống sau`} disabled={index === levels.length - 1} onClick={() => moveLevel(index, 1)}><ArrowDown /></Button>
                    </span>
                  </div>
                  <div className="sl-level-layers">
                    {level.layers.map(draft => {
                      const before = dragging?.kind === 'layer' && target?.kind === 'layer' && target.level === level.key && target.before === draft.key;
                      return (
                        <div
                          key={draft.key}
                          className={`sl-level-layer${before ? ' is-drop-before' : ''}${dragging?.kind === 'layer' && dragging.key === draft.key ? ' is-dragged' : ''}`}
                          style={{ '--layer-color': draft.color } as React.CSSProperties}
                          onDragOver={event => over(event, { kind: 'layer', level: level.key, before: draft.key })}
                          onDrop={drop}
                        >
                          <div className="sl-level-layer-top">
                            <span
                              className="sl-level-grip"
                              draggable
                              title="Kéo sang cấp khác"
                              onDragStart={event => startDrag(event, { kind: 'layer', key: draft.key }, event.currentTarget.closest('.sl-level-layer'))}
                              onDragEnd={endDrag}
                            >
                              <GripVertical />
                            </span>
                            <Select items={colorItems} value={draft.color} onValueChange={color => { if (color) update(draft.key, { color }); }}>
                              <SelectTrigger aria-label={`Màu của tầng ${draft.name || 'mới'}`} className="w-14" size="sm">
                                <SelectValue>{(value: string) => <span className="sl-color-dot" style={{ background: value }} />}</SelectValue>
                              </SelectTrigger>
                              <SelectContent alignItemWithTrigger={false} className="min-w-40">
                                <SelectGroup>
                                  {colorItems.map(item => (
                                    <SelectItem key={item.value} value={item.value}>
                                      <span className="sl-color-dot" style={{ background: item.value }} />{item.label}
                                    </SelectItem>
                                  ))}
                                </SelectGroup>
                              </SelectContent>
                            </Select>
                            <Input aria-label="Tên tầng" placeholder="Tên tầng" value={draft.name} onChange={event => update(draft.key, { name: event.target.value })} />
                            <Button size="icon-xs" variant="ghost" aria-label={`Xóa tầng ${draft.name || 'mới'}`} onClick={() => remove(draft.key)}><Trash2 /></Button>
                          </div>
                          <div className="sl-level-layer-bottom">
                            <Input aria-label="Mô tả tầng" placeholder="Mô tả ngắn" value={draft.description} onChange={event => update(draft.key, { description: event.target.value })} />
                            <Button
                              size="icon-xs"
                              variant="ghost"
                              aria-label={`Chuyển tầng ${draft.name || 'mới'} lên cấp trước`}
                              title="Chuyển lên cấp trước"
                              disabled={index === 0 && level.layers.length === 1}
                              onClick={() => moveLayer(draft.key, index, -1)}
                            >
                              <ArrowUp />
                            </Button>
                            <Button
                              size="icon-xs"
                              variant="ghost"
                              aria-label={`Chuyển tầng ${draft.name || 'mới'} xuống cấp sau`}
                              title="Chuyển xuống cấp sau"
                              disabled={index === levels.length - 1 && level.layers.length === 1}
                              onClick={() => moveLayer(draft.key, index, 1)}
                            >
                              <ArrowDown />
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                    <button type="button" className="sl-level-add" onClick={() => addLayer(level.key)}>
                      <Plus /> Thêm tầng cùng cấp
                    </button>
                  </div>
                </section>
              </React.Fragment>
            );
          })}
          {levels.length > 0 ? gap(levels.length) : null}
          {levels.length === 0 ? <p className="sl-empty">Chưa có tầng nào. Ví dụ: Nguồn, Chuẩn hóa, Phục vụ báo cáo.</p> : null}
        </div>
        <Button variant="outline" className="w-fit" onClick={addLevel}><Plus data-icon="inline-start" /> Thêm cấp mới</Button>
        {error ? <p role="alert" className="text-destructive">{error}</p> : null}
        <DialogFooter>
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

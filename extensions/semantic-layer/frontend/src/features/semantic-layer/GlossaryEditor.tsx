import React, { useEffect, useState } from 'react';
import { Minus, Plus, Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { DashboardDataset, GlossaryLink, GlossaryProvenance, GlossaryTerm, GlossaryTermPayload } from './types';

type DraftLink = { dataset_id: number | null; column_name: string; metric_id: number | null };
type Props = {
  term: GlossaryTerm | null;
  datasets: DashboardDataset[];
  busy: boolean;
  onCancel: () => void;
  onSave: (payload: GlossaryTermPayload, expectedRevision?: number) => void;
};

const emptyLink = (): DraftLink => ({ dataset_id: null, column_name: '', metric_id: null });
const current = (term: GlossaryTerm | null) => term?.current_revision ?? term?.revisions?.find(revision => revision.is_current) ?? null;

/** Editor for an admin candidate. An AI origin stays a draft until the separate approve action succeeds. */
export function GlossaryEditor({ term, datasets, busy, onCancel, onSave }: Props) {
  const [name, setName] = useState('');
  const [definition, setDefinition] = useState('');
  const [synonyms, setSynonyms] = useState('');
  const [ownerId, setOwnerId] = useState('');
  const [stewardId, setStewardId] = useState('');
  const [provenance, setProvenance] = useState<GlossaryProvenance>('manual');
  const [links, setLinks] = useState<DraftLink[]>([emptyLink()]);

  useEffect(() => {
    const revision = current(term);
    setName(term?.canonical_name ?? revision?.canonical_name ?? '');
    setDefinition(revision?.definition ?? '');
    setSynonyms((revision?.synonyms ?? []).join(', '));
    setOwnerId(term?.owner_id?.toString() ?? '');
    setStewardId(term?.steward_id?.toString() ?? '');
    setProvenance(revision?.provenance ?? 'manual');
    setLinks(revision?.links.length ? revision.links.map(link => ({
      dataset_id: link.dataset_id,
      column_name: link.column_name ?? '',
      metric_id: link.metric_id ?? null,
    })) : [emptyLink()]);
  }, [term]);

  const updateLink = (index: number, patch: Partial<DraftLink>) => setLinks(items => items.map((item, itemIndex) => (
    itemIndex === index ? { ...item, ...patch } : item
  )));
  const submit = () => {
    const parsedLinks: GlossaryLink[] = links
      .filter(link => link.dataset_id !== null)
      .map(link => ({
        kind: link.metric_id !== null ? 'metric' : link.column_name.trim() ? 'column' : 'dataset',
        dataset_id: link.dataset_id as number,
        column_name: link.column_name.trim() || null,
        metric_id: link.metric_id,
      }));
    onSave({
      canonical_name: name.trim(),
      definition: definition.trim(),
      synonyms: synonyms.split(',').map(value => value.trim()).filter(Boolean),
      owner_id: ownerId ? Number(ownerId) : null,
      steward_id: stewardId ? Number(stewardId) : null,
      provenance,
      links: parsedLinks,
    }, current(term)?.revision_number);
  };

  return <section className="sl-glossary-editor" aria-label={term ? `Edit ${name || 'glossary term'}` : 'Create glossary term'}>
    <header><h3>{term ? 'Edit draft' : 'New glossary term'}</h3><p>Changes create or update a candidate draft; they are not discoverable until approved.</p></header>
    <div className="sl-glossary-fields">
      <label>Canonical name<Input value={name} disabled={busy} onChange={event => setName(event.target.value)} /></label>
      <label>Synonyms <small>comma-separated</small><Input value={synonyms} disabled={busy} onChange={event => setSynonyms(event.target.value)} /></label>
      <label>Owner user ID<Input type="number" min="1" value={ownerId} disabled={busy} onChange={event => setOwnerId(event.target.value)} /></label>
      <label>Steward user ID<Input type="number" min="1" value={stewardId} disabled={busy} onChange={event => setStewardId(event.target.value)} /></label>
      <label>Provenance<select value={provenance} disabled={busy} onChange={event => setProvenance(event.target.value as GlossaryProvenance)}>
        <option value="manual">Manual</option><option value="import">Import</option><option value="ai_suggestion">AI suggestion (candidate only)</option>
      </select></label>
      <label className="sl-glossary-wide">Definition<Textarea value={definition} disabled={busy} onChange={event => setDefinition(event.target.value)} /></label>
    </div>
    <section className="sl-glossary-links" aria-label="Semantic links"><div><h4>Semantic links</h4><p>Link each term to a live dataset column or saved metric.</p></div>
      {links.map((link, index) => {
        const dataset = datasets.find(item => item.id === link.dataset_id);
        return <div className="sl-glossary-link" key={index}>
          <select aria-label={`Dataset link ${index + 1}`} value={link.dataset_id ?? ''} disabled={busy} onChange={event => updateLink(index, { dataset_id: event.target.value ? Number(event.target.value) : null, column_name: '', metric_id: null })}>
            <option value="">Select dataset</option>{datasets.map(item => <option key={item.id} value={item.id}>{item.datasource_name || item.name || item.table_name || `Dataset ${item.id}`}</option>)}
          </select>
          <select aria-label={`Column link ${index + 1}`} value={link.column_name} disabled={busy || !dataset} onChange={event => updateLink(index, { column_name: event.target.value, metric_id: null })}>
            <option value="">Column (or choose metric)</option>{dataset?.columns?.map(column => <option key={column.column_name} value={column.column_name}>{column.column_name}</option>)}
          </select>
          <select aria-label={`Metric link ${index + 1}`} value={link.metric_id ?? ''} disabled={busy || !dataset} onChange={event => updateLink(index, { metric_id: event.target.value ? Number(event.target.value) : null, column_name: '' })}>
            <option value="">Metric (or choose column)</option>{dataset?.metrics?.map(metric => <option key={metric.id} value={metric.id}>{metric.verbose_name || metric.metric_name}</option>)}
          </select>
          <Button variant="ghost" size="icon" disabled={busy || links.length === 1} aria-label="Remove link" onClick={() => setLinks(items => items.filter((_, itemIndex) => itemIndex !== index))}><Minus /></Button>
        </div>;
      })}
      <Button variant="outline" size="sm" disabled={busy} onClick={() => setLinks(items => [...items, emptyLink()])}><Plus data-icon="inline-start" /> Add link</Button>
    </section>
    <footer className="sl-glossary-editor-actions"><Button variant="outline" disabled={busy} onClick={onCancel}>Cancel</Button><Button disabled={busy} onClick={submit}><Save data-icon="inline-start" /> Save draft</Button></footer>
  </section>;
}

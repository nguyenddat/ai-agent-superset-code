import React, { useCallback, useEffect, useState } from 'react';
import { Check, FileClock, LoaderCircle, Plus, RotateCcw, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { requestJson, semanticLayerApi } from './api';
import { GlossaryEditor } from './GlossaryEditor';
import type { DashboardDataset, GlossaryAuditEvent, GlossaryRevision, GlossaryTerm, GlossaryTermPayload } from './types';

type Props = { datasets: DashboardDataset[] };
const revisionFor = (term: GlossaryTerm): GlossaryRevision | null => term.current_revision ?? term.revisions?.find(revision => revision.is_current) ?? null;
const responseTerms = (payload: { terms?: GlossaryTerm[] } | GlossaryTerm[]) => Array.isArray(payload) ? payload : payload.terms ?? [];

/** Admin-facing, versioned glossary workflow. Discovery has its own permission-filtered API and is intentionally not shown here. */
export function Glossary({ datasets }: Props) {
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [selected, setSelected] = useState<GlossaryTerm | null>(null);
  const [editing, setEditing] = useState(false);
  const [audit, setAudit] = useState<GlossaryAuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const payload = await requestJson<{ terms?: GlossaryTerm[] } | GlossaryTerm[]>(semanticLayerApi.glossary, 'GET');
      setTerms(responseTerms(payload));
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load glossary.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const choose = async (term: GlossaryTerm) => {
    setError(''); setAudit([]);
    try {
      const payload = await requestJson<{ term?: GlossaryTerm } | GlossaryTerm>(semanticLayerApi.glossaryTerm(term.id), 'GET');
      setSelected(('term' in payload ? payload.term : payload as GlossaryTerm) ?? term);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load term.'); }
  };
  const save = async (payload: GlossaryTermPayload, expectedRevision?: number) => {
    setBusy(true); setError('');
    try {
      const result = selected
        ? await requestJson<{ term?: GlossaryTerm }>(semanticLayerApi.glossaryDraft(selected.id), 'PUT', { ...payload, expected_revision: expectedRevision })
        : await requestJson<{ term?: GlossaryTerm }>(semanticLayerApi.glossary, 'POST', payload);
      await load(); setSelected(result.term ?? null); setEditing(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to save draft.'); }
    finally { setBusy(false); }
  };
  const lifecycle = async (action: 'approve' | 'revoke') => {
    if (!selected) return;
    const revision = revisionFor(selected); if (!revision) return;
    const reason = window.prompt(`${action === 'approve' ? 'Approval' : 'Revocation'} reason (required):`);
    if (!reason?.trim()) return;
    setBusy(true); setError('');
    try {
      const endpoint = action === 'approve' ? semanticLayerApi.glossaryApprove(selected.id) : semanticLayerApi.glossaryRevoke(selected.id);
      const result = await requestJson<{ term?: GlossaryTerm }>(endpoint, 'POST', { expected_revision: revision.revision_number, reason: reason.trim() });
      setSelected(result.term ?? selected); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Lifecycle action failed.'); }
    finally { setBusy(false); }
  };
  const loadAudit = async () => {
    if (!selected) return;
    setBusy(true); setError('');
    try { const payload = await requestJson<{ events?: GlossaryAuditEvent[] } | GlossaryAuditEvent[]>(semanticLayerApi.glossaryAudit(selected.id), 'GET'); setAudit(Array.isArray(payload) ? payload : payload.events ?? []); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to load audit.'); }
    finally { setBusy(false); }
  };

  const revision = selected ? revisionFor(selected) : null;
  return <main className="sl-glossary">
    <header className="sl-glossary-toolbar"><div><h3>Business Glossary</h3><p>Approved terms are discoverable only through permission-filtered consumer discovery.</p></div><Button onClick={() => { setSelected(null); setEditing(true); }}><Plus data-icon="inline-start" /> New term</Button></header>
    {error ? <div className="sl-glossary-error" role="alert">{error}</div> : null}
    <div className="sl-glossary-layout"><section className="sl-glossary-list" aria-label="Glossary terms">
      {loading ? <p className="sl-glossary-state"><LoaderCircle className="sl-spin" /> Loading glossary…</p> : terms.length === 0 ? <p className="sl-glossary-state">No governed terms yet.</p> : terms.map(term => { const itemRevision = revisionFor(term); return <button key={term.id} className={`sl-glossary-term${selected?.id === term.id ? ' is-selected' : ''}`} onClick={() => void choose(term)}><strong>{term.canonical_name}</strong><span><em className={`sl-glossary-status is-${itemRevision?.status ?? 'draft'}`}>{itemRevision?.status ?? 'draft'}</em> v{itemRevision?.revision_number ?? '—'}</span></button>; })}
      <Button variant="ghost" size="sm" onClick={() => void load()}><RotateCcw data-icon="inline-start" /> Refresh</Button>
    </section>
    <section className="sl-glossary-detail">{editing ? <GlossaryEditor term={selected} datasets={datasets} busy={busy} onCancel={() => setEditing(false)} onSave={(payload, expectedRevision) => void save(payload, expectedRevision)} /> : selected && revision ? <>
      <header className="sl-glossary-detail-heading"><div><h3>{selected.canonical_name}</h3><p><em className={`sl-glossary-status is-${revision.status}`}>{revision.status}</em> <span className="sl-glossary-provenance">{revision.provenance === 'ai_suggestion' ? 'AI suggestion — candidate only' : revision.provenance}</span> · version {revision.revision_number}</p></div><Button variant="outline" onClick={() => setEditing(true)}>Edit draft</Button></header>
      <p className="sl-glossary-definition">{revision.definition}</p>{revision.synonyms.length ? <p><strong>Synonyms:</strong> {revision.synonyms.join(', ')}</p> : null}
      <p><strong>Owner:</strong> {selected.owner_id ?? '—'} · <strong>Steward:</strong> {selected.steward_id ?? '—'}</p>
      <ul className="sl-glossary-linked-objects">{revision.links.map(link => <li key={link.id ?? `${link.dataset_id}-${link.column_name ?? link.metric_id}`}><strong>{link.dataset_name ?? `Dataset ${link.dataset_id}`}</strong>{link.column_name ? ` · column ${link.column_name}` : ''}{link.metric_name ? ` · metric ${link.metric_name}` : link.metric_id ? ` · metric ${link.metric_id}` : ''}</li>)}</ul>
      <div className="sl-glossary-actions">{revision.status === 'draft' ? <Button disabled={busy} onClick={() => void lifecycle('approve')}><Check data-icon="inline-start" /> Approve</Button> : null}{revision.status === 'approved' ? <Button variant="outline" disabled={busy} onClick={() => void lifecycle('revoke')}><X data-icon="inline-start" /> Revoke</Button> : null}<Button variant="outline" disabled={busy} onClick={() => void loadAudit()}><FileClock data-icon="inline-start" /> Audit</Button></div>
      {audit.length ? <ol className="sl-glossary-audit">{audit.map(event => <li key={event.id}><strong>{event.action}</strong>{event.revision_number ? ` · v${event.revision_number}` : ''}{event.reason ? ` · ${event.reason}` : ''}<small>{event.created_at ? new Date(event.created_at).toLocaleString() : ''}</small></li>)}</ol> : null}
    </> : <p className="sl-glossary-state">Select a term to inspect its current revision, or create a new candidate.</p>}</section></div>
  </main>;
}

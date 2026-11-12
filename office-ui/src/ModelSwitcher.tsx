import React, { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { api, type ModelSettings } from './api';
import type { ProviderId } from './types';

export function ModelSwitcher({ runActive, onApplied }: { runActive: boolean; onApplied: () => void }) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [draft, setDraft] = useState<Partial<Record<ProviderId, string>>>({});
  const [custom, setCustom] = useState<Partial<Record<ProviderId, boolean>>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const reduced = useReducedMotion();
  const busy = runActive || !!settings?.busy;
  const accept = (data: ModelSettings) => { setSettings(data); setDraft(Object.fromEntries(data.providers.map(p => [p.id, p.model]))); setCustom({}); };

  useEffect(() => {
    if (!open) return;
    let disposed = false;
    setError(''); setSaved(false);
    api.models().then(data => { if (!disposed) accept(data); }).catch(e => { if (!disposed) setError(e.message); });
    const outside = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape);
    return () => { disposed = true; document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open, runActive]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault(); if (saving || busy) return;
    setSaving(true); setError(''); setSaved(false);
    try { accept(await api.saveModels(draft)); setSaved(true); onApplied(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  };
  return <div className="model-switcher" ref={ref}>
    <button type="button" ref={trigger} className="models-trigger" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="model-settings-panel" data-testid="open-models"><span aria-hidden="true">☷</span> Models <span aria-hidden="true">⌄</span></button>
    <AnimatePresence>{open && <motion.div id="model-settings-panel" className="model-settings-panel" initial={{ opacity: 0, y: reduced ? 0 : -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: reduced ? 0 : -4 }} transition={{ duration: .16 }}>
      <div className="model-settings-heading"><div><span className="eyebrow">YOUR COUNCIL</span><h2>Choose the models</h2></div><button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }} aria-label="Close model settings">×</button></div>
      <p className="model-settings-help">Applies to new tasks and resumed steps. Changing models starts no agent calls.</p>
      <form onSubmit={save}>
        {!settings && !error && <p className="small muted">Loading model settings…</p>}
        {settings?.providers.map(provider => <div className="provider-model-field" key={provider.id}>
          <label htmlFor={`model-${provider.id}`}>{provider.name}<span>{provider.effort} effort</span></label>
          <select id={`model-${provider.id}`} value={custom[provider.id] ? '__custom' : draft[provider.id] || provider.model} disabled={saving || busy} onChange={e => {
            setSaved(false);
            if (e.target.value === '__custom') setCustom({ ...custom, [provider.id]: true });
            else { setCustom({ ...custom, [provider.id]: false }); setDraft({ ...draft, [provider.id]: e.target.value }); }
          }}>
            {provider.options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}<option value="__custom">Other model…</option>
          </select>
          {custom[provider.id] && <input aria-label={`${provider.name} custom model ID`} value={draft[provider.id] || ''} onChange={e => { setSaved(false); setDraft({ ...draft, [provider.id]: e.target.value }); }} placeholder="Exact model ID" required maxLength={128} disabled={saving || busy} />}
        </div>)}
        {busy && <p className="model-settings-warning">Pause the active run before changing models.</p>}
        {error && <p className="model-settings-error" role="alert">{error}</p>}
        {saved && <p className="model-settings-saved" role="status">Models saved. Ready for your next task.</p>}
        <button type="submit" className="primary wide-button" disabled={!settings || saving || busy || Object.values(draft).some(v => !v?.trim())}>{saving ? 'Saving…' : 'Apply models'}</button>
      </form>
    </motion.div>}</AnimatePresence>
  </div>;
}

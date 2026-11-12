import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { api, connectEvents, getToken } from './api';
import { applyEventReplayStep, enforceSingleWriterSeat } from './office/stateMachine';
import { AREA_BY_ROOM, stateLabel, workflowArea } from './office/workspace';
import { AGENT_IDS } from './office/visuals';
import { useRetroAudio } from './office/useRetroAudio';
import { PixelOfficeCanvas } from './office/PixelOfficeCanvas';
import { AgentInspector, AgentStatusCards, ApprovalDialog, ConversationPanel, TaskBoard } from './panels';
import { AreaIcon, AreaNavigation, AreaWorkspace, ProviderIssue } from './workspacePanels';
import { TaskComposer } from './TaskComposer';
import { ModelSwitcher } from './ModelSwitcher';
import type { AgentSnapshot, CouncilEventItem, OfficeRoom, OfficeSnapshot, ProviderId } from './types';

const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

export const OfficeApp: React.FC = () => {
  const reduced = useReducedMotion();
  const [snap, setSnap] = useState<OfficeSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [area, setArea] = useState<OfficeRoom>('desks');
  const [follow, setFollow] = useState(true);
  const [selectedAgent, setSelectedAgent] = useState<ProviderId | null>(null);
  const [showApproval, setShowApproval] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [composerOpen, setComposerOpen] = useState<boolean | null>(null);
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<'discuss' | 'plan'>('discuss');
  const [cwd, setCwd] = useState('');
  const [showActivity, setShowActivity] = useState(false);
  const [replay, setReplay] = useState<{ events: CouncilEventItem[]; idx: number; agents: Record<ProviderId, AgentSnapshot> } | null>(null);
  const wsRef = useRef<ReturnType<typeof connectEvents> | null>(null);
  const snapRef = useRef(snap); snapRef.current = snap;
  const requestedRun = useRef<string | null>(null);
  const workspaceRef = useRef<HTMLElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const focusRequested = useRef(false);
  const sound = useRetroAudio();
  const previousRun = useRef<{ id: string; state: string; approved: boolean } | null>(null);

  useEffect(() => {
    if (!getToken()) {
      setError('Open the office URL printed in PowerShell, including its ?token=… parameter.');
      return;
    }
    let disposed = false;
    const acceptSnapshot = (data: OfficeSnapshot) => {
      if (!disposed && (!requestedRun.current || data.active_run_id === requestedRun.current)) setSnap(data);
    };
    api.state().then(acceptSnapshot).catch(e => { if (!disposed) setError(errorText(e)); });
    wsRef.current = connectEvents(msg => {
      if (msg.type === 'snapshot') acceptSnapshot(msg.data);
      else if (msg.type === 'events') acceptSnapshot(msg.snapshot);
      else if (msg.type === 'replay' && snapRef.current?.run?.run_id === msg.run_id) {
        const baseline = { ...snapRef.current.agents };
        AGENT_IDS.forEach(id => { baseline[id] = {
          ...baseline[id], room: 'desks', seat_id: `desk-${id}`, animation: 'idle',
          current_task: 'Replay starting', status_badge: 'IDLE', tool_calls: [], elapsed_ms: 0,
          usage: { input_tokens: 0, output_tokens: 0, cost_usd: null, duration_ms: 0 }, latest_output: null,
        }; });
        setReplay({ events: msg.events, idx: 0, agents: baseline });
      }
    }, live => {
      if (disposed) return;
      setConnected(live);
      if (live && requestedRun.current) wsRef.current?.send({ action: 'select_run', run_id: requestedRun.current });
    });
    return () => { disposed = true; wsRef.current?.close(); };
  }, []);

  useEffect(() => {
    const run = snap?.run;
    const previous = previousRun.current;
    if (run && !replay && previous?.id === run.run_id) {
      if (previous.state !== run.state) sound.play(run.state === 'COMPLETED' ? 'complete' : run.state === 'FAILED' ? 'error'
        : !previous.approved && run.approved ? 'approval' : 'stage');
      else if (!previous.approved && run.approved) sound.play('approval');
    }
    previousRun.current = run ? { id: run.run_id, state: run.state, approved: run.approved } : null;
  }, [snap?.run?.run_id, snap?.run?.state, snap?.run?.approved, !!replay, sound.play]);

  useEffect(() => {
    if (snap && follow && !replay) { setArea(workflowArea(snap)); setSelectedAgent(null); }
  }, [snap?.run?.state, snap?.run?.run_id, follow, !!replay]);

  useEffect(() => {
    if (!focusRequested.current) return;
    focusRequested.current = false;
    const target = workspaceRef.current?.querySelector<HTMLElement>('[data-selection-panel]') || workspaceRef.current;
    target?.focus({ preventScroll: true });
    if (window.innerWidth < 1100) target?.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }, [area, selectedAgent]);

  useEffect(() => {
    if (composerOpen) { composerRef.current?.focus(); composerRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
  }, [composerOpen]);

  useEffect(() => {
    if (!replay || replay.idx >= replay.events.length) return;
    const timer = window.setTimeout(() => setReplay(r => r && ({ ...r, agents: applyEventReplayStep(r.agents, r.events[r.idx]), idx: r.idx + 1 })), 450);
    return () => window.clearTimeout(timer);
  }, [replay]);

  const selectArea = (room: OfficeRoom) => {
    setFollow(false); focusRequested.current = true; setSelectedAgent(null); setArea(room);
    if (room === area && !selectedAgent) workspaceRef.current?.focus({ preventScroll: true });
  };
  const selectAgent = (id: ProviderId) => {
    setFollow(false); focusRequested.current = true; setSelectedAgent(id); setArea(snapRef.current?.agents[id].room || 'desks');
  };
  const openComposer = () => {
    setComposerOpen(true);
    const input = composerRef.current;
    if (input) { input.focus(); input.scrollIntoView({ block: 'center', behavior: reduced ? 'instant' : 'smooth' }); }
  };
  const selectRun = useCallback((id: string) => {
    requestedRun.current = id; setReplay(null); setFollow(true); setSelectedAgent(null); setError(null);
    wsRef.current?.send({ action: 'select_run', run_id: id });
    api.state(id).then(data => { if (requestedRun.current === id) setSnap(data); }).catch(e => setError(errorText(e)));
  }, []);

  const startRun = async (event: React.FormEvent) => {
    event.preventDefault(); if (!question.trim() || starting) return;
    setStarting(true); setError(null); setReplay(null);
    try {
      const response = await api.startRun({ mode, question: question.trim(), cwd: cwd.trim() || undefined });
      if (!response.run_id) throw new Error('The server did not create a run. Check the server log and try again.');
      requestedRun.current = response.run_id; setSnap(response.snapshot); setFollow(true); setSelectedAgent(null);
      wsRef.current?.send({ action: 'select_run', run_id: response.run_id });
      setQuestion(''); setComposerOpen(false);
    } catch (e) { setError(errorText(e)); } finally { setStarting(false); }
  };

  const approve = async (writer: ProviderId, createPr: boolean) => {
    if (!snap?.run) return;
    setApprovalBusy(true); setApprovalError(null);
    try {
      const response = await api.approve(snap.run.run_id, { writer, create_pr: createPr });
      if (!response.approved || !response.snapshot.run?.approved) throw new Error('Approval was not confirmed by the server.');
      setSnap(response.snapshot); setShowApproval(false); setFollow(true);
    } catch (e) { setApprovalError(errorText(e)); } finally { setApprovalBusy(false); }
  };
  const runAction = async (action: 'cancel' | 'resume') => {
    if (!snap?.run || actionBusy) return;
    setActionBusy(true); setError(null); setReplay(null);
    try { const response = await api[action](snap.run.run_id); setSnap(response.snapshot); if (action === 'resume') setFollow(true); }
    catch (e) { setError(errorText(e)); } finally { setActionBusy(false); }
  };

  if (!snap) return <div className="app loading"><div className="brand-mark" aria-hidden="true">P</div><h1>Opening your council office</h1><p>{error || 'Connecting to the local server…'}</p>{error && <button type="button" onClick={() => location.reload()}>Reconnect</button>}</div>;

  const run = snap.run;
  const agents = enforceSingleWriterSeat(replay?.agents || snap.agents, run?.writer || null);
  const terminal = !run || ['COMPLETED', 'FAILED', 'CANCELLED'].includes(run.state);
  const areaInfo = AREA_BY_ROOM[area];
  const occupants = AGENT_IDS.filter(id => agents[id].room === area);
  return <motion.div className="app" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reduced ? 0 : .28 }} onClickCapture={e => {
    const button = (e.target as HTMLElement).closest('button');
    if (button && !button.disabled && !button.hasAttribute('data-sound-toggle')) sound.play('click');
  }}>
    {snap.demo_mode && <div className="demo-banner">SIMULATED DEMO — these are not real agent calls</div>}
    <motion.header className="app-header" initial={{ opacity: 0, y: reduced ? 0 : -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .3 }}>
      <div className="brand"><span className="brand-mark" aria-hidden="true">P<span /></span><div><span className="eyebrow">PEER CONSULT</span><h1>Council Office<span className="brand-cursor" aria-hidden="true">_</span></h1></div></div>
      <span className={`connection-indicator ${connected ? 'ok' : 'err'}`} data-testid="ws-status">{connected ? '● live' : '○ reconnecting'}</span>
      <div className="header-actions"><label className="run-picker"><span className="sr-only">Run history</span><select aria-label="Run history" value={snap.active_run_id || ''} onChange={e => selectRun(e.target.value)} disabled={!snap.runs.length}>
        {!snap.runs.length && <option value="">No runs yet</option>}{snap.runs.map(r => <option key={r.run_id} value={r.run_id}>{r.question.slice(0, 42) || r.run_id} · {stateLabel(r.state)}</option>)}
      </select></label><ModelSwitcher runActive={!terminal} onApplied={() => api.state(requestedRun.current || undefined).then(setSnap).catch(e => setError(errorText(e)))} /><button type="button" data-sound-toggle onClick={sound.toggle} aria-pressed={!sound.muted} aria-label={sound.muted ? 'Enable retro sound effects' : 'Mute retro sound effects'} disabled={sound.unavailable} className="sound-toggle">{sound.unavailable ? 'Audio unavailable' : sound.muted ? '♪ Off' : '♪ On'}</button><button type="button" className="primary" onClick={openComposer}>＋ New task</button></div>
    </motion.header>

    <AgentStatusCards agents={agents} selectedAgent={selectedAgent} onSelect={selectAgent} />
    <AreaNavigation area={area} snapshot={{ ...snap, agents }} onSelect={selectArea} />
    {error && <div className="banner err" role="alert">{error}<button type="button" onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>}
    {replay && <div className="replay-banner" role="status"><span>EVENT REPLAY · {replay.idx} / {replay.events.length} · recorded activity</span><button type="button" onClick={() => setReplay(null)}>Exit replay</button></div>}

    <main className="office-layout">
      <section className="office-main">
        <section className="run-overview">
          <div><span className="eyebrow">{run ? `${run.mode === 'discuss' ? 'RESEARCH & DISCUSSION' : 'PLAN & IMPLEMENTATION'} / CURRENT TASK` : 'YOUR TEAM IS READY'}</span><h2>{run?.question || 'What shall we work on?'}</h2><p>{run ? `Chair: ${agents[run.chair]?.name || run.chair}${run.writer ? ` · Writer: ${agents[run.writer]?.name || run.writer}` : ''}` : 'Start with a question. Research, discuss, resolve doubts, then build.'}</p></div>
          {run && <span className={`run-status run-${run.state.toLowerCase()}`} data-testid="run-state" data-state={run.state}>{stateLabel(run.state)}</span>}
          {run && <div className="run-actions">{run.state === 'AWAITING_APPROVAL' && <button className="primary" type="button" data-testid="open-approval" onClick={() => setShowApproval(true)}>Review & approve</button>}{!terminal && <button type="button" data-testid="cancel-btn" disabled={actionBusy || !!replay} onClick={() => runAction('cancel')}>Pause run</button>}{['FAILED', 'CANCELLED'].includes(run.state) && <button type="button" data-testid="resume-btn" disabled={actionBusy || !!replay} onClick={() => runAction('resume')}>{actionBusy ? 'Resuming…' : 'Resume run'}</button>}<button type="button" disabled={!connected || !!replay} data-testid="replay-btn" onClick={() => wsRef.current?.send({ action: 'replay', run_id: run.run_id })}>Replay events</button></div>}
        </section>
        {run?.error?.message && <div className="run-error-summary"><span>! <b>A provider needs attention.</b> Completed work is saved.</span><button type="button" onClick={() => selectArea('review_room')}>View in Doubts →</button></div>}
        <div className="map-section">
          <div className="section-toolbar"><div><span className="live-dot" /> <b>Office floor</b><span className="muted"> · agents move with the workflow</span></div><label className="follow-control"><input type="checkbox" checked={follow} onChange={e => { setFollow(e.target.checked); if (e.target.checked) { setArea(workflowArea(snap)); setSelectedAgent(null); } }} />Follow workflow</label></div>
          <PixelOfficeCanvas agents={agents} selectedAgentId={selectedAgent} selectedRoom={area} designatedWriter={run?.writer || null} onSelectAgent={selectAgent} onSelectRoom={selectArea} />
        </div>
        <TaskBoard columns={snap.task_board} />
        <TaskComposer open={composerOpen ?? !run} onOpenChange={setComposerOpen} question={question} onQuestionChange={setQuestion}
          mode={mode} onModeChange={setMode} cwd={cwd} onCwdChange={setCwd} starting={starting} connected={connected} inputRef={composerRef} onSubmit={startRun} />
        <details className="activity-section" open={showActivity} onToggle={e => setShowActivity(e.currentTarget.open)}><summary>Activity log <span>{snap.events.length} events</span></summary>{showActivity && <ConversationPanel events={snap.events} />}</details>
      </section>

      <aside className="workspace-sidebar" ref={workspaceRef} tabIndex={-1} aria-label={`${areaInfo.name} workspace`}>
        <div className="workspace-heading" style={{ '--area-color': areaInfo.color } as React.CSSProperties}><span className="area-icon"><AreaIcon room={area} /></span><div><h2>{areaInfo.name}</h2><p>{occupants.length ? `${occupants.length} ${occupants.length === 1 ? 'agent' : 'agents'} assigned` : 'Ready when needed'}</p></div>{selectedAgent && <button type="button" onClick={() => setSelectedAgent(null)}>← Workspace</button>}</div>
        <div className="workspace-content"><motion.div key={selectedAgent || area} className="workspace-view" initial={{ opacity: 0, y: reduced ? 0 : 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reduced ? 0 : .24 }}>
          {selectedAgent ? <AgentInspector key={selectedAgent} agent={agents[selectedAgent]} onClose={() => { focusRequested.current = true; setSelectedAgent(null); }} /> : <AreaWorkspace key={area} room={area} snapshot={snap} onApprove={() => setShowApproval(true)} onNewTask={openComposer} />}
          {!selectedAgent && area === 'review_room' && run?.error?.message && !AGENT_IDS.some(id => agents[id].animation === 'failed') && <ProviderIssue message={run.error.message} />}
        </motion.div></div>
      </aside>
    </main>
    <footer className="app-footer"><span>PEER CONSULT <span className="muted">/ local council workspace</span></span><span>{run?.run_id || 'No active task'} · {replay ? 'replay' : connected ? 'live connection' : 'reconnecting'}</span></footer>
    <AnimatePresence>{showApproval && <ApprovalDialog key="approval" snapshot={snap} busy={approvalBusy} error={approvalError} onApprove={approve} onCancel={() => setShowApproval(false)} />}</AnimatePresence>
  </motion.div>;
};

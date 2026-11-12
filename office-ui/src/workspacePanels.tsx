import React, { useState } from 'react';
import { LayoutGroup, motion, useReducedMotion } from 'motion/react';
import type { OfficeRoom, OfficeSnapshot, ProviderId } from './types';
import { AGENT_IDS } from './office/visuals';
import { AREAS, AREA_BY_ROOM, describeIssue } from './office/workspace';
import { ExecutionPanel, MeetingDrawer } from './panels';

export function AreaIcon({ room }: { room: OfficeRoom }) {
  const paths: Record<OfficeRoom, React.ReactNode> = {
    desks: <><path d="M4 4h6l2 2 2-2h6v15h-6l-2 2-2-2H4z"/><path d="M12 6v15M7 8h2m-2 4h2m6-4h2m-2 4h2"/></>,
    meeting_room: <><path d="M3 4h18v12h-9l-5 4v-4H3z"/><path d="M7 8h10M7 12h6"/></>,
    review_room: <><path d="M5 3h14v18H5z"/><path d="M9 8a3 3 0 0 1 6 0c0 2-3 2-3 4m0 3v1"/></>,
    coding_room: <><path d="M3 4h18v16H3zM3 8h18M7 12l3 2-3 2m6 0h4"/></>,
  };
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="miter" aria-hidden="true">{paths[room]}</svg>;
}

export const AreaNavigation: React.FC<{
  area: OfficeRoom; snapshot: OfficeSnapshot; onSelect: (room: OfficeRoom) => void;
}> = ({ area, snapshot, onSelect }) => {
  const reduced = useReducedMotion();
  return <LayoutGroup id="office-areas"><nav className="area-navigation" aria-label="Office work areas">
    {AREAS.map(item => {
      const count = AGENT_IDS.filter(id => snapshot.agents[id].room === item.room).length;
      return <motion.button key={item.room} type="button" className={`area-nav-item ${area === item.room ? 'active' : ''}`}
        style={{ '--area-color': item.color } as React.CSSProperties} aria-pressed={area === item.room}
        whileHover={reduced ? undefined : { y: -2 }} whileTap={reduced ? undefined : { scale: .98 }}
        onClick={() => onSelect(item.room)} data-testid={`area-${item.room}`}>
        {area === item.room && <motion.span className="area-selection-surface" layoutId="selected-work-area" transition={{ type: 'spring', stiffness: 420, damping: 36 }} aria-hidden="true" />}
        <span className="area-icon"><AreaIcon room={item.room} /></span><span className="area-nav-copy"><b>{item.name}</b><small>{item.purpose}</small></span>
        <span className="area-agent-count" title={`${count} agents assigned`}>{count}</span>
      </motion.button>;
    })}
  </nav></LayoutGroup>;
};

export const EmptyState: React.FC<{ title: string; children: React.ReactNode; room?: OfficeRoom }> = ({ title, children, room = 'desks' }) => (
  <div className="empty-state"><span className="empty-icon"><AreaIcon room={room} /></span><h3>{title}</h3><p>{children}</p></div>
);

export const ProviderIssue: React.FC<{ message: string; name?: string }> = ({ message, name }) => {
  const issue = describeIssue(message);
  return <article className="provider-issue" role="status"><span className="eyebrow">{name || 'RUN'} / NEEDS ATTENTION</span>
    <h3>{issue.title}</h3><p>{issue.detail}</p><details><summary>Technical details</summary><pre>{message}</pre></details></article>;
};

export const ResearchPanel: React.FC<{ snapshot: OfficeSnapshot }> = ({ snapshot }) => {
  const proposals = Object.entries(snapshot.meeting.proposals);
  return <div data-testid="research-panel">
    <div className="workspace-intro"><span className="eyebrow">01 / RESEARCH</span><h2>Find the evidence.</h2><p>Independent perspectives, source material, and initial recommendations.</p></div>
    {!proposals.length && <EmptyState title={snapshot.run?.state === 'PROPOSING' ? 'Research is underway' : 'A place for your next question'}>Start a task to collect independent proposals from Claude, Codex, and Antigravity. Results appear here as each agent finishes.</EmptyState>}
    {proposals.map(([id, proposal]) => <article className="research-card" key={id}>
      <div className="content-card-heading"><span className={`provider-name agent-${id}`}>{snapshot.agents[id as ProviderId]?.name || id}</span><span className="pill">{proposal.confidence} confidence</span></div>
      <h3>{proposal.summary}</h3><p>{proposal.recommendation}</p>
      {proposal.evidence?.length > 0 && <div className="evidence-list"><h4>Evidence</h4>{proposal.evidence.map(e => <div key={e.id}><span className={e.verified ? 'ok' : 'muted'}>{e.verified ? 'Verified' : 'To verify'}</span><p>{e.claim}</p><code>{e.reference}</code></div>)}</div>}
      <details><summary>Approach & implementation notes</summary><p>{proposal.assessment || proposal.proposed_approach}</p><ol>{proposal.implementation_steps?.map((s, i) => <li key={i}>{s}</li>)}</ol>{proposal.affected_files?.length > 0 && <p className="small muted">Files: {proposal.affected_files.join(', ')}</p>}</details>
    </article>)}
  </div>;
};

export const DoubtsPanel: React.FC<{ snapshot: OfficeSnapshot }> = ({ snapshot }) => {
  const [filter, setFilter] = useState<'all' | 'blocking'>('all');
  const disagreements = snapshot.meeting.unresolved_disagreements;
  const questions = Object.entries(snapshot.meeting.critiques).flatMap(([agent, c]) => (c.unresolved_questions || []).map(q => ({ agent, question: q })));
  const assumptions = snapshot.meeting.synthesis?.assumptions_ledger || [];
  const findings = snapshot.execution?.peer_reviews.flatMap(r => r.output.findings.map(f => ({ ...f, agent: r.agent }))) || [];
  const failedAgents = AGENT_IDS.filter(id => snapshot.agents[id].animation === 'failed');
  const hasContent = disagreements.length + questions.length + assumptions.length + findings.length + failedAgents.length;
  return <div data-testid="doubts-panel">
    <div className="workspace-intro"><span className="eyebrow">03 / DOUBTS & REVIEW</span><h2>Make uncertainty visible.</h2><p>Open questions, conflicting ideas, assumptions, and issues that need a decision.</p></div>
    <div className="doubt-summary"><span><b>{disagreements.filter(d => d.blocking).length}</b> blockers</span><span><b>{questions.length}</b> questions</span><span><b>{findings.length}</b> review findings</span></div>
    {failedAgents.map(id => <ProviderIssue key={id} name={snapshot.agents[id].name} message={snapshot.agents[id].current_task} />)}
    {!!disagreements.length && <><div className="content-card-heading"><h3>Disagreements</h3><label className="small">Show <select aria-label="Filter disagreements" value={filter} onChange={e => setFilter(e.target.value as 'all' | 'blocking')}><option value="all">All</option><option value="blocking">Blocking only</option></select></label></div>
      {disagreements.filter(d => filter === 'all' || d.blocking).map((d, i) => <article className={`doubt-card ${d.blocking ? 'blocking' : ''}`} key={i}><span className={`pill ${d.blocking ? 'err' : 'muted'}`}>{d.blocking ? 'Decision needed' : 'Open question'}</span><h3>{d.topic}</h3>{d.positions.map((p, j) => <p key={j}><b>{p.agent_or_proposal}:</b> {p.stance}</p>)}<div className="resolution-note"><b>Suggested next step</b><p>{d.recommended_resolution}</p></div></article>)}</>}
    {questions.length > 0 && <section className="content-section"><h3>Questions from discussion</h3>{questions.map((q, i) => <article className="doubt-card" key={i}><span className="eyebrow">{q.agent}</span><p>{q.question}</p></article>)}</section>}
    {assumptions.length > 0 && <section className="content-section"><h3>Assumptions to validate</h3>{assumptions.map(a => <article className="doubt-card" key={a.id}><h4>{a.assumption}</h4><p className="small">Check: {a.validation_check}</p><p className="muted small">If incorrect: {a.impact_if_false}</p></article>)}</section>}
    {findings.length > 0 && <section className="content-section"><h3>Peer review findings</h3>{findings.map((f, i) => <article className="doubt-card" key={i}><span className="pill">{f.severity}</span><h4>{f.description}</h4><code>{f.file_path}:{f.line_range}</code><p>{f.suggested_fix}</p></article>)}</section>}
    {!hasContent && <EmptyState room="review_room" title="Nothing unresolved yet">As the council works, this area collects doubts and review findings. An empty list does not mean review has finished.</EmptyState>}
    <div className="clarification-note"><b>Want the council to investigate a doubt?</b><p>Use New task with a specific question. Choose Research & discussion for a read-only answer.</p></div>
  </div>;
};

export const AreaWorkspace: React.FC<{ room: OfficeRoom; snapshot: OfficeSnapshot; onApprove: () => void; onNewTask: () => void }> = ({ room, snapshot, onApprove, onNewTask }) => {
  const area = AREA_BY_ROOM[room];
  return <div className="area-workspace" data-testid="area-workspace" style={{ '--area-color': area.color } as React.CSSProperties}>
    {room === 'desks' && <ResearchPanel snapshot={snapshot} />}
    {room === 'meeting_room' && <><div className="workspace-intro"><span className="eyebrow">02 / DISCUSSION</span><h2>Bring the ideas together.</h2><p>Compare proposals, read peer critiques, and inspect the chair’s recommendation.</p></div><MeetingDrawer meeting={snapshot.meeting} onClose={() => {}} hideHeader initialTab="critiques" /></>}
    {room === 'review_room' && <DoubtsPanel snapshot={snapshot} />}
    {room === 'coding_room' && <><div className="workspace-intro"><span className="eyebrow">04 / CODING</span><h2>Turn the plan into working code.</h2><p>A designated writer implements the approved scope. Tests and peer reviews appear here.</p></div>
      {!snapshot.execution && <EmptyState room="coding_room" title="Your implementation workspace">Choose Plan & implementation when starting a task. After the council creates a plan, review it and approve the writer to begin coding.</EmptyState>}
      {snapshot.run?.state === 'AWAITING_APPROVAL' && <button type="button" className="primary wide-button" onClick={onApprove}>Review plan & approve coding</button>}
      {snapshot.execution && <ExecutionPanel execution={snapshot.execution} onClose={() => {}} hideHeader />}</>}
  </div>;
};

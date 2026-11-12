import React, { useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import type {
  AgentSnapshot,
  CouncilEventItem,
  ExecutionData,
  MeetingData,
  OfficeSnapshot,
  OfficeRoom,
  ProviderId,
  TaskBoardColumn,
} from './types';
import { AGENT_IDS, CHAR_ASSETS } from './office/visuals';
import { OFFICE_SEATS, ROOM_ZONES } from './office/stateMachine';
import { AREA_BY_ROOM, describeIssue, formatTime } from './office/workspace';

const fmtMs = (ms: number) => (ms >= 60000 ? `${(ms / 60000).toFixed(1)}m` : `${(ms / 1000).toFixed(1)}s`);

const AgentPortrait: React.FC<{ agent: AgentSnapshot }> = ({ agent }) => (
  <span className={`agent-portrait state-${agent.animation}`} aria-hidden="true">
    <span style={{ backgroundImage: `url("${CHAR_ASSETS[agent.id]}")` }} />
  </span>
);

export const AgentStatusCards: React.FC<{
  agents: Record<ProviderId, AgentSnapshot>;
  selectedAgent: ProviderId | null;
  onSelect: (id: ProviderId) => void;
}> = ({ agents, selectedAgent, onSelect }) => {
  const reduced = useReducedMotion();
  const longest = Math.max(1, ...AGENT_IDS.map((id) => agents[id].elapsed_ms));
  return (
    <nav className="agent-status-cards" aria-label="Council agents">
      {AGENT_IDS.map((id, index) => {
        const agent = agents[id];
        return (
          <motion.button key={id} type="button" className={`agent-status-card ${selectedAgent === id ? 'selected' : ''}`}
            initial={{ opacity: 0, y: reduced ? 0 : 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .28, delay: reduced ? 0 : index * .055 }}
            whileHover={reduced ? undefined : { y: -3 }} whileTap={reduced ? undefined : { scale: .99 }}
            style={{ '--agent-color': agent.color } as React.CSSProperties}
            onClick={() => onSelect(id)} aria-pressed={selectedAgent === id} data-testid={`agent-card-${id}`}>
            <AgentPortrait agent={agent} />
            <span className="agent-card-details">
              <span className="agent-card-title"><b>{agent.name}</b><span className="role-badge">{agent.role.toUpperCase()}</span></span>
              <span className="agent-card-state"><span className={`status-led state-${agent.animation}`} />{agent.status_badge.replaceAll('_', ' ')} · {AREA_BY_ROOM[agent.room].name}</span>
              <span className="agent-card-usage"><span>IN {agent.usage.input_tokens.toLocaleString()} / OUT {agent.usage.output_tokens.toLocaleString()} tok</span><b>{fmtMs(agent.elapsed_ms)}</b></span>
              <meter min={0} max={longest} value={Math.max(0, agent.elapsed_ms)}
                aria-label={`${agent.name} measured elapsed time relative to the longest agent duration`}
                title="Measured elapsed time relative to the longest agent duration; not task progress" />
            </span>
          </motion.button>
        );
      })}
    </nav>
  );
};

export const RoomInspector: React.FC<{
  room: OfficeRoom;
  agents: Record<ProviderId, AgentSnapshot>;
  onSelectAgent: (id: ProviderId) => void;
  onClose: () => void;
}> = ({ room, agents, onSelectAgent, onClose }) => {
  const zone = ROOM_ZONES[room];
  const occupants = AGENT_IDS.filter((id) => agents[id].room === room);
  return (
    <div className="panel room-inspector" data-selection-panel tabIndex={-1} aria-label={`${zone.title} inspector`}>
      <div className="panel-head"><h3>{zone.title}</h3><button type="button" onClick={onClose} aria-label="Close room inspector">✕</button></div>
      <p className="small muted">{zone.subtitle}</p>
      <table className="kv"><tbody>
        <tr><td>Room size</td><td>{zone.x2 - zone.x1 + 1} × {zone.y2 - zone.y1 + 1} tiles</td></tr>
        <tr><td>Stations</td><td>{Object.values(OFFICE_SEATS).filter((s) => s.room === room).length}</td></tr>
        <tr><td>Assigned agents</td><td>{occupants.length}</td></tr>
      </tbody></table>
      <div className="room-occupants">
        {occupants.map((id) => <button type="button" key={id} onClick={() => onSelectAgent(id)}>{agents[id].name} · {agents[id].animation}</button>)}
        {occupants.length === 0 && <p className="small muted">No agents assigned.</p>}
      </div>
    </div>
  );
};

export const TaskBoard: React.FC<{ columns: TaskBoardColumn[] }> = ({ columns }) => (
  <div className="task-board" data-testid="task-board">
    {columns.map((col) => (
      <div key={col.id} className={`task-col status-${col.status.toLowerCase()}`} data-testid={`task-col-${col.id}`}>
        <div className="task-col-title">{({ PROPOSING: 'Research', CRITIQUING: 'Discussion', SYNTHESIZING: 'Consensus', AWAITING_APPROVAL: 'Approval', EXECUTING: 'Coding', REVIEWING: 'Review & tests' } as Record<string, string>)[col.id] || col.title}</div>
        <span className="stage-status">{col.status.replaceAll('_', ' ').toLowerCase()}</span>
        {col.items.length > 0 && <details className="stage-details"><summary>{col.items.length} {col.items.length === 1 ? 'update' : 'updates'}</summary>{col.items.map((it, i) => (
          <div key={i} className={`task-item item-${it.status.toLowerCase()}`}>
            <b>{it.provider}</b>
            {it.attempt && it.attempt > 1 ? ` #${it.attempt}` : ''} · {it.status}
            {it.duration_ms ? ` · ${fmtMs(it.duration_ms)}` : ''}
            {it.error && <div className="err small">{it.error}</div>}
          </div>
        ))}</details>}
      </div>
    ))}
  </div>
);

export const AgentInspector: React.FC<{ agent: AgentSnapshot; onClose: () => void }> = ({ agent, onClose }) => (
  <div className="panel inspector" data-testid={`inspector-${agent.id}`} data-selection-panel tabIndex={-1} aria-label={`${agent.name} inspector`}>
    <div className="panel-head" style={{ borderColor: agent.color }}>
      <span className="eyebrow">AGENT INSPECTOR</span>
      <button type="button" onClick={onClose} aria-label="close" title="Back to workspace">
        ✕
      </button>
    </div>
    <div className="inspector-hero" style={{ '--agent-color': agent.color } as React.CSSProperties}>
      <AgentPortrait agent={agent} /><div><h3>{agent.name}</h3><span className="role-badge">{agent.role.toUpperCase()}</span><p className="small muted">{AREA_BY_ROOM[agent.room].name} area</p></div>
    </div>
    <table className="kv">
      <tbody>
        <tr><td>Role</td><td>{agent.role}</td></tr>
        <tr><td>Status</td><td data-testid="inspector-status">{agent.status_badge} ({agent.animation})</td></tr>
        <tr><td>Area</td><td>{AREA_BY_ROOM[agent.room].name}</td></tr>
        <tr><td>Station</td><td>{OFFICE_SEATS[agent.seat_id]?.label || agent.seat_id}</td></tr>
        <tr><td>Model</td><td>{agent.model} @ {agent.reasoning_effort}</td></tr>
        <tr><td>Current task</td><td>{agent.animation === 'failed' ? describeIssue(agent.current_task).detail : agent.current_task}</td></tr>
        <tr><td>Elapsed (measured)</td><td>{fmtMs(agent.elapsed_ms)}</td></tr>
        <tr>
          <td>Usage (measured)</td>
          <td>
            in {agent.usage.input_tokens} / out {agent.usage.output_tokens} tok
            {agent.usage.cost_usd != null ? ` · $${agent.usage.cost_usd}` : ' · cost n/a'}
          </td>
        </tr>
      </tbody>
    </table>
    <h4>Activity &amp; tool calls ({agent.tool_calls.length})</h4>
    <ul className="log">
      {agent.tool_calls.slice(-40).reverse().map((t) => (
        <li key={t.seq}>
          <span className="muted">{formatTime(t.timestamp)}</span> <b>{t.event_type}</b> — {t.summary}
        </li>
      ))}
    </ul>
    {agent.latest_output && (
      <details>
        <summary>Latest structured output</summary>
        <pre>{JSON.stringify(agent.latest_output, null, 2)}</pre>
      </details>
    )}
  </div>
);

export const MeetingDrawer: React.FC<{ meeting: MeetingData; onClose: () => void; hideHeader?: boolean; initialTab?: 'proposals' | 'critiques' | 'consensus' | 'disagreements' }> = ({ meeting, onClose, hideHeader, initialTab = 'proposals' }) => {
  const [tab, setTab] = useState<'proposals' | 'critiques' | 'consensus' | 'disagreements'>(initialTab);
  const labelFor = (agent: string) =>
    Object.entries(meeting.anonymized_map).find(([, a]) => a === agent)?.[0] || agent;
  const syn = meeting.synthesis;
  return (
    <div className="panel meeting" data-testid="meeting-drawer">
      {!hideHeader && <div className="panel-head">
        <h3>Council Meeting — chair: {meeting.chair}</h3>
        <button type="button" onClick={onClose} aria-label="close">✕</button>
      </div>}
      <div className="tabs">
        {(['proposals', 'critiques', 'consensus', 'disagreements'] as const).map((t) => (
          <button key={t} type="button" className={tab === t ? 'active' : ''} onClick={() => setTab(t)} data-testid={`tab-${t}`}>
            {{ proposals: 'Proposals', critiques: 'Peer discussion', consensus: 'Consensus', disagreements: 'Doubts' }[t]}
          </button>
        ))}
      </div>
      {tab === 'proposals' && (
        <div>
          {Object.keys(meeting.proposals).length === 0 && <p className="muted">No proposals yet.</p>}
          {Object.entries(meeting.proposals).map(([agent, p]) => (
            <div key={agent} className="card">
              <h4>{labelFor(agent)} <span className="muted">({agent})</span> · confidence {p.confidence}</h4>
              <p><b>Summary:</b> {p.summary}</p>
              <p><b>Recommendation:</b> {p.recommendation}</p>
              <p className="small"><b>Files:</b> {p.affected_files?.join(', ')}</p>
            </div>
          ))}
        </div>
      )}
      {tab === 'critiques' && (
        <div>
          {Object.keys(meeting.critiques).length === 0 && <p className="panel-empty">Peer discussion appears after independent research is complete.</p>}
          {Object.entries(meeting.critiques).map(([agent, c]) => (
            <div key={agent} className="card">
              <h4>Critique by {agent}</h4>
              <p>{c.overall_comparison}</p>
              <ul>
                {c.critiques?.map((x) => (
                  <li key={x.target_proposal}>
                    <b>{x.target_proposal}</b>: {x.verdict}
                    {x.flaws_and_blindspots?.length ? ` — flaws: ${x.flaws_and_blindspots.join('; ')}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {tab === 'consensus' && (
        <div>
          {!syn && <p className="muted">Synthesis not yet available.</p>}
          {syn && (
            <div className="card">
              <p><b>Executive summary:</b> {syn.executive_summary}</p>
              <p><b>Recommendation:</b> {syn.final_recommendation}</p>
              <h4>Consensus points</h4>
              <ul>{syn.consensus_points.map((c, i) => <li key={i}>{c}</li>)}</ul>
              <h4>Evidence ledger</h4>
              <ul>{syn.evidence_ledger.map((e) => <li key={e.id}>{e.id} [{e.verified ? 'verified' : 'unverified'}] {e.claim} — <i>{e.reference}</i></li>)}</ul>
              <h4>Assumptions</h4>
              <ul>{syn.assumptions_ledger.map((a) => <li key={a.id}>{a.id} {a.assumption} (check: {a.validation_check})</li>)}</ul>
              <p className="small"><b>Recommended writer:</b> {syn.recommended_writer} · <b>Authorized files:</b> {syn.authorized_files.join(', ')}</p>
            </div>
          )}
        </div>
      )}
      {tab === 'disagreements' && (
        <div data-testid="disagreements">
          {meeting.unresolved_disagreements.length === 0 && <p className="muted">No unresolved disagreements recorded.</p>}
          {meeting.unresolved_disagreements.map((d, i) => (
            <div key={i} className={`card ${d.blocking ? 'blocking' : ''}`}>
              <h4>{d.topic} {d.blocking && <span className="pill err">BLOCKING</span>}</h4>
              <ul>{d.positions.map((p, j) => <li key={j}><b>{p.agent_or_proposal}</b>: {p.stance}</li>)}</ul>
              <p className="small"><b>Recommended resolution:</b> {d.recommended_resolution}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export const ExecutionPanel: React.FC<{ execution: ExecutionData | null; onClose: () => void; hideHeader?: boolean }> = ({ execution, onClose, hideHeader }) => (
  <div className="panel execution" data-testid="execution-panel">
    {!hideHeader && <div className="panel-head">
      <h3>Coding &amp; Review Lab</h3>
      <button type="button" onClick={onClose} aria-label="close">✕</button>
    </div>}
    {!execution && <p className="muted">No execution data for this run.</p>}
    {execution && (
      <>
        <table className="kv">
          <tbody>
            <tr><td>Single writer</td><td>{execution.writer || '—'}</td></tr>
            <tr><td>Approved</td><td>{execution.approved ? 'yes' : 'no'}</td></tr>
            <tr><td>Branch</td><td>{execution.branch_name || '—'}</td></tr>
            <tr><td>Worktree</td><td className="small">{execution.worktree_path || '—'}</td></tr>
            <tr><td>Repairs</td><td>{execution.repair_attempts} / 2</td></tr>
            <tr><td>Authorized</td><td>{execution.authorized_files.join(', ') || '—'}</td></tr>
            <tr>
              <td>Tests</td>
              <td data-testid="test-status" className={execution.test_passed ? 'ok' : execution.test_passed === false ? 'err' : ''}>
                {execution.test_passed == null ? 'not run' : execution.test_passed ? 'PASSED' : 'FAILED'}
              </td>
            </tr>
          </tbody>
        </table>
        <h4>Peer reviews</h4>
        <ul>
          {execution.peer_reviews.map((r, i) => (
            <li key={i}>
              <b>{r.agent}</b> (round {r.attempt}): <span className={r.output.verdict === 'approve' ? 'ok' : 'err'}>{r.output.verdict}</span> — {r.output.summary}
            </li>
          ))}
        </ul>
        <h4>Git diff ({execution.changed_files.length} files)</h4>
        <pre className="diff" data-testid="git-diff">
          {(execution.git_diff || '(no diff)').split('\n').map((line, i) => (
            <span key={i} className={line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : ''}>
              {line}
              {'\n'}
            </span>
          ))}
        </pre>
        <h4>Test output</h4>
        <pre>{execution.test_output || '(none)'}</pre>
      </>
    )}
  </div>
);

export const ApprovalDialog: React.FC<{
  snapshot: OfficeSnapshot;
  busy: boolean;
  error: string | null;
  onApprove: (writer: ProviderId, createPr: boolean) => void;
  onCancel: () => void;
}> = ({ snapshot, busy, error, onApprove, onCancel }) => {
  const syn = snapshot.meeting.synthesis;
  const [writer, setWriter] = useState<ProviderId>((syn?.recommended_writer as ProviderId) || 'claude');
  const [pr, setPr] = useState(true);
  const blocking = snapshot.meeting.unresolved_disagreements.filter((d) => d.blocking);
  return (
    <motion.div className="modal-backdrop" data-testid="approval-dialog" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.div className="modal" initial={{ opacity: 0, y: 14, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: .98 }} transition={{ duration: .2 }}>
        <h3>Approve sandboxed execution?</h3>
        <p className="small">
          Run <code>{snapshot.run?.run_id}</code> will create an isolated Git worktree. Exactly one writer edits it; the
          other two review read-only. Nothing is merged or deployed.
        </p>
        {syn && (
          <>
            <p><b>Authorized files:</b> {syn.authorized_files.join(', ')}</p>
            <p><b>Forbidden:</b> {syn.forbidden_paths.join(', ') || '—'}</p>
            <ul className="small">{syn.acceptance_criteria.map((a, i) => <li key={i}>{a}</li>)}</ul>
          </>
        )}
        {blocking.length > 0 && (
          <p className="err">⚠ {blocking.length} blocking disagreement(s) remain unresolved. Review before approving.</p>
        )}
        <label>
          Single writer:{' '}
          <select value={writer} onChange={(e) => setWriter(e.target.value as ProviderId)} data-testid="writer-select">
            <option value="claude">Claude Code</option>
            <option value="codex">OpenAI Codex</option>
            <option value="agy">Google Antigravity</option>
          </select>
        </label>
        <label className="small">
          <input type="checkbox" checked={pr} onChange={(e) => setPr(e.target.checked)} /> Generate draft PR summary
        </label>
        {error && <p className="err" data-testid="approval-error">{error}</p>}
        <div className="modal-actions">
          <button type="button" onClick={onCancel} disabled={busy}>Close</button>
          <button type="button" className="primary" onClick={() => onApprove(writer, pr)} disabled={busy} data-testid="approve-btn">
            {busy ? 'Waiting for backend confirmation…' : 'Approve & execute'}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
};

export const ConversationPanel: React.FC<{ events: CouncilEventItem[] }> = ({ events }) => (
  <div className="panel conversation" data-testid="conversation-panel">
    <h3>Activity log <span className="pill">{events.length}</span></h3>
    {events.length === 0 && <p className="small muted">No activity yet. Start a task to see the council at work.</p>}
    <ul className="log">
      {events.slice(-80).reverse().map((e) => (
        <li key={e.seq} className={`agent-${e.agent}`}>
          <time className="muted">{formatTime(e.timestamp)}</time> <b>{e.agent}</b> <span className="pill">{e.stage}</span> <span>{e.message.split('\n')[0].slice(0, 240)}</span>
        </li>
      ))}
    </ul>
  </div>
);

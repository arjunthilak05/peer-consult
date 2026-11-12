import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { ApprovalDialog, ExecutionPanel, MeetingDrawer, TaskBoard } from '../panels';
import type { OfficeSnapshot } from '../types';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

function mount(el: React.ReactElement) {
  const div = document.createElement('div');
  document.body.appendChild(div);
  const root = createRoot(div);
  act(() => root.render(el));
  return { div, unmount: () => act(() => root.unmount()) };
}

const synthesis = {
  executive_summary: 'exec',
  final_recommendation: 'rec',
  consensus_points: ['c1'],
  rejected_ideas: [],
  unresolved_disagreements: [
    { topic: 'Caching', positions: [{ agent_or_proposal: 'Proposal A', stance: 'no cache' }], blocking: true, recommended_resolution: 'defer' },
  ],
  evidence_ledger: [{ id: 'E1', source: 'file_line', reference: 'app.py:1', claim: 'x', verified: true }],
  assumptions_ledger: [],
  recommended_writer: 'codex' as const,
  writer_rationale: '',
  authorized_files: ['app.py'],
  forbidden_paths: ['.env'],
  acceptance_criteria: ['returns 42'],
  verification_commands: [],
  steps: [],
  risks: [],
  confidence: 'high',
};

const snap = {
  run: { run_id: 'run-1', approved: false } as any,
  meeting: {
    chair: 'claude',
    anonymized_map: { 'Proposal A': 'claude' },
    proposals: {},
    critiques: {},
    synthesis,
    unresolved_disagreements: synthesis.unresolved_disagreements,
  },
} as unknown as OfficeSnapshot;

describe('UI panels', () => {
  it('ApprovalDialog defaults to recommended writer, warns on blocking disagreements, and calls onApprove', () => {
    const onApprove = vi.fn();
    const { div, unmount } = mount(
      <ApprovalDialog snapshot={snap} busy={false} error={null} onApprove={onApprove} onCancel={() => {}} />,
    );
    const select = div.querySelector('[data-testid="writer-select"]') as HTMLSelectElement;
    expect(select.value).toBe('codex');
    expect(div.textContent).toContain('blocking disagreement');
    act(() => (div.querySelector('[data-testid="approve-btn"]') as HTMLButtonElement).click());
    expect(onApprove).toHaveBeenCalledWith('codex', true);
    unmount();
  });

  it('ApprovalDialog disables approval while awaiting backend confirmation', () => {
    const { div, unmount } = mount(
      <ApprovalDialog snapshot={snap} busy={true} error={null} onApprove={() => {}} onCancel={() => {}} />,
    );
    const btn = div.querySelector('[data-testid="approve-btn"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Waiting for backend confirmation');
    unmount();
  });

  it('MeetingDrawer shows unresolved disagreements tab', () => {
    const { div, unmount } = mount(<MeetingDrawer meeting={snap.meeting} onClose={() => {}} />);
    act(() => (div.querySelector('[data-testid="tab-disagreements"]') as HTMLButtonElement).click());
    expect(div.querySelector('[data-testid="disagreements"]')!.textContent).toContain('Caching');
    unmount();
  });

  it('TaskBoard and ExecutionPanel render backend data', () => {
    const { div, unmount } = mount(
      <>
        <TaskBoard columns={[{ id: 'PROPOSING', title: '1. Proposals', status: 'COMPLETED', items: [{ stage: 'proposal', provider: 'claude', status: 'COMPLETED', duration_ms: 1500, error: null }] }]} />
        <ExecutionPanel
          execution={{
            writer: 'claude', approved: true, worktree_path: '/wt', branch_name: 'council/run-1', repair_attempts: 1,
            authorized_files: ['app.py'], forbidden_paths: [], acceptance_criteria: [], changed_files: ['app.py'],
            git_diff: '+return 42\n-return 1', test_passed: true, test_output: '1 passed', peer_reviews: [],
          }}
          onClose={() => {}}
        />
      </>,
    );
    expect(div.querySelector('[data-testid="task-col-PROPOSING"]')!.textContent).toContain('claude');
    expect(div.querySelector('[data-testid="test-status"]')!.textContent).toBe('PASSED');
    expect(div.querySelector('[data-testid="git-diff"] .add')!.textContent).toContain('+return 42');
    unmount();
  });
});

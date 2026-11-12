import type { OfficeRoom, OfficeSnapshot } from '../types';

export const AREAS: Array<{ room: OfficeRoom; name: string; purpose: string; color: string; number: string }> = [
  { room: 'desks', name: 'Research', purpose: 'Evidence & independent proposals', color: '#72b6cc', number: '01' },
  { room: 'meeting_room', name: 'Discussion', purpose: 'Compare ideas & build consensus', color: '#dfb36e', number: '02' },
  { room: 'review_room', name: 'Doubts', purpose: 'Questions, challenges & review', color: '#b8a2e2', number: '03' },
  { room: 'coding_room', name: 'Coding', purpose: 'Implementation, diffs & tests', color: '#73c5a0', number: '04' },
];
export const AREA_BY_ROOM = Object.fromEntries(AREAS.map(area => [area.room, area])) as Record<OfficeRoom, (typeof AREAS)[number]>;

export function workflowArea(snap: OfficeSnapshot): OfficeRoom {
  const state = snap.run?.state;
  if (state === 'FAILED') return 'review_room';
  if (['WORKTREE_READY', 'EXECUTING', 'REPAIRING'].includes(state || '')) return 'coding_room';
  if (['VERIFYING', 'REVIEWING'].includes(state || '')) return 'review_room';
  if (['CRITIQUING', 'SYNTHESIZING', 'AWAITING_APPROVAL', 'COMPLETED'].includes(state || '')) return 'meeting_room';
  return 'desks';
}

export function stateLabel(state: string): string {
  const labels: Record<string, string> = {
    CREATED: 'Starting', CONTEXT_BUILT: 'Preparing research', PROPOSING: 'Researching', CRITIQUING: 'Discussing',
    SYNTHESIZING: 'Building consensus', AWAITING_APPROVAL: 'Ready for your approval', WORKTREE_READY: 'Preparing workspace',
    EXECUTING: 'Coding', VERIFYING: 'Running tests', REVIEWING: 'Reviewing', REPAIRING: 'Making repairs',
    COMPLETED: 'Completed', FAILED: 'Needs attention', CANCELLED: 'Paused',
  };
  return labels[state] || state.replaceAll('_', ' ').toLowerCase();
}

export function describeIssue(message: string): { title: string; detail: string } {
  if (/quota|resource_exhausted|billing|credit balance/i.test(message)) {
    const reset = message.match(/Resets in ([^\n.]+)/i)?.[1];
    return { title: 'Provider quota exhausted', detail: `This provider has reached its account limit.${reset ? ` The provider reported a reset in ${reset}.` : ''} Resume after the limit resets or the account is updated.` };
  }
  if (/not found on PATH|configured .+ command not found/i.test(message)) return {
    title: 'Provider executable unavailable', detail: 'The server cannot find this provider. Check its command path in the peer-consult configuration, then restart the office.',
  };
  if (/auth|sign.?in|log.?in|unauthorized|credentials/i.test(message)) return {
    title: 'Provider sign-in required', detail: 'Sign in to the provider CLI on this computer, then resume the run.',
  };
  if (/timeout|timed out/i.test(message)) return { title: 'Provider timed out', detail: 'The provider did not finish in time. Completed work is saved; you can resume the run.' };
  return { title: 'This step needs attention', detail: message.split('\n')[0].slice(0, 260) || 'Review the details before resuming.' };
}

export const formatTime = (value: string) => {
  const time = new Date(value);
  return Number.isNaN(time.valueOf()) ? '—' : time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

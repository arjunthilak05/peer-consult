import { describe, expect, it } from 'vitest';
import {
  applyEventReplayStep,
  Direction,
  enforceSingleWriterSeat,
  findTilePath,
  OFFICE_FURNITURE,
  OFFICE_SEATS,
  resolveSpriteFrame,
} from '../office/stateMachine';
import type { AgentSnapshot, CouncilEventItem, ProviderId } from '../types';

function agent(id: ProviderId, overrides: Partial<AgentSnapshot> = {}): AgentSnapshot {
  return {
    id,
    name: id,
    color: '#fff',
    palette: 0,
    model: 'm',
    reasoning_effort: 'high',
    role: 'adviser',
    room: 'desks',
    seat_id: `desk-${id}`,
    animation: 'idle',
    current_task: '',
    tool_calls: [],
    elapsed_ms: 0,
    usage: { input_tokens: 0, output_tokens: 0, cost_usd: null, duration_ms: 0 },
    latest_output: null,
    status_badge: 'IDLE',
    ...overrides,
  };
}

const base = () => ({ claude: agent('claude'), codex: agent('codex'), agy: agent('agy') });

describe('resolveSpriteFrame (deterministic animation mapping)', () => {
  it('maps all 9 states deterministically for the same tick', () => {
    const states = ['idle', 'working', 'thinking', 'reading', 'coding', 'reviewing', 'waiting', 'failed', 'completed'] as const;
    for (const s of states) {
      expect(resolveSpriteFrame(s, false, Direction.UP, 42)).toEqual(resolveSpriteFrame(s, false, Direction.UP, 42));
    }
  });
  it('uses typing frames 3/4 for coding and reading frames 5/6 for reviewing', () => {
    expect([3, 4]).toContain(resolveSpriteFrame('coding', false, Direction.UP, 0).frameCol);
    expect([5, 6]).toContain(resolveSpriteFrame('reviewing', false, Direction.UP, 0).frameCol);
    expect(resolveSpriteFrame('coding', false, Direction.UP, 0).badge).toBe('coding');
  });
  it('uses walk cycle while moving and flips for LEFT', () => {
    const f = resolveSpriteFrame('coding', true, Direction.LEFT, 0);
    expect([0, 1, 2]).toContain(f.frameCol);
    expect(f.flipX).toBe(true);
    expect(f.badge).toBeNull();
  });
  it('failed/completed face forward with badges', () => {
    expect(resolveSpriteFrame('failed', false, Direction.UP, 0)).toMatchObject({ frameRow: 0, badge: 'failed' });
    expect(resolveSpriteFrame('completed', false, Direction.LEFT, 0)).toMatchObject({ frameRow: 0, badge: 'completed', flipX: false });
  });
});

describe('findTilePath', () => {
  it('routes between every station without walking through desks or tables', () => {
    const blocked = new Set<string>();
    OFFICE_FURNITURE.filter(f => !f.id.startsWith('chair')).forEach(f => {
      for (let col = f.col; col < f.col + Math.ceil(f.widthPx / 16); col++) {
        for (let row = f.row; row < f.row + Math.ceil(f.heightPx / 16); row++) blocked.add(`${col},${row}`);
      }
    });
    for (const from of Object.values(OFFICE_SEATS)) for (const to of Object.values(OFFICE_SEATS)) {
      if (from.id === to.id) continue;
      const path = findTilePath(from.col, from.row, to.col, to.row);
      expect(path.length).toBeGreaterThan(0);
      expect(path.at(-1)).toEqual({ col: to.col, row: to.row });
      expect(path.slice(0, -1).every(p => !blocked.has(`${p.col},${p.row}`))).toBe(true);
    }
  });
  it('returns empty path when already at target', () => {
    expect(findTilePath(3, 4, 3, 4)).toEqual([]);
  });
  it('routes between rooms via hallway row 8 and ends at target', () => {
    const p = findTilePath(3, 4, 17, 13);
    expect(p.some((s) => s.row === 8)).toBe(true);
    expect(p[p.length - 1]).toEqual({ col: 17, row: 13 });
    for (let i = 1; i < p.length; i++) {
      expect(Math.abs(p[i].col - p[i - 1].col) + Math.abs(p[i].row - p[i - 1].row)).toBe(1);
    }
  });
});

describe('enforceSingleWriterSeat', () => {
  it('never allows two agents in the coding room', () => {
    const a = base();
    a.claude = agent('claude', { room: 'coding_room', seat_id: 'coding-writer' });
    a.codex = agent('codex', { room: 'coding_room', seat_id: 'coding-writer' });
    const out = enforceSingleWriterSeat(a, 'codex');
    const coders = (Object.keys(out) as ProviderId[]).filter((k) => out[k].room === 'coding_room');
    expect(coders).toEqual(['codex']);
    expect(out.claude.room).toBe('review_room');
  });
});

describe('applyEventReplayStep', () => {
  it('moves the actor into the event room with the event animation', () => {
    const ev: CouncilEventItem = {
      seq: 1, event_id: 'e', run_id: 'r', timestamp: '2026-01-01T00:00:00Z', stage: 'writer',
      agent: 'agy', event_type: 'writer.started', animation_state: 'coding', room: 'coding_room',
      message: 'agy coding', payload: {},
    };
    const out = applyEventReplayStep(base(), ev);
    expect(out.agy.room).toBe('coding_room');
    expect(out.agy.seat_id).toBe('coding-writer');
    expect(out.agy.animation).toBe('coding');
    expect(out.claude.room).toBe('desks');
  });
});

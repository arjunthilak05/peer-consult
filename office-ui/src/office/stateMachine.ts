import type { AgentAnimation, AgentSnapshot, CouncilEventItem, OfficeRoom, ProviderId } from '../types';

export const OFFICE_COLS = 26;
export const OFFICE_ROWS = 17;
export const TILE_SIZE = 16;

export const Direction = {
  DOWN: 0,
  UP: 1,
  RIGHT: 2,
  LEFT: 3,
} as const;
export type Direction = (typeof Direction)[keyof typeof Direction];

export interface SeatCoord {
  id: string;
  room: OfficeRoom;
  col: number;
  row: number;
  facing: Direction;
  label: string;
}

export interface RoomZone {
  id: OfficeRoom;
  title: string;
  subtitle: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  floorAsset: string;
  accentColor: string;
}

export interface FurniturePlacement {
  id: string;
  assetPath: string;
  col: number;
  row: number;
  widthPx: number;
  heightPx: number;
  room: OfficeRoom;
  isAnimatedPc?: boolean;
}

export const ROOM_ZONES: Record<OfficeRoom, RoomZone> = {
  desks: {
    id: 'desks',
    title: 'RESEARCH',
    subtitle: 'Evidence · independent proposals',
    x1: 1,
    y1: 1,
    x2: 11,
    y2: 7,
    floorAsset: 'assets/floors/floor_1.png',
    accentColor: '#60a5fa',
  },
  meeting_room: {
    id: 'meeting_room',
    title: 'DISCUSSION',
    subtitle: 'Compare ideas · reach consensus',
    x1: 14,
    y1: 1,
    x2: 24,
    y2: 7,
    floorAsset: 'assets/floors/floor_3.png',
    accentColor: '#f59e0b',
  },
  coding_room: {
    id: 'coding_room',
    title: 'CODING',
    subtitle: 'One writer · approved implementation',
    x1: 1,
    y1: 10,
    x2: 11,
    y2: 15,
    floorAsset: 'assets/floors/floor_5.png',
    accentColor: '#10b981',
  },
  review_room: {
    id: 'review_room',
    title: 'DOUBTS & REVIEW',
    subtitle: 'Questions · challenges · verification',
    x1: 14,
    y1: 10,
    x2: 24,
    y2: 15,
    floorAsset: 'assets/floors/floor_7.png',
    accentColor: '#a855f7',
  },
};

export const OFFICE_SEATS: Record<string, SeatCoord> = {
  'desk-claude': { id: 'desk-claude', room: 'desks', col: 3, row: 4, facing: Direction.UP, label: 'Claude Desk' },
  'desk-codex': { id: 'desk-codex', room: 'desks', col: 6, row: 4, facing: Direction.UP, label: 'Codex Desk' },
  'desk-agy': { id: 'desk-agy', room: 'desks', col: 9, row: 4, facing: Direction.UP, label: 'Antigravity Desk' },
  'meeting-claude': { id: 'meeting-claude', room: 'meeting_room', col: 17, row: 3, facing: Direction.DOWN, label: 'Discussion Seat A' },
  'meeting-codex': { id: 'meeting-codex', room: 'meeting_room', col: 19, row: 6, facing: Direction.UP, label: 'Discussion Seat B' },
  'meeting-agy': { id: 'meeting-agy', room: 'meeting_room', col: 21, row: 3, facing: Direction.DOWN, label: 'Discussion Seat C' },
  'coding-writer': { id: 'coding-writer', room: 'coding_room', col: 6, row: 13, facing: Direction.UP, label: 'Single-Writer Station' },
  'review-1': { id: 'review-1', room: 'review_room', col: 17, row: 13, facing: Direction.UP, label: 'Reviewer Station 1' },
  'review-2': { id: 'review-2', room: 'review_room', col: 21, row: 13, facing: Direction.UP, label: 'Reviewer Station 2' },
  'doubts-claude': { id: 'doubts-claude', room: 'review_room', col: 16, row: 13, facing: Direction.DOWN, label: 'Claude clarification station' },
  'doubts-codex': { id: 'doubts-codex', room: 'review_room', col: 19, row: 13, facing: Direction.DOWN, label: 'Codex clarification station' },
  'doubts-agy': { id: 'doubts-agy', room: 'review_room', col: 22, row: 13, facing: Direction.DOWN, label: 'Antigravity clarification station' },
};

export const OFFICE_FURNITURE: FurniturePlacement[] = [
  // Room 1: Adviser Desks
  { id: 'desk-1', assetPath: 'assets/furniture/DESK/DESK_FRONT.png', col: 2, row: 2, widthPx: 48, heightPx: 32, room: 'desks' },
  { id: 'pc-1', assetPath: 'assets/furniture/PC/PC_FRONT_ON_1.png', col: 3, row: 2, widthPx: 16, heightPx: 32, room: 'desks', isAnimatedPc: true },
  { id: 'chair-1', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK.png', col: 3, row: 4, widthPx: 16, heightPx: 16, room: 'desks' },

  { id: 'desk-2', assetPath: 'assets/furniture/DESK/DESK_FRONT.png', col: 5, row: 2, widthPx: 48, heightPx: 32, room: 'desks' },
  { id: 'pc-2', assetPath: 'assets/furniture/PC/PC_FRONT_ON_2.png', col: 6, row: 2, widthPx: 16, heightPx: 32, room: 'desks', isAnimatedPc: true },
  { id: 'chair-2', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK.png', col: 6, row: 4, widthPx: 16, heightPx: 16, room: 'desks' },

  { id: 'desk-3', assetPath: 'assets/furniture/DESK/DESK_FRONT.png', col: 8, row: 2, widthPx: 48, heightPx: 32, room: 'desks' },
  { id: 'pc-3', assetPath: 'assets/furniture/PC/PC_FRONT_ON_3.png', col: 9, row: 2, widthPx: 16, heightPx: 32, room: 'desks', isAnimatedPc: true },
  { id: 'chair-3', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK.png', col: 9, row: 4, widthPx: 16, heightPx: 16, room: 'desks' },

  { id: 'bookshelf-desks', assetPath: 'assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', col: 1, row: 1, widthPx: 32, heightPx: 32, room: 'desks' },
  { id: 'plant-desks', assetPath: 'assets/furniture/PLANT/PLANT.png', col: 11, row: 2, widthPx: 16, heightPx: 32, room: 'desks' },
  { id: 'coffee-desks', assetPath: 'assets/furniture/COFFEE/COFFEE.png', col: 1, row: 6, widthPx: 16, heightPx: 16, room: 'desks' },

  // Room 2: Council Meeting Room
  { id: 'whiteboard-meeting', assetPath: 'assets/furniture/WHITEBOARD/WHITEBOARD.png', col: 18, row: 1, widthPx: 32, heightPx: 32, room: 'meeting_room' },
  { id: 'clock-meeting', assetPath: 'assets/furniture/CLOCK/CLOCK.png', col: 15, row: 1, widthPx: 16, heightPx: 32, room: 'meeting_room' },
  { id: 'table-meeting-1', assetPath: 'assets/furniture/TABLE_FRONT/TABLE_FRONT.png', col: 17, row: 4, widthPx: 48, heightPx: 32, room: 'meeting_room' },
  { id: 'table-meeting-2', assetPath: 'assets/furniture/COFFEE_TABLE/COFFEE_TABLE.png', col: 20, row: 4, widthPx: 32, heightPx: 32, room: 'meeting_room' },
  { id: 'chair-m1', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_FRONT.png', col: 17, row: 3, widthPx: 16, heightPx: 16, room: 'meeting_room' },
  { id: 'chair-m2', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK.png', col: 19, row: 6, widthPx: 16, heightPx: 16, room: 'meeting_room' },
  { id: 'chair-m3', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_FRONT.png', col: 21, row: 3, widthPx: 16, heightPx: 16, room: 'meeting_room' },
  { id: 'plant-meeting', assetPath: 'assets/furniture/LARGE_PLANT/LARGE_PLANT.png', col: 23, row: 2, widthPx: 16, heightPx: 32, room: 'meeting_room' },

  // Room 3: Single-Writer Coding Room
  { id: 'desk-coding', assetPath: 'assets/furniture/DESK/DESK_FRONT.png', col: 5, row: 11, widthPx: 48, heightPx: 32, room: 'coding_room' },
  { id: 'pc-coding', assetPath: 'assets/furniture/PC/PC_FRONT_ON_1.png', col: 6, row: 11, widthPx: 16, heightPx: 32, room: 'coding_room', isAnimatedPc: true },
  { id: 'chair-coding', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK.png', col: 6, row: 13, widthPx: 16, heightPx: 16, room: 'coding_room' },
  { id: 'bookshelf-coding', assetPath: 'assets/furniture/BOOKSHELF/BOOKSHELF.png', col: 2, row: 10, widthPx: 16, heightPx: 32, room: 'coding_room' },
  { id: 'cactus-coding', assetPath: 'assets/furniture/CACTUS/CACTUS.png', col: 9, row: 11, widthPx: 16, heightPx: 32, room: 'coding_room' },
  { id: 'painting-coding', assetPath: 'assets/furniture/SMALL_PAINTING/SMALL_PAINTING.png', col: 4, row: 10, widthPx: 16, heightPx: 32, room: 'coding_room' },

  // Room 4: Peer Review Room
  { id: 'desk-rev-1', assetPath: 'assets/furniture/DESK/DESK_FRONT.png', col: 16, row: 11, widthPx: 48, heightPx: 32, room: 'review_room' },
  { id: 'pc-rev-1', assetPath: 'assets/furniture/PC/PC_FRONT_ON_2.png', col: 17, row: 11, widthPx: 16, heightPx: 32, room: 'review_room', isAnimatedPc: true },
  { id: 'chair-rev-1', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK.png', col: 17, row: 13, widthPx: 16, heightPx: 16, room: 'review_room' },

  { id: 'desk-rev-2', assetPath: 'assets/furniture/DESK/DESK_FRONT.png', col: 20, row: 11, widthPx: 48, heightPx: 32, room: 'review_room' },
  { id: 'pc-rev-2', assetPath: 'assets/furniture/PC/PC_FRONT_ON_3.png', col: 21, row: 11, widthPx: 16, heightPx: 32, room: 'review_room', isAnimatedPc: true },
  { id: 'chair-rev-2', assetPath: 'assets/furniture/CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK.png', col: 21, row: 13, widthPx: 16, heightPx: 16, room: 'review_room' },

  { id: 'whiteboard-rev', assetPath: 'assets/furniture/WHITEBOARD/WHITEBOARD.png', col: 14, row: 10, widthPx: 32, heightPx: 32, room: 'review_room' },
  { id: 'sofa-rev', assetPath: 'assets/furniture/SOFA/SOFA_FRONT.png', col: 23, row: 13, widthPx: 32, heightPx: 16, room: 'review_room' },
];

export interface SpriteFrameSelection {
  /** Column index in char_N.png (0..6, each 16px wide) */
  frameCol: number;
  /** Row index in char_N.png (0 = DOWN, 1 = UP, 2 = RIGHT/LEFT, each 32px tall) */
  frameRow: number;
  /** True when facing LEFT (flips row 2 horizontally) */
  flipX: boolean;
  /** Bubble badge to draw above head */
  badge: 'thinking' | 'waiting' | 'coding' | 'reviewing' | 'completed' | 'failed' | null;
}

/**
 * Deterministically map an agent's current animation state, movement status,
 * direction, and tick index to the exact 16x32 frame in `pixel-agents` char_N.png.
 */
export function resolveSpriteFrame(
  animation: AgentAnimation,
  isMoving: boolean,
  dir: Direction,
  tick: number,
): SpriteFrameSelection {
  const frameRow = dir === Direction.DOWN ? 0 : dir === Direction.UP ? 1 : 2;
  const flipX = dir === Direction.LEFT;

  if (isMoving) {
    const walkCycle = [0, 1, 2, 1];
    return {
      frameCol: walkCycle[Math.floor(tick / 6) % walkCycle.length],
      frameRow,
      flipX,
      badge: null,
    };
  }

  switch (animation) {
    case 'working':
    case 'coding':
      return {
        frameCol: 3 + (Math.floor(tick / 10) % 2), // typing frames 3 & 4
        frameRow,
        flipX,
        badge: animation === 'coding' ? 'coding' : null,
      };
    case 'reading':
    case 'reviewing':
      return {
        frameCol: 5 + (Math.floor(tick / 14) % 2), // reading frames 5 & 6
        frameRow,
        flipX,
        badge: animation === 'reviewing' ? 'reviewing' : null,
      };
    case 'thinking':
      return {
        frameCol: Math.floor(tick / 20) % 2 === 0 ? 1 : 5,
        frameRow,
        flipX,
        badge: 'thinking',
      };
    case 'waiting':
      return {
        frameCol: 1,
        frameRow,
        flipX,
        badge: 'waiting',
      };
    case 'completed':
      return {
        frameCol: 1,
        frameRow: 0, // face front proudly
        flipX: false,
        badge: 'completed',
      };
    case 'failed':
      return {
        frameCol: 1,
        frameRow: 0,
        flipX: false,
        badge: 'failed',
      };
    case 'idle':
    default:
      return {
        frameCol: 1,
        frameRow,
        flipX,
        badge: null,
      };
  }
}

/**
 * Deterministic BFS around furniture, via the central corridor for room changes.
 */
export function findTilePath(
  startCol: number,
  startRow: number,
  endCol: number,
  endRow: number,
): Array<{ col: number; row: number }> {
  if (startCol === endCol && startRow === endRow) {
    return [];
  }

  const waypoints: Array<{ col: number; row: number }> = [];
  const sameRoomVert = (startRow <= 7 && endRow <= 7) || (startRow >= 10 && endRow >= 10);
  const sameRoomHoriz = (startCol <= 11 && endCol <= 11) || (startCol >= 14 && endCol >= 14);

  if (!sameRoomVert || !sameRoomHoriz) {
    // Route via hallway row 8 and central intersection col 12
    waypoints.push({ col: startCol, row: 8 });
    waypoints.push({ col: endCol, row: 8 });
  }
  waypoints.push({ col: endCol, row: endRow });

  const blocked = new Set<string>();
  OFFICE_FURNITURE.filter(f => !f.id.startsWith('chair')).forEach(f => {
    for (let c = f.col; c < f.col + Math.ceil(f.widthPx / TILE_SIZE); c++) {
      for (let r = f.row; r < f.row + Math.ceil(f.heightPx / TILE_SIZE); r++) blocked.add(`${c},${r}`);
    }
  });
  const path: Array<{ col: number; row: number }> = [];
  let from = { col: startCol, row: startRow };
  for (const target of waypoints) {
    const queue = [from];
    const key = (c: number, r: number) => `${c},${r}`;
    const visited = new Set([key(from.col, from.row)]);
    const parent = new Map<string, { col: number; row: number }>();
    let reached = false;
    for (let head = 0; head < queue.length; head++) {
      const current = queue[head];
      if (current.col === target.col && current.row === target.row) { reached = true; break; }
      for (const [dc, dr] of [[0, 1], [1, 0], [-1, 0], [0, -1]]) {
        const col = current.col + dc, row = current.row + dr;
        const nextKey = key(col, row);
        const inFloor = row === 8 || row === 9 || col === 12 || col === 13
          || Object.values(ROOM_ZONES).some(z => col >= z.x1 && col <= z.x2 && row >= z.y1 && row <= z.y2);
        if (col < 1 || col >= OFFICE_COLS - 1 || row < 1 || row >= OFFICE_ROWS - 1 || !inFloor || visited.has(nextKey)) continue;
        if (blocked.has(nextKey) && (col !== endCol || row !== endRow)) continue;
        visited.add(nextKey); parent.set(nextKey, current); queue.push({ col, row });
      }
    }
    if (!reached) return [];
    const segment: typeof path = [];
    let step = target;
    while (step.col !== from.col || step.row !== from.row) {
      segment.push(step);
      step = parent.get(key(step.col, step.row))!;
    }
    path.push(...segment.reverse());
    from = target;
  }
  return path;
}

/**
 * UI safety invariant: ensure at most ONE agent is ever assigned to the Coding Room (`coding-writer`).
 * If multiple agents ever claim `coding_room`, only the designated single writer keeps `coding-writer`
 * and any other agent is redirected to `review_room`.
 */
export function enforceSingleWriterSeat(
  agents: Record<ProviderId, AgentSnapshot>,
  designatedWriter: ProviderId | null,
): Record<ProviderId, AgentSnapshot> {
  const copy: Record<ProviderId, AgentSnapshot> = {
    claude: { ...agents.claude },
    codex: { ...agents.codex },
    agy: { ...agents.agy },
  };
  const inCoding = (Object.keys(copy) as ProviderId[]).filter((id) => copy[id].room === 'coding_room');
  if (inCoding.length <= 1) {
    return copy;
  }
  const allowedWriter = designatedWriter && inCoding.includes(designatedWriter) ? designatedWriter : inCoding[0];
  let revIdx = 1;
  for (const id of inCoding) {
    if (id !== allowedWriter) {
      copy[id] = {
        ...copy[id],
        room: 'review_room',
        seat_id: `review-${revIdx}`,
        role: 'reviewer',
        animation: 'waiting',
      };
      revIdx = Math.min(2, revIdx + 1);
    }
  }
  return copy;
}

/**
 * Deterministically apply a recorded CouncilEventItem onto the current agent snapshot map
 * for visual Event Replay without making any model calls.
 */
export function applyEventReplayStep(
  agents: Record<ProviderId, AgentSnapshot>,
  event: CouncilEventItem,
): Record<ProviderId, AgentSnapshot> {
  const next: Record<ProviderId, AgentSnapshot> = {
    claude: { ...agents.claude },
    codex: { ...agents.codex },
    agy: { ...agents.agy },
  };

  const seatForRoom = (id: ProviderId, room: OfficeRoom): string => {
    if (room === 'desks') return `desk-${id}`;
    if (room === 'meeting_room') return `meeting-${id}`;
    if (room === 'coding_room') return 'coding-writer';
    return id === 'codex' ? 'review-1' : 'review-2';
  };

  const actor = event.agent as ProviderId;
  if (actor in next) {
    next[actor] = {
      ...next[actor],
      room: event.room,
      seat_id: seatForRoom(actor, event.room),
      animation: event.animation_state,
      current_task: event.message || `${event.stage}: ${event.event_type}`,
      status_badge: event.animation_state.toUpperCase(),
    };
  } else if (event.agent === 'orchestrator') {
    for (const id of ['claude', 'codex', 'agy'] as ProviderId[]) {
      if (event.stage === 'critique' || event.stage === 'awaiting_approval') {
        next[id] = {
          ...next[id],
          room: 'meeting_room',
          seat_id: `meeting-${id}`,
          animation: event.animation_state,
          current_task: event.message,
          status_badge: event.animation_state.toUpperCase(),
        };
      } else if (event.stage === 'completed') {
        next[id] = {
          ...next[id],
          animation: 'completed',
          current_task: event.message,
          status_badge: 'COMPLETED',
        };
      }
    }
  }
  return enforceSingleWriterSeat(next, null);
}

import type { ProviderId } from '../types';

export const AGENT_IDS: ProviderId[] = ['claude', 'codex', 'agy'];
export const CHAR_ASSETS: Record<ProviderId, string> = {
  claude: 'assets/generated/characters/char_0.png',
  codex: 'assets/generated/characters/char_1.png',
  agy: 'assets/generated/characters/char_2.png',
};
export const AGENT_COLORS: Record<ProviderId, string> = {
  claude: '#D97757', codex: '#10A37F', agy: '#06B6D4',
};

// Eight logical pixels, drawn at 2x, form a native 16x16 icon. No system emoji fonts.
const ICONS = {
  thinking: ['..####..', '.######.', '.######.', '..####..', '...##...', '..####..', '...##...', '........'],
  coding: ['....##..', '...##...', '..####..', '.####...', '...##...', '..##....', '.##.....', '........'],
  shield: ['.######.', '.######.', '.######.', '..####..', '..####..', '...##...', '........', '........'],
  reviewing: ['..###...', '.#...#..', '#.....#.', '#.....#.', '.#...#..', '..####..', '.....##.', '......##'],
  waiting: ['..#.#...', '...#....', '.#####..', '.#...###', '.#...#.#', '.#####..', '........', '.######.'],
  completed: ['........', '......#.', '.....##.', '.#..##..', '.####...', '..##....', '........', '........'],
  failed: ['........', '.##..##.', '..####..', '...##...', '..####..', '.##..##.', '........', '........'],
} as const;
export type EmoteIcon = keyof typeof ICONS;
export const EMOTE_ASSETS: Record<EmoteIcon, string> = {
  thinking: 'assets/generated/emotes/idea.png', coding: 'assets/generated/emotes/spark.png',
  shield: 'assets/generated/emotes/shield.png', reviewing: 'assets/generated/emotes/inspection.png',
  waiting: 'assets/generated/emotes/coffee.png', completed: 'assets/generated/emotes/success.png',
  failed: 'assets/generated/emotes/error.png',
};
export const FURNITURE_ASSETS: Record<string, string> = {
  'assets/furniture/WHITEBOARD/WHITEBOARD.png': 'assets/generated/furniture/WHITEBOARD/WHITEBOARD.png',
  'assets/furniture/COFFEE/COFFEE.png': 'assets/generated/furniture/COFFEE/COFFEE.png',
};
export function drawPixelIcon(ctx: CanvasRenderingContext2D, icon: EmoteIcon, x: number, y: number, scale: number) {
  const colors: Record<EmoteIcon, string> = {
    thinking: '#fbbf24', coding: '#10a37f', shield: '#4285f4', reviewing: '#6366f1',
    waiting: '#995e3a', completed: '#16a34a', failed: '#dc2626',
  };
  ctx.fillStyle = colors[icon];
  ICONS[icon].forEach((row, py) => [...row].forEach((pixel, px) => {
    if (pixel === '#') ctx.fillRect(x + px * 2 * scale, y + py * 2 * scale, 2 * scale, 2 * scale);
  }));
}

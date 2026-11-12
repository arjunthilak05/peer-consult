import React, { useEffect, useRef } from 'react';
import type { AgentSnapshot, OfficeRoom, ProviderId } from '../types';
import { AGENT_COLORS, AGENT_IDS, CHAR_ASSETS, EMOTE_ASSETS, FURNITURE_ASSETS, drawPixelIcon } from './visuals';
import {
  Direction,
  enforceSingleWriterSeat,
  findTilePath,
  OFFICE_COLS,
  OFFICE_FURNITURE,
  OFFICE_ROWS,
  OFFICE_SEATS,
  resolveSpriteFrame,
  ROOM_ZONES,
  TILE_SIZE,
} from './stateMachine';

interface PixelOfficeCanvasProps {
  agents: Record<ProviderId, AgentSnapshot>;
  selectedAgentId: ProviderId | null;
  selectedRoom: OfficeRoom | null;
  designatedWriter: ProviderId | null;
  onSelectAgent: (id: ProviderId) => void;
  onSelectRoom: (room: OfficeRoom) => void;
}

interface LiveCharacterSpriteState {
  id: ProviderId;
  col: number;
  row: number;
  x: number;
  y: number;
  dir: Direction;
  targetSeatId: string;
  path: Array<{ col: number; row: number }>;
  moveProgress: number;
}

const SCALE = 3; // 16px tile * 3 = 48px per tile -> 1248x816 canvas
const CANVAS_W = OFFICE_COLS * TILE_SIZE * SCALE;
const CANVAS_H = OFFICE_ROWS * TILE_SIZE * SCALE;

const PC_FRAME_PATHS = [
  'assets/furniture/PC/PC_FRONT_ON_1.png',
  'assets/furniture/PC/PC_FRONT_ON_2.png',
  'assets/furniture/PC/PC_FRONT_ON_3.png',
];

export const PixelOfficeCanvas: React.FC<PixelOfficeCanvasProps> = ({
  agents,
  selectedAgentId,
  selectedRoom,
  designatedWriter,
  onSelectAgent,
  onSelectRoom,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imagesRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const charsRef = useRef<Record<ProviderId, LiveCharacterSpriteState>>({
    claude: {
      id: 'claude',
      col: OFFICE_SEATS['desk-claude'].col,
      row: OFFICE_SEATS['desk-claude'].row,
      x: OFFICE_SEATS['desk-claude'].col * TILE_SIZE,
      y: OFFICE_SEATS['desk-claude'].row * TILE_SIZE,
      dir: OFFICE_SEATS['desk-claude'].facing,
      targetSeatId: 'desk-claude',
      path: [],
      moveProgress: 0,
    },
    codex: {
      id: 'codex',
      col: OFFICE_SEATS['desk-codex'].col,
      row: OFFICE_SEATS['desk-codex'].row,
      x: OFFICE_SEATS['desk-codex'].col * TILE_SIZE,
      y: OFFICE_SEATS['desk-codex'].row * TILE_SIZE,
      dir: OFFICE_SEATS['desk-codex'].facing,
      targetSeatId: 'desk-codex',
      path: [],
      moveProgress: 0,
    },
    agy: {
      id: 'agy',
      col: OFFICE_SEATS['desk-agy'].col,
      row: OFFICE_SEATS['desk-agy'].row,
      x: OFFICE_SEATS['desk-agy'].col * TILE_SIZE,
      y: OFFICE_SEATS['desk-agy'].row * TILE_SIZE,
      dir: OFFICE_SEATS['desk-agy'].facing,
      targetSeatId: 'desk-agy',
      path: [],
      moveProgress: 0,
    },
  });

  const safeAgents = enforceSingleWriterSeat(agents, designatedWriter);
  const agentsRef = useRef(safeAgents);
  agentsRef.current = safeAgents;

  const selectionRef = useRef({ selectedAgentId, selectedRoom });
  selectionRef.current = { selectedAgentId, selectedRoom };

  // Preload all PNG assets from pixel-agents v1.5.0
  useEffect(() => {
    const assetUrls = new Set<string>([
      CHAR_ASSETS.claude,
      CHAR_ASSETS.codex,
      CHAR_ASSETS.agy,
      'assets/floors/floor_0.png',
      'assets/floors/floor_1.png',
      'assets/floors/floor_3.png',
      'assets/floors/floor_5.png',
      'assets/floors/floor_7.png',
      'assets/walls/wall_0.png',
      'assets/pets/claudio/pet.png',
      'assets/pets/gitcat/pet.png',
      'assets/generated/carpets/carpet_0.png',
      'assets/generated/carpets/carpet_1.png',
      ...Object.values(EMOTE_ASSETS),
      ...PC_FRAME_PATHS,
      ...OFFICE_FURNITURE.map((f) => FURNITURE_ASSETS[f.assetPath] || f.assetPath),
    ]);

    assetUrls.forEach((url) => {
      if (imagesRef.current.has(url)) return;
      const img = new Image();
      img.src = url;
      imagesRef.current.set(url, img);
    });
  }, []);

  // Recompute BFS tile paths when any agent's seat assignment changes
  useEffect(() => {
    (['claude', 'codex', 'agy'] as ProviderId[]).forEach((id) => {
      const ag = safeAgents[id];
      const live = charsRef.current[id];
      const targetSeat = OFFICE_SEATS[ag.seat_id] || OFFICE_SEATS[`desk-${id}`];
      if (live.targetSeatId !== targetSeat.id) {
        live.targetSeatId = targetSeat.id;
        live.path = findTilePath(live.col, live.row, targetSeat.col, targetSeat.row);
        live.moveProgress = 0;
      }
    });
  }, [safeAgents.claude.seat_id, safeAgents.codex.seat_id, safeAgents.agy.seat_id]);

  // 60fps deterministic pixel-art render loop
  useEffect(() => {
    let animId = 0;
    let tick = 0;
    let previousTime = 0;
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const dust: Array<{ x: number; y: number; life: number; dx: number }> = [];

    const render = (time: number) => {
      // Clamp elapsed time after tab suspension; movement speed is refresh-rate independent.
      const dt = previousTime ? Math.min((time - previousTime) / 1000, 0.05) : 0;
      previousTime = time;
      tick += dt * 60;
      const fxTick = motion.matches ? 0 : tick;
      const canvas = canvasRef.current;
      if (!canvas) {
        animId = requestAnimationFrame(render);
        return;
      }
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        animId = requestAnimationFrame(render);
        return;
      }
      ctx.imageSmoothingEnabled = false;

      // 1. Background hallway floor
      ctx.fillStyle = '#172a32';
      ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

      // Draw hallway grid lines (row 8-9 & col 12-13)
      ctx.strokeStyle = '#21343b';
      ctx.lineWidth = 1;
      for (let c = 0; c < OFFICE_COLS; c++) {
        for (let r = 0; r < OFFICE_ROWS; r++) {
          ctx.strokeRect(c * TILE_SIZE * SCALE, r * TILE_SIZE * SCALE, TILE_SIZE * SCALE, TILE_SIZE * SCALE);
        }
      }

      // 2. Render each of the 4 rooms
      (Object.values(ROOM_ZONES) as Array<(typeof ROOM_ZONES)[OfficeRoom]>).forEach((zone) => {
        const zx = zone.x1 * TILE_SIZE * SCALE;
        const zy = zone.y1 * TILE_SIZE * SCALE;
        const zw = (zone.x2 - zone.x1 + 1) * TILE_SIZE * SCALE;
        const zh = (zone.y2 - zone.y1 + 1) * TILE_SIZE * SCALE;
        const roomColors: Record<OfficeRoom, string> = { desks: '#314b4b', meeting_room: '#534a38', coding_room: '#2d493f', review_room: '#3e4055' };
        ctx.fillStyle = roomColors[zone.id];
        ctx.fillRect(zx, zy, zw, zh);

        // Tile floor using pixel-agents floor sprite or fallback pattern
        const floorImg = imagesRef.current.get(zone.floorAsset);
        for (let c = zone.x1; c <= zone.x2; c++) {
          for (let r = zone.y1; r <= zone.y2; r++) {
            const tx = c * TILE_SIZE * SCALE;
            const ty = r * TILE_SIZE * SCALE;
            if (floorImg && floorImg.complete && floorImg.naturalWidth > 0) {
              ctx.globalAlpha = 0.24;
              ctx.drawImage(floorImg, 0, 0, 16, 16, tx, ty, TILE_SIZE * SCALE, TILE_SIZE * SCALE);
              ctx.globalAlpha = 1;
            } else {
              ctx.fillStyle = (c + r) % 2 === 0 ? '#1e293b' : '#263449';
              ctx.fillRect(tx, ty, TILE_SIZE * SCALE, TILE_SIZE * SCALE);
            }
          }
        }

        // Room border (highlight if selected)
        const isSelectedRoom = selectionRef.current.selectedRoom === zone.id;
        ctx.strokeStyle = isSelectedRoom ? '#fbbf24' : zone.accentColor;
        ctx.lineWidth = isSelectedRoom ? 4 + Math.sin(fxTick / 20) : 2;
        ctx.strokeRect(zx, zy, zw, zh);

        // Room top header banner
        ctx.fillStyle = '#1c3038';
        ctx.fillRect(zx, zy - 37, zw, 35);
        ctx.fillStyle = zone.accentColor;
        ctx.font = 'bold 16px "Courier New", monospace';
        ctx.fillText(zone.title, zx + 12, zy - 21);
        ctx.fillStyle = '#b5c6c5';
        ctx.font = '12px "Courier New", monospace';
        ctx.fillText(zone.subtitle, zx + 12, zy - 7);
        const occupants = AGENT_IDS.filter(id => agentsRef.current[id].room === zone.id);
        occupants.forEach((id, i) => {
          ctx.fillStyle = AGENT_COLORS[id];
          ctx.fillRect(zx + zw - 18 - i * 12, zy - 24, 6, 6);
        });
      });

      // Central Hallway Label
      ctx.fillStyle = 'rgba(30, 41, 59, 0.85)';
      ctx.fillRect(9 * TILE_SIZE * SCALE, 8 * TILE_SIZE * SCALE + 6, 8 * TILE_SIZE * SCALE, 28);
      ctx.fillStyle = '#e2e8f0';
      ctx.font = 'bold 12px "Courier New", monospace';
      ctx.fillText('RESEARCH > DISCUSS > RESOLVE > BUILD', 9 * TILE_SIZE * SCALE + 12, 8 * TILE_SIZE * SCALE + 24);

      // Rugs retain their native pixel size: existing 64px art and replacement 48px art both fit.
      ['assets/generated/carpets/carpet_0.png', 'assets/generated/carpets/carpet_1.png'].forEach((url, i) => {
        const img = imagesRef.current.get(url);
        if (img?.complete && img.naturalWidth > 0) {
          ctx.drawImage(img, (i ? 17 : 4) * TILE_SIZE * SCALE, (i ? 11 : 4) * TILE_SIZE * SCALE,
            img.naturalWidth * SCALE, img.naturalHeight * SCALE);
        }
      });

      // 3. Render furniture in each room
      OFFICE_FURNITURE.forEach((furn) => {
        let assetUrl = FURNITURE_ASSETS[furn.assetPath] || furn.assetPath;
        if (furn.isAnimatedPc) {
          const pcIdx = Math.floor(fxTick / 18) % PC_FRAME_PATHS.length;
          assetUrl = PC_FRAME_PATHS[pcIdx];
        }
        const img = imagesRef.current.get(assetUrl);
        const fx = furn.col * TILE_SIZE * SCALE;
        const fy = furn.row * TILE_SIZE * SCALE;
        const fw = furn.widthPx * SCALE;
        const fh = furn.heightPx * SCALE;
        if (img && img.complete && img.naturalWidth > 0) {
          ctx.drawImage(img, fx, fy, fw, fh);
        } else {
          ctx.fillStyle = '#475569';
          ctx.fillRect(fx + 4, fy + 4, fw - 8, fh - 8);
        }
        if (furn.isAnimatedPc) {
          const occupant = AGENT_IDS.find((id) => {
            const live = charsRef.current[id];
            return live.path.length === 0 && live.col === furn.col && live.row === furn.row + 2
              && ['working', 'coding', 'reviewing'].includes(agentsRef.current[id].animation);
          });
          if (occupant) {
            ctx.save();
            ctx.fillStyle = AGENT_COLORS[occupant];
            const pulse = 0.8 + Math.sin(fxTick / 18) * 0.15;
            // Layered pixel rectangles cast light across the desk, without blurred sprite edges.
            [0, 1, 2].forEach((layer) => {
              ctx.globalAlpha = (0.10 - layer * 0.025) * pulse;
              ctx.fillRect(fx - layer * 3 * SCALE, fy + (17 + layer * 2) * SCALE,
                (16 + layer * 6) * SCALE, (5 + layer) * SCALE);
            });
            ctx.restore();
          }
        }
      });

      // Render Office Pets (Claudio & Gitcat) in the corridor
      const claudioImg = imagesRef.current.get('assets/pets/claudio/pet.png');
      if (claudioImg && claudioImg.complete && claudioImg.naturalWidth > 0) {
        const petFrame = Math.floor(fxTick / 20) % 3;
        const petX = Math.round((4 + Math.sin(fxTick / 60) * 1.5) * TILE_SIZE) * SCALE;
        const petY = 8 * TILE_SIZE * SCALE - 8;
        ctx.drawImage(claudioImg, petFrame * 16, 0, 16, 32, petX, petY, 16 * SCALE, 32 * SCALE);
      }
      const gitcatImg = imagesRef.current.get('assets/pets/gitcat/pet.png');
      if (gitcatImg && gitcatImg.complete && gitcatImg.naturalWidth > 0) {
        const petFrame = Math.floor(fxTick / 22) % 3;
        const petX = Math.round((20 + Math.cos(fxTick / 55) * 1.5) * TILE_SIZE) * SCALE;
        const petY = 8 * TILE_SIZE * SCALE - 8;
        ctx.drawImage(gitcatImg, petFrame * 16, 0, 16, 32, petX, petY, 16 * SCALE, 32 * SCALE);
      }

      for (let i = dust.length - 1; i >= 0; i--) {
        const p = dust[i];
        p.life -= dt;
        if (p.life <= 0 || motion.matches) { dust.splice(i, 1); continue; }
        p.x += p.dx * dt;
        p.y -= dt * 5;
        ctx.save();
        ctx.globalAlpha = p.life / 0.35 * 0.35;
        ctx.fillStyle = '#dbc8a5';
        ctx.fillRect(Math.round(p.x) * SCALE, Math.round(p.y) * SCALE, SCALE * 2, SCALE);
        ctx.restore();
      }

      // 4. Advance & render the 3 AI Council Agents (Claude, Codex, Antigravity)
      [...AGENT_IDS].sort((a, b) => charsRef.current[a].y - charsRef.current[b].y).forEach((id) => {
        const snap = agentsRef.current[id];
        const live = charsRef.current[id];
        const seat = OFFICE_SEATS[snap.seat_id] || OFFICE_SEATS[`desk-${id}`];

        const isMoving = live.path.length > 0;
        if (isMoving) {
          const nextStep = live.path[0];
          if (nextStep.col > live.col) live.dir = Direction.RIGHT;
          else if (nextStep.col < live.col) live.dir = Direction.LEFT;
          else if (nextStep.row > live.row) live.dir = Direction.DOWN;
          else if (nextStep.row < live.row) live.dir = Direction.UP;

          live.moveProgress += dt * 8.4;
          if (live.moveProgress >= 1) {
            live.col = nextStep.col;
            live.row = nextStep.row;
            live.x = live.col * TILE_SIZE;
            live.y = live.row * TILE_SIZE;
            live.path.shift();
            live.moveProgress -= 1;
            if (!motion.matches && dust.length < 60) {
              [-1, 1].forEach((side) => dust.push({ x: live.x + 8 + side * 2, y: live.y + 18,
                life: 0.35, dx: side * 7 }));
            }
            if (live.path.length === 0) {
              live.dir = seat.facing;
              live.moveProgress = 0;
            } else {
              const upcoming = live.path[0];
              live.x = (live.col + (upcoming.col - live.col) * live.moveProgress) * TILE_SIZE;
              live.y = (live.row + (upcoming.row - live.row) * live.moveProgress) * TILE_SIZE;
            }
          } else {
            live.x = (live.col + (nextStep.col - live.col) * live.moveProgress) * TILE_SIZE;
            live.y = (live.row + (nextStep.row - live.row) * live.moveProgress) * TILE_SIZE;
          }
        } else {
          live.col = seat.col;
          live.row = seat.row;
          live.x = seat.col * TILE_SIZE;
          live.y = seat.row * TILE_SIZE;
          live.dir = seat.facing;
        }

        const frame = resolveSpriteFrame(snap.animation, isMoving && !motion.matches, live.dir, fxTick);
        const charImg = imagesRef.current.get(CHAR_ASSETS[id]);

        // Character draw position (16x32 sprite anchored on tile)
        const drawX = Math.round(live.x) * SCALE;
        const bob = !isMoving && Math.sin(fxTick / 26 + AGENT_IDS.indexOf(id) * 2) > 0.65 ? 1 : 0;
        const drawY = (Math.round(live.y) - 12 - bob) * SCALE;
        const drawW = 16 * SCALE;
        const drawH = 32 * SCALE;

        ctx.save();
        ctx.fillStyle = 'rgba(8, 12, 24, .38)';
        const shadowX = drawX + (live.dir === Direction.LEFT ? -1 : 1) * SCALE;
        const groundY = (Math.round(live.y) + 18) * SCALE;
        ctx.fillRect(shadowX + SCALE * 2, groundY, SCALE * 14, SCALE * 2);
        ctx.fillRect(shadowX + SCALE * 4, groundY - SCALE, SCALE * 10, SCALE * 4);
        ctx.restore();

        // Provider signatures use only whole pixel rectangles and restrained alpha.
        ctx.save();
        ctx.fillStyle = AGENT_COLORS[id];
        if (id === 'claude') {
          ctx.globalAlpha = 0.18 + Math.sin(fxTick / 28) * 0.05;
          for (let p = 0; p < 10; p++) {
            const angle = p * Math.PI / 5;
            ctx.fillRect(drawX + Math.round(8 + Math.cos(angle) * 12) * SCALE,
              drawY + Math.round(12 + Math.sin(angle) * 9) * SCALE, SCALE, SCALE);
          }
        } else if (id === 'agy') {
          for (let p = 0; p < 5; p++) {
            const angle = fxTick / 65 + p * Math.PI * 2 / 5;
            ctx.globalAlpha = 0.25 + 0.2 * Math.sin(fxTick / 25 + p);
            ctx.fillStyle = p % 2 ? '#4285f4' : '#67e8f9';
            ctx.fillRect(drawX + Math.round(8 + Math.cos(angle) * 13) * SCALE,
              drawY + Math.round(13 + Math.sin(angle) * 13) * SCALE, SCALE, SCALE);
          }
        }
        ctx.restore();

        // Selection ring under character
        const isSelected = selectionRef.current.selectedAgentId === id;
        ctx.save();
        ctx.beginPath();
        ctx.ellipse(
          drawX + drawW / 2,
          drawY + drawH - 6,
          isSelected ? 22 : 16,
          isSelected ? 10 : 7,
          0,
          0,
          Math.PI * 2,
        );
        ctx.fillStyle = isSelected ? 'rgba(251, 191, 36, 0.45)' : `${snap.color}44`;
        ctx.fill();
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.strokeStyle = isSelected ? '#fbbf24' : snap.color;
        ctx.stroke();
        ctx.restore();

        // Draw character sprite from char_N.png (112x96 sheet: 7 cols x 16px, 3 rows x 32px)
        if (charImg && charImg.complete && charImg.naturalWidth > 0) {
          ctx.save();
          if (frame.flipX) {
            ctx.translate(drawX + drawW, drawY);
            ctx.scale(-1, 1);
            ctx.drawImage(
              charImg,
              frame.frameCol * 16,
              frame.frameRow * 32,
              16,
              32,
              0,
              0,
              drawW,
              drawH,
            );
          } else {
            ctx.drawImage(
              charImg,
              frame.frameCol * 16,
              frame.frameRow * 32,
              16,
              32,
              drawX,
              drawY,
              drawW,
              drawH,
            );
          }
          ctx.restore();
        } else {
          // Fallback pixel character if image is still loading
          ctx.fillStyle = snap.color;
          ctx.fillRect(drawX + 8, drawY + 12, drawW - 16, drawH - 16);
        }

        if (id === 'codex') {
          ctx.save();
          ctx.globalAlpha = 0.2;
          ctx.fillStyle = '#6ee7b7';
          const scanY = Math.floor(fxTick / 5) % 22;
          ctx.fillRect(drawX + SCALE * 4, drawY + (5 + scanY) * SCALE, SCALE * 8, SCALE);
          ctx.fillRect(drawX - SCALE * 2, drawY + scanY * SCALE, SCALE, SCALE * 2);
          ctx.restore();
        }

        // Draw overhead pixel speech bubble for active animation state
        if (frame.badge) {
          const bx = drawX - SCALE * 2;
          const by = drawY - SCALE * 24;
          ctx.fillStyle = '#f8fafc';
          ctx.strokeStyle = '#0f172a';
          ctx.lineWidth = 2;
          ctx.fillRect(bx, by, 20 * SCALE, 20 * SCALE);
          ctx.strokeRect(bx, by, 20 * SCALE, 20 * SCALE);
          ctx.fillRect(bx + 8 * SCALE, by + 20 * SCALE, 4 * SCALE, 2 * SCALE);
          const icon = frame.badge === 'waiting' && snap.room === 'meeting_room' ? 'shield' : frame.badge;
          const iconImage = imagesRef.current.get(EMOTE_ASSETS[icon]);
          if (iconImage?.complete && iconImage.naturalWidth === 16) {
            ctx.drawImage(iconImage, bx + 2 * SCALE, by + 2 * SCALE, 16 * SCALE, 16 * SCALE);
          } else drawPixelIcon(ctx, icon, bx + 2 * SCALE, by + 2 * SCALE, SCALE);
          if (!motion.matches && Math.floor(fxTick / 24) % 2 === 0) {
            ctx.fillStyle = '#fff';
            ctx.fillRect(bx + 15 * SCALE, by + 3 * SCALE, SCALE, SCALE);
          }
        }

        // Draw Agent Nameplate & Role/Animation Pill beneath character
        const labelText = ({ claude: 'Claude', codex: 'Codex', agy: 'Antigravity' } as const)[id];
        ctx.font = 'bold 11px "Courier New", monospace';
        const textWidth = ctx.measureText(labelText).width;
        const lx = drawX + drawW / 2 - textWidth / 2 - 6;
        const ly = drawY + drawH + 2;

        ctx.fillStyle = 'rgba(15, 23, 42, 0.92)';
        ctx.fillRect(lx, ly, textWidth + 12, 18);
        ctx.strokeStyle = snap.color;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(lx, ly, textWidth + 12, 18);

        ctx.fillStyle = '#f8fafc';
        ctx.fillText(labelText, lx + 6, ly + 13);
      });

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, []);

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = CANVAS_W / rect.width;
    const scaleY = CANVAS_H / rect.height;
    const cx = (e.clientX - rect.left) * scaleX;
    const cy = (e.clientY - rect.top) * scaleY;

    // 1. Check if user clicked on one of the 3 characters
    for (const id of [...AGENT_IDS].sort((a, b) => charsRef.current[b].y - charsRef.current[a].y)) {
      const live = charsRef.current[id];
      const drawX = live.x * SCALE;
      const drawY = (live.y - 12) * SCALE;
      const drawW = 16 * SCALE;
      const drawH = 32 * SCALE + 22;
      if (cx >= drawX - 10 && cx <= drawX + drawW + 10 && cy >= drawY - 24 && cy <= drawY + drawH) {
        onSelectAgent(id);
        return;
      }
    }

    // 2. Otherwise check if user clicked inside one of the 4 rooms
    for (const zone of Object.values(ROOM_ZONES)) {
      if (cx >= zone.x1 * TILE_SIZE * SCALE && cx < (zone.x2 + 1) * TILE_SIZE * SCALE
        && cy >= zone.y1 * TILE_SIZE * SCALE - 37 && cy < (zone.y2 + 1) * TILE_SIZE * SCALE) {
        onSelectRoom(zone.id);
        return;
      }
    }
  };

  return (
    <div className="pixel-canvas-wrapper" data-testid="pixel-office-canvas-wrapper">
      <canvas
        ref={canvasRef}
        width={CANVAS_W}
        height={CANVAS_H}
        onClick={handleCanvasClick}
        className="pixel-office-canvas"
        data-testid="pixel-office-canvas"
        role="img"
        aria-label="Live pixel office. Use the work-area navigation above or agent buttons below to inspect activity."
      />
      <div className="pixel-canvas-quickbar">
        <span className="quickbar-hint">Select a room to explore its work. Select an agent to inspect activity.</span>
        {(['claude', 'codex', 'agy'] as ProviderId[]).map((id) => {
          const ag = safeAgents[id];
          return (
            <button
              key={id}
              type="button"
              onClick={() => onSelectAgent(id)}
              className={`quick-agent-btn ${selectedAgentId === id ? 'active' : ''}`}
              style={{ borderColor: ag.color }}
              data-testid={`select-agent-${id}`}
              aria-pressed={selectedAgentId === id}
            >
              <span className="dot" style={{ backgroundColor: ag.color }} />
              {{ claude: 'Claude', codex: 'Codex', agy: 'Antigravity' }[id]}
            </button>
          );
        })}
      </div>
    </div>
  );
};

import { useCallback, useEffect, useRef, useState } from 'react';

type Cue = 'click' | 'approval' | 'stage' | 'complete' | 'error';
const NOTES: Record<Cue, number[]> = {
  click: [660], approval: [523.25, 783.99], stage: [392, 523.25],
  complete: [523.25, 659.25, 783.99, 1046.5], error: [196, 146.83],
};

export function useRetroAudio() {
  const [muted, setMuted] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const audio = useRef<{ ctx: AudioContext; master: GainNode } | null>(null);
  const enabled = useRef(false);
  const lastClick = useRef(-Infinity);
  const mounted = useRef(true);

  const play = useCallback((cue: Cue) => {
    const engine = audio.current;
    if (!enabled.current || !engine || engine.ctx.state !== 'running') return;
    const now = engine.ctx.currentTime;
    if (cue === 'click' && now - lastClick.current < 0.045) return;
    if (cue === 'click') lastClick.current = now;
    NOTES[cue].forEach((frequency, i) => {
      const start = now + i * 0.095;
      const osc = engine.ctx.createOscillator();
      const envelope = engine.ctx.createGain();
      osc.type = 'square';
      osc.frequency.setValueAtTime(frequency, start);
      envelope.gain.setValueAtTime(0, start);
      envelope.gain.linearRampToValueAtTime(0.07, start + 0.004);
      envelope.gain.exponentialRampToValueAtTime(0.0001, start + 0.085);
      osc.connect(envelope).connect(engine.master);
      osc.onended = () => { osc.disconnect(); envelope.disconnect(); };
      osc.start(start);
      osc.stop(start + 0.09);
    });
  }, []);

  const toggle = useCallback(async () => {
    if (enabled.current) {
      enabled.current = false;
      audio.current?.master.gain.setValueAtTime(0, audio.current.ctx.currentTime);
      setMuted(true);
      return;
    }
    try {
      // Only constructed/resumed by the user's sound-toggle gesture.
      if (!audio.current) {
        const ctx = new AudioContext();
        const master = ctx.createGain();
        master.gain.value = 0;
        master.connect(ctx.destination);
        audio.current = { ctx, master };
      }
      await audio.current.ctx.resume();
      if (!mounted.current) return;
      enabled.current = true;
      audio.current.master.gain.setValueAtTime(0.35, audio.current.ctx.currentTime);
      setMuted(false);
      play('click');
    } catch {
      if (mounted.current) { setUnavailable(true); setMuted(true); }
      enabled.current = false;
    }
  }, [play]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      enabled.current = false;
      const engine = audio.current;
      audio.current = null;
      if (engine && engine.ctx.state !== 'closed') void engine.ctx.close().catch(() => {});
    };
  }, []);
  return { muted, unavailable, toggle, play };
}

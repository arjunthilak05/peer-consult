import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';

const HINTS = [
  'Research the best approach for my next project…',
  'Compare these ideas and explain the trade-offs…',
  'Help me turn this feature into working code…',
];

function TypedHint({ active }: { active: boolean }) {
  const reduced = useReducedMotion();
  const [text, setText] = useState('');
  useEffect(() => {
    if (!active || reduced) return;
    let timer = 0;
    let phrase = 0, count = 0, deleting = false;
    const step = () => {
      count += deleting ? -1 : 1;
      setText(HINTS[phrase].slice(0, count));
      let delay = deleting ? 22 : 43;
      if (count === HINTS[phrase].length) { deleting = true; delay = 2200; }
      else if (count === 0) { deleting = false; phrase = (phrase + 1) % HINTS.length; delay = 500; }
      timer = window.setTimeout(step, delay);
    };
    setText('');
    timer = window.setTimeout(step, 650);
    return () => clearTimeout(timer);
  }, [active, reduced]);
  if (!active) return null;
  return <span className="typed-hint" aria-hidden="true">{reduced ? HINTS[0] : text}<span className="hint-caret" /></span>;
}

interface TaskComposerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  question: string;
  onQuestionChange: (value: string) => void;
  mode: 'discuss' | 'plan';
  onModeChange: (mode: 'discuss' | 'plan') => void;
  cwd: string;
  onCwdChange: (cwd: string) => void;
  starting: boolean;
  connected: boolean;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  onSubmit: (event: React.FormEvent) => void;
}

export function TaskComposer({ open, onOpenChange, question, onQuestionChange, mode, onModeChange, cwd, onCwdChange, starting, connected, inputRef, onSubmit }: TaskComposerProps) {
  const reduced = useReducedMotion();
  const [focused, setFocused] = useState(false);
  const [typing, setTyping] = useState(false);
  const typingTimer = useRef(0);
  const formRef = useRef<HTMLFormElement | null>(null);
  const canSubmit = connected && !!question.trim() && !starting;

  useEffect(() => () => clearTimeout(typingTimer.current), []);
  useEffect(() => { if (!question || !open) { setTyping(false); clearTimeout(typingTimer.current); } }, [question, open]);
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input || !open) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(280, Math.max(136, input.scrollHeight))}px`;
  }, [question, open, inputRef]);

  return <motion.section className={`task-composer premium-composer ${focused ? 'is-focused' : ''} ${typing ? 'is-typing' : ''}`}
    initial={{ opacity: 0, y: reduced ? 0 : 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .25 }}>
    <button type="button" className="composer-toggle" aria-expanded={open} aria-controls="task-composer-body" onClick={() => onOpenChange(!open)}>
      <span className="composer-command" aria-hidden="true">&gt;_</span><span className="composer-toggle-copy"><b>Give your council a task</b><small>One clear question. Three independent perspectives.</small></span>
      <motion.span className="composer-toggle-icon" aria-hidden="true" animate={{ rotate: open ? 45 : 0 }} transition={{ duration: reduced ? 0 : .18 }}>＋</motion.span>
    </button>
    <AnimatePresence initial={false}>
      {open && <motion.div id="task-composer-body" key="composer-body" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: reduced ? 0 : .22 }} style={{ overflow: 'hidden' }}>
        <form ref={formRef} onSubmit={onSubmit}>
          <div className="composer-editor-heading"><label htmlFor="task-question">Question or objective</label><span className={`composer-writing ${typing ? 'active' : ''}`} aria-hidden="true">{typing ? 'Writing' : focused ? 'Ready when you are' : 'Make it specific'}<span className="writing-dots"><i /><i /><i /></span></span></div>
          <div className="composer-editor">
            <textarea id="task-question" ref={inputRef} value={question} onChange={e => {
              onQuestionChange(e.target.value); setTyping(true); clearTimeout(typingTimer.current);
              typingTimer.current = window.setTimeout(() => setTyping(false), 900);
            }} onFocus={() => setFocused(true)} onBlur={() => { setFocused(false); setTyping(false); }}
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing) {
                  e.preventDefault(); if (canSubmit) formRef.current?.requestSubmit();
                }
              }} placeholder="What should the council research, discuss, or build?"
              aria-describedby="composer-shortcut composer-help" data-testid="question-input" required maxLength={20000} />
            <TypedHint active={!question && !focused} />
            <div className="editor-bottom-bar"><span id="composer-shortcut"><kbd>Ctrl</kbd> + <kbd>Enter</kbd> to start <span className="mac-shortcut">· ⌘ on Mac</span></span><span className="character-count" aria-label={`${question.length} of 20000 characters`}>{question.length.toLocaleString()}<span> / 20,000</span></span></div>
          </div>
          <div className="composer-fields"><label>Workflow<select value={mode} onChange={e => onModeChange(e.target.value as 'discuss' | 'plan')} aria-label="Workflow"><option value="discuss">Research & discussion</option><option value="plan">Plan & implementation</option></select></label><label>Project folder <span className="muted">(optional)</span><input value={cwd} onChange={e => onCwdChange(e.target.value)} placeholder="repository path (optional)" /></label>
            <motion.button type="submit" className="primary composer-submit" data-testid="start-run-btn" disabled={!canSubmit} whileHover={canSubmit && !reduced ? { y: -1 } : undefined} whileTap={canSubmit && !reduced ? { scale: .97 } : undefined}>
              {starting && <span className="button-spinner" aria-hidden="true" />}<span>{starting ? 'Starting…' : 'Start task'}</span><span className="submit-arrow" aria-hidden="true">↗</span>
            </motion.button>
          </div>
          <p className="composer-help" id="composer-help">{mode === 'discuss' ? 'Read-only research and discussion. Your files stay untouched.' : 'The council researches first. You approve the plan and a single writer before coding begins.'}</p>
        </form>
      </motion.div>}
    </AnimatePresence>
  </motion.section>;
}

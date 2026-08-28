import React, { useEffect, useRef, useState } from 'react';
import { ArrowUp, MessageSquareText, X } from 'lucide-react';
import { Badge, Button, Spinner, cn } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { askNarrator } from '../services/api';
import type { Candidate, ProvenanceTag } from '../types';

interface Turn {
  id: string;
  role: 'user' | 'model';
  text: string;
  provenance?: Record<string, ProvenanceTag>;
  error?: boolean;
}

/**
 * Openers built from the network on screen, so the first question is about a
 * real facility rather than a placeholder.
 */
function suggestions(candidates: Candidate[], warehouseNames: string[]): string[] {
  const rejected = candidates.find((c) => !c.passed_screening);
  const questions = [
    'Which warehouse is most critical?',
    'How does cost trade off against resilience here?',
    'Which facilities are most exposed to flooding?',
  ];
  if (warehouseNames.length) {
    questions.unshift(`What if ${warehouseNames[0]} becomes unavailable?`);
  }
  if (rejected) questions.push(`Why was ${rejected.name} ruled out?`);
  return questions.slice(0, 4);
}

export interface AskDrawerProps {
  open: boolean;
  onClose: () => void;
  candidates: Candidate[];
  /** Facilities the active design opens, used to seed the openers. */
  warehouseNames?: string[];
  ready: boolean;
}

export const AskDrawer: React.FC<AskDrawerProps> = ({
  open,
  onClose,
  candidates,
  warehouseNames = [],
  ready,
}) => {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 120);
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns, busy]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const send = async (text: string) => {
    const query = text.trim();
    if (!query || busy) return;

    setDraft('');
    setBusy(true);
    setTurns((t) => [...t, { id: `u-${Date.now()}`, role: 'user', text: query }]);

    try {
      const res = await askNarrator(query);
      setTurns((t) => [
        ...t,
        { id: `m-${Date.now()}`, role: 'model', text: res.answer, provenance: res.provenance },
      ]);
    } catch (err) {
      setTurns((t) => [
        ...t,
        {
          id: `e-${Date.now()}`,
          role: 'model',
          text: err instanceof Error ? err.message : 'That question could not be answered right now.',
          error: true,
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 animate-fade-in bg-ink/20 backdrop-blur-[1px] lg:hidden"
          onClick={onClose}
          aria-hidden
        />
      )}

      <aside
        className={cn(
          'fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-line bg-surface shadow-pop transition-transform duration-300 ease-out',
          open ? 'translate-x-0' : 'pointer-events-none translate-x-full'
        )}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-accent/25 bg-accent-soft text-accent">
              <MessageSquareText className="h-3.5 w-3.5" />
            </span>
            <div>
              <h2 className="text-sm font-semibold tracking-tight text-ink">Ask OptiFlow</h2>
              <p className="text-2xs text-muted">What-if questions, answered from this network.</p>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close" className="px-2">
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {turns.length === 0 && (
            <div>
              <p className="text-xs leading-relaxed text-muted">
                Questions are resolved against the network on screen — its facilities, its
                assignments and the frontier it came from — not from general knowledge.
              </p>
              <div className="mt-4 space-y-2">
                {suggestions(candidates, warehouseNames).map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    disabled={!ready || busy}
                    className="w-full rounded-lg border border-line bg-sunken px-3 py-2.5 text-left text-xs text-muted transition-colors hover:border-accent/30 hover:bg-accent-soft hover:text-accent disabled:opacity-50 focus-ring"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t) =>
            t.role === 'user' ? (
              <div key={t.id} className="flex justify-end">
                <p className="max-w-[85%] rounded-xl rounded-br-sm bg-accent px-3.5 py-2.5 text-xs leading-relaxed text-white">
                  {t.text}
                </p>
              </div>
            ) : (
              <div
                key={t.id}
                className={cn(
                  'rounded-xl rounded-bl-sm border px-3.5 py-3',
                  t.error ? 'border-danger/25 bg-danger-soft' : 'border-line bg-sunken'
                )}
              >
                {t.error ? (
                  <p className="text-xs leading-relaxed text-danger">{t.text}</p>
                ) : (
                  <Markdown text={t.text} />
                )}
                {t.provenance && Object.keys(t.provenance).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-2.5">
                    {Object.entries(t.provenance).map(([layer, tag]) => (
                      <Badge key={layer} tone="neutral">
                        {layer} · #{tag.response_hash?.slice(0, 6)}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            )
          )}

          {busy && (
            <div className="flex items-center gap-2 text-xs text-muted">
              <Spinner className="h-3.5 w-3.5 text-accent" />
              Checking the network state…
            </div>
          )}
        </div>

        <div className="border-t border-line px-5 py-4">
          <div className="flex items-end gap-2 rounded-xl border border-line bg-sunken p-2 transition-colors focus-within:border-accent/40 focus-within:ring-4 focus-within:ring-accent/10">
            <textarea
              ref={inputRef}
              rows={1}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send(draft);
                }
                e.stopPropagation();
              }}
              placeholder={ready ? 'Ask a question…' : 'Run a study first'}
              disabled={!ready || busy}
              className="max-h-[7.5rem] flex-1 resize-none bg-transparent px-1.5 py-1 text-xs leading-relaxed text-ink outline-none placeholder:text-faint disabled:cursor-not-allowed"
            />
            <Button
              variant="primary"
              size="sm"
              onClick={() => send(draft)}
              disabled={!ready || busy || !draft.trim()}
              aria-label="Send"
              className="h-7 w-7 shrink-0 px-0"
            >
              <ArrowUp className="h-3.5 w-3.5" />
            </Button>
          </div>
          <p className="mt-2 text-2xs text-faint">
            Enter sends · Shift + Enter adds a line
          </p>
        </div>
      </aside>
    </>
  );
};

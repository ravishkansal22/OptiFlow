import React from 'react';
import { cn } from './ui';

/**
 * Minimal renderer for the narrator agent's output. It emits a fixed, known
 * subset of Markdown -- headings, bullets, bold, inline code -- so a full
 * parser would be overkill. Everything is escaped by React, never dangerouslySet.
 */

// Bold is listed first so ** wins over the single-asterisk italic alternative.
const INLINE = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`)/g;

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={key} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return (
        <em key={key} className="not-italic font-medium text-ink/80">
          {part.slice(1, -1)}
        </em>
      );
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={key} className="num rounded bg-sunken px-1 py-0.5 font-mono text-2xs text-ink">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <React.Fragment key={key}>{part}</React.Fragment>;
  });
}

/** Strip the emoji the narrator prefixes onto headings; the UI carries its own. */
const stripLeadingEmoji = (s: string) =>
  s.replace(/^[\p{Extended_Pictographic}️‍\s]+/u, '').trim();

export const Markdown: React.FC<{ text: string; className?: string }> = ({ text, className }) => {
  if (!text?.trim()) return null;

  const lines = text.split('\n');
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = () => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="my-2.5 space-y-1.5">
        {items.map((b, i) => (
          <li key={i} className="relative pl-4 text-sm leading-relaxed text-muted">
            <span className="absolute left-0 top-[0.62em] h-px w-2 bg-strong" />
            {renderInline(b, `li-${i}`)}
          </li>
        ))}
      </ul>
    );
  };

  lines.forEach((raw, i) => {
    const line = raw.trimEnd();

    if (!line.trim()) {
      flushBullets();
      return;
    }

    if (line.startsWith('####')) {
      flushBullets();
      blocks.push(
        <h4 key={`h4-${i}`} className="mt-5 text-sm font-semibold tracking-tight text-ink first:mt-0">
          {stripLeadingEmoji(line.replace(/^#+\s*/, ''))}
        </h4>
      );
      return;
    }

    if (line.startsWith('#')) {
      flushBullets();
      blocks.push(
        <h3
          key={`h3-${i}`}
          className="mt-6 font-display text-lg font-medium tracking-tight text-ink first:mt-0"
        >
          {stripLeadingEmoji(line.replace(/^#+\s*/, ''))}
        </h3>
      );
      return;
    }

    if (/^[-*]\s+/.test(line)) {
      bullets.push(line.replace(/^[-*]\s+/, ''));
      return;
    }

    flushBullets();
    blocks.push(
      <p key={`p-${i}`} className="my-2.5 text-sm leading-relaxed text-muted first:mt-0">
        {renderInline(stripLeadingEmoji(line), `p-${i}`)}
      </p>
    );
  });

  flushBullets();

  return <div className={cn('max-w-none', className)}>{blocks}</div>;
};

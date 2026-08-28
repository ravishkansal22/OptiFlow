import React from 'react';
import { FileSearch } from 'lucide-react';
import { Badge, Button, Dialog, EmptyState, cn } from './ui';
import type { ProvenanceTag } from '../types';

/**
 * The evidence behind a value: which Mireye endpoint answered, when, how long
 * it took and the hash of the response it came from. A tag that is not `live`
 * came from the local simulation model, and says so.
 */
export const ProvenanceRow: React.FC<{ layer: string; tag: ProvenanceTag }> = ({ layer, tag }) => (
  <li className="rounded-lg border border-line bg-surface px-2.5 py-2">
    <div className="flex items-center justify-between gap-2">
      <span className="num font-mono text-2xs text-ink">{layer}</span>
      <Badge tone={tag.live ? 'pass' : tag.cached ? 'neutral' : 'warn'}>
        {tag.source || (tag.live ? 'live' : 'simulation')}
      </Badge>
    </div>
    <p className="num mt-1 truncate font-mono text-2xs text-muted" title={tag.endpoint}>
      {tag.endpoint}
    </p>
    <p className="num mt-0.5 font-mono text-2xs text-faint">
      #{tag.response_hash?.slice(0, 12)} · {tag.latency_ms?.toFixed(0)}ms
      {tag.timestamp ? ` · ${new Date(tag.timestamp).toLocaleTimeString('en-US', { hour12: false })}` : ''}
    </p>
  </li>
);

export const ProvenanceList: React.FC<{
  provenance?: Record<string, ProvenanceTag> | null;
  className?: string;
  emptyLabel?: string;
}> = ({ provenance, className, emptyLabel = 'No provenance was attached to this record.' }) => {
  const entries = Object.entries(provenance ?? {});
  if (!entries.length) return <p className="text-xs text-muted">{emptyLabel}</p>;
  return (
    <ul className={cn('space-y-2', className)}>
      {entries.map(([layer, tag]) => (
        <ProvenanceRow key={layer} layer={layer} tag={tag} />
      ))}
    </ul>
  );
};

/** How much of one record rests on real API answers rather than the simulator. */
export const evidenceSummary = (provenance?: Record<string, ProvenanceTag> | null) => {
  const tags = Object.values(provenance ?? {});
  const live = tags.filter((t) => t.live).length;
  return { total: tags.length, live, allLive: tags.length > 0 && live === tags.length };
};

/**
 * The full evidence trail for one site or lane. Opened from anywhere a value is
 * shown, so the number on screen can always be traced to the call behind it.
 */
export const MireyeEvidenceDialog: React.FC<{
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  provenance?: Record<string, ProvenanceTag> | null;
}> = ({ open, onClose, title, provenance }) => {
  const { total, live } = evidenceSummary(provenance);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Mireye evidence"
      subtitle={
        total > 0
          ? `${live} of ${total} values for ${title} came from the API; the rest are simulated.`
          : `Nothing was recorded for ${title}.`
      }
      wide
    >
      {total === 0 ? (
        <EmptyState
          icon={<FileSearch className="h-5 w-5" />}
          title="No evidence recorded"
          body="This record carries no provenance tag, so its values cannot be traced to a lookup."
        />
      ) : (
        <>
          <ProvenanceList provenance={provenance} />
          <p className="mt-4 border-t border-line pt-3 text-2xs leading-relaxed text-muted">
            Each row is one call the Mireye Gateway made. The hash identifies the exact response the
            value was read from, so the same verdict can be checked again later.
          </p>
        </>
      )}
    </Dialog>
  );
};

/** Opens the evidence dialog for a record. */
export const EvidenceButton: React.FC<{
  provenance?: Record<string, ProvenanceTag> | null;
  label?: string;
  title: React.ReactNode;
  className?: string;
}> = ({ provenance, label = 'View Mireye evidence', title, className }) => {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)} className={className}>
        <FileSearch className="h-3.5 w-3.5" />
        {label}
      </Button>
      <MireyeEvidenceDialog
        open={open}
        onClose={() => setOpen(false)}
        title={title}
        provenance={provenance}
      />
    </>
  );
};

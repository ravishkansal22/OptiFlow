import React, { useMemo, useState } from 'react';
import {
  ArrowRight,
  ChevronDown,
  Layers,
  Mountain,
  Search,
  ShieldAlert,
  Waves,
  X,
} from 'lucide-react';
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, Meter, Segmented, cn } from '../components/ui';
import { EvidenceButton, ProvenanceList, evidenceSummary } from '../components/Provenance';
import { NetworkMap } from '../panels/NetworkMap';
import { SiteDecisions } from '../panels/SiteDecisions';
import { buildCandidateInsights, type CandidateInsight } from '../lib/network';
import { summarizeScreening } from '../lib/domain';
import { coord, num, pct, usdShort } from '../lib/format';
import type { Candidate, LogisticsGraph, NetworkSolution } from '../types';

type Filter = 'all' | 'viable' | 'rejected';

const STATUS_META = {
  selected: { label: 'In the plan', tone: 'accent' as const },
  eligible: { label: 'Viable', tone: 'pass' as const },
  rejected: { label: 'Rejected', tone: 'danger' as const },
};

export interface CandidatesProps {
  candidates: Candidate[];
  graph: LogisticsGraph | null;
  solution: NetworkSolution | null;
  budgetLimit?: number;
  busy?: boolean;
  onOptimize: () => void;
}

/**
 * The shortlist, on the map where it means something. Every figure on a card is
 * one the Site and Risk agents measured, or a count of the routed lanes the
 * Route agent built.
 */
export const Candidates: React.FC<CandidatesProps> = ({
  candidates,
  graph,
  solution,
  budgetLimit,
  busy,
  onOptimize,
}) => {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [showTable, setShowTable] = useState(false);

  const insights = useMemo(
    () => buildCandidateInsights(candidates, graph, solution),
    [candidates, graph, solution]
  );
  const summary = useMemo(() => summarizeScreening(candidates, solution), [candidates, solution]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return insights.filter((v) => {
      if (filter === 'viable' && v.status === 'rejected') return false;
      if (filter === 'rejected' && v.status !== 'rejected') return false;
      if (!q) return true;
      return (
        v.candidate.name.toLowerCase().includes(q) ||
        v.candidate.id.toLowerCase().includes(q) ||
        v.candidate.land_cover.toLowerCase().includes(q) ||
        v.candidate.rejection_reasons.some((r) => r.toLowerCase().includes(q))
      );
    });
  }, [insights, filter, query]);

  const detail = insights.find((v) => v.candidate.id === detailId) ?? null;

  if (!candidates.length) {
    return (
      <Card>
        <EmptyState
          icon={<Layers className="h-5 w-5" />}
          title="Nothing screened yet"
          body="Run the analysis and every site OptiFlow checked will be listed here, with the reason behind each verdict."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-[1.6rem] font-medium leading-tight tracking-tight text-ink">
            Warehouse Candidates
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">
            {summary.passed} of {summary.total} sites can take a warehouse. Pick any one to see what
            was measured there and the lookups behind it.
          </p>
        </div>
        <Button variant="primary" size="lg" onClick={onOptimize} loading={busy}>
          Build Optimized Network
          <ArrowRight className="h-4 w-4" />
        </Button>
      </header>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(22rem,0.9fr)] xl:items-start">
        <NetworkMap
          graph={graph}
          candidates={candidates}
          solution={solution}
          selectedCandidateId={selectedId}
          onSelectCandidate={(id) => {
            setSelectedId(id);
            setDetailId(id);
          }}
          title="Where the candidates are"
          subtitle={`${summary.passed} viable · ${summary.rejected} rejected · ${graph?.customers.length ?? 0} demand zones · ${graph?.hazards.length ?? 0} hazard zones`}
        />

        <Card flush className="xl:sticky xl:top-32">
          <div className="space-y-3 border-b border-line px-4 py-3.5">
            <CardHeader
              title="The shortlist"
              subtitle="Ordered by suitability, best first."
            />
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search sites or reasons"
                  className="h-8 w-full rounded-lg border border-line bg-surface pl-8 pr-7 text-xs text-ink outline-none transition-colors placeholder:text-faint focus:border-accent/50 focus:ring-4 focus:ring-accent/10"
                />
                {query && (
                  <button
                    onClick={() => setQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-ink"
                    aria-label="Clear search"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
              <Segmented<Filter>
                value={filter}
                onChange={setFilter}
                options={[
                  { value: 'all', label: `All ${insights.length}` },
                  { value: 'viable', label: `Viable ${summary.passed}` },
                  { value: 'rejected', label: `Out ${summary.rejected}` },
                ]}
              />
            </div>
          </div>

          {visible.length === 0 ? (
            <EmptyState title="Nothing matches" body="Try a different filter or search term." />
          ) : (
            <ul className="max-h-[38rem] divide-y divide-line overflow-y-auto">
              {visible.map((v) => (
                <CandidateCard
                  key={v.candidate.id}
                  insight={v}
                  selected={selectedId === v.candidate.id}
                  onSelect={() => {
                    setSelectedId(v.candidate.id);
                    setDetailId(v.candidate.id);
                  }}
                />
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* --------------------- everything measured, folded away --------------------- */}
      <div>
        <button
          onClick={() => setShowTable((v) => !v)}
          className="flex items-center gap-1.5 text-xs font-medium text-muted transition-colors hover:text-ink focus-ring"
        >
          <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showTable && 'rotate-180')} />
          Full screening table
        </button>
        {showTable && (
          <div className="mt-4 animate-fade-in">
            <SiteDecisions
              candidates={candidates}
              graph={graph}
              solution={solution}
              budgetLimit={budgetLimit}
            />
          </div>
        )}
      </div>

      <CandidateDetail insight={detail} onClose={() => setDetailId(null)} />
    </div>
  );
};

/* ---------------------------------------------------------------- cards */

const CandidateCard: React.FC<{
  insight: CandidateInsight;
  selected: boolean;
  onSelect: () => void;
}> = ({ insight, selected, onSelect }) => {
  const c = insight.candidate;
  const meta = STATUS_META[insight.status];

  return (
    <li>
      <button
        onClick={onSelect}
        className={cn(
          'w-full px-4 py-3.5 text-left transition-colors',
          selected ? 'bg-accent-soft' : 'hover:bg-sunken'
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className={cn('truncate text-[13px] font-medium', selected ? 'text-accent' : 'text-ink')}>
              {c.name}
            </p>
            <p className="num mt-0.5 truncate font-mono text-2xs text-faint">{c.id}</p>
          </div>
          <Badge tone={meta.tone}>{meta.label}</Badge>
        </div>

        {insight.status === 'rejected' ? (
          <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-danger">
            {c.rejection_reasons[0] ?? 'Failed screening.'}
          </p>
        ) : (
          <>
            <div className="mt-2.5 flex items-baseline justify-between gap-2">
              <span className="text-2xs text-faint">Suitability</span>
              <span className="num text-xs font-medium text-ink">
                {Math.round(c.suitability_score * 100)}
              </span>
            </div>
            <Meter value={c.suitability_score} tone={selected ? 'accent' : 'pass'} className="mt-1.5" />

            <dl className="mt-3 grid grid-cols-3 gap-2">
              <MiniField label="Risk" value={c.composite_risk.toFixed(2)} />
              <MiniField
                label="Reach"
                value={
                  insight.totalZones
                    ? `${insight.zonesInWindow}/${insight.totalZones}`
                    : '—'
                }
              />
              <MiniField
                label="Median"
                value={insight.medianMinutes == null ? '—' : `${insight.medianMinutes.toFixed(0)}m`}
              />
            </dl>
          </>
        )}
      </button>
    </li>
  );
};

const MiniField: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <dt className="text-2xs text-faint">{label}</dt>
    <dd className="num text-xs font-medium text-ink">{value}</dd>
  </div>
);

/* ------------------------------------------------------- "why this site" */

const CandidateDetail: React.FC<{ insight: CandidateInsight | null; onClose: () => void }> = ({
  insight,
  onClose,
}) => {
  if (!insight) return null;
  const c = insight.candidate;
  const meta = STATUS_META[insight.status];
  const evidence = evidenceSummary(c.provenance);

  return (
    <Dialog
      open
      onClose={onClose}
      title="Why this site?"
      subtitle={`${c.name} · ${coord(c.lat, c.lon)}`}
      wide
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={meta.tone}>{meta.label}</Badge>
        {insight.status !== 'rejected' && (
          <Badge tone="neutral">suitability {Math.round(c.suitability_score * 100)}</Badge>
        )}
        <Badge tone={evidence.allLive ? 'pass' : 'warn'}>
          {evidence.live}/{evidence.total} values live
        </Badge>
      </div>

      {c.rejection_reasons.length > 0 && (
        <div className="mt-4 rounded-lg border border-danger/20 bg-danger-soft px-3.5 py-3">
          <p className="text-2xs font-medium uppercase tracking-[0.08em] text-danger">
            Why it was rejected
          </p>
          <ul className="mt-2 space-y-1.5">
            {c.rejection_reasons.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-xs leading-relaxed text-danger">
                <X className="mt-0.5 h-3 w-3 shrink-0" strokeWidth={2.5} />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        <Section icon={<Mountain className="h-3.5 w-3.5" />} title="Terrain">
          <Row k="Slope" v={`${c.terrain_slope_pct.toFixed(2)}%`} />
          <Row k="Elevation" v={`${num(c.elevation_m, 1)} m`} />
        </Section>

        <Section icon={<Waves className="h-3.5 w-3.5" />} title="Flood risk">
          <Row k="Flood index" v={c.flood_risk_score.toFixed(3)} />
          <Row k="Composite risk" v={c.composite_risk.toFixed(3)} />
        </Section>

        <Section icon={<Layers className="h-3.5 w-3.5" />} title="Infrastructure">
          <Row k="Land cover" v={c.land_cover} />
          <Row k="Parcel area" v={c.parcel_area_sqm > 0 ? `${num(c.parcel_area_sqm)} m²` : '0'} />
          <Row k="Occupied" v={String(c.is_occupied)} />
          <Row k="Capacity" v={`${num(c.capacity_units)} units`} />
          <Row k="Fixed cost" v={`${usdShort(c.fixed_operating_cost)}/yr`} />
        </Section>

        <Section icon={<ShieldAlert className="h-3.5 w-3.5" />} title="Accessibility">
          {insight.warehouseId ? (
            <>
              <Row
                k="Zones in window"
                v={`${insight.zonesInWindow} of ${insight.totalZones}`}
              />
              <Row k="Demand reachable" v={pct(insight.reachShare * 100, 0)} />
              <Row
                k="Median drive"
                v={insight.medianMinutes == null ? '—' : `${insight.medianMinutes.toFixed(0)} min`}
              />
              {insight.status === 'selected' && (
                <Row
                  k="Assigned"
                  v={`${num(insight.demandServed)} units · ${insight.customerCount} zones`}
                />
              )}
            </>
          ) : (
            <p className="text-xs leading-relaxed text-muted">
              Rejected sites never enter the routing graph, so no drive times were measured here.
            </p>
          )}
        </Section>
      </div>

      {Object.keys(c.score_components ?? {}).length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
            What the suitability score is made of
          </p>
          <ul className="mt-3 space-y-2.5">
            {Object.entries(c.score_components).map(([key, value]) => (
              <li key={key} className="flex items-center gap-3">
                <span className="num min-w-0 flex-1 truncate font-mono text-2xs text-muted">{key}</span>
                <Meter value={value} className="w-32 shrink-0" />
                <span className="num w-9 shrink-0 text-right text-xs text-ink">
                  {value.toFixed(2)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <p className="text-2xs leading-relaxed text-muted">
          Every value above came from a recorded lookup. Open the evidence to see which.
        </p>
        <EvidenceButton provenance={c.provenance} title={c.name} />
      </div>

      <details className="mt-4 rounded-lg border border-line bg-sunken px-3.5 py-3">
        <summary className="cursor-pointer text-2xs font-medium uppercase tracking-[0.08em] text-faint">
          Provenance inline
        </summary>
        <ProvenanceList provenance={c.provenance} className="mt-3" />
      </details>
    </Dialog>
  );
};

const Section: React.FC<{ icon: React.ReactNode; title: string; children: React.ReactNode }> = ({
  icon,
  title,
  children,
}) => (
  <div>
    <p className="flex items-center gap-1.5 text-2xs font-medium uppercase tracking-[0.08em] text-faint">
      <span className="text-muted">{icon}</span>
      {title}
    </p>
    <dl className="mt-2.5 divide-y divide-line rounded-lg border border-line bg-surface px-3">
      {children}
    </dl>
  </div>
);

const Row: React.FC<{ k: string; v: string }> = ({ k, v }) => (
  <div className="flex items-baseline justify-between gap-3 py-1.5">
    <dt className="text-2xs text-faint">{k}</dt>
    <dd className="num truncate text-xs text-ink">{v}</dd>
  </div>
);

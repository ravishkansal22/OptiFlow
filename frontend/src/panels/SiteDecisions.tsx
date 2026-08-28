import React, { useMemo, useState } from 'react';
import { ChevronRight, Search, ShieldCheck, X } from 'lucide-react';
import { Badge, Card, CardHeader, EmptyState, Meter, Segmented, cn } from '../components/ui';
import { ProvenanceRow } from '../components/Provenance';
import { buildVerdicts, riskShade, summarizeScreening, type CandidateVerdict } from '../lib/domain';
import { num, usd, usdShort } from '../lib/format';
import type { Candidate, LogisticsGraph, NetworkSolution } from '../types';

type Filter = 'all' | 'selected' | 'eligible' | 'rejected';

const OUTCOME_META = {
  selected: { label: 'In the plan', tone: 'accent' as const, blurb: 'We recommend opening this one' },
  eligible: { label: 'Usable', tone: 'info' as const, blurb: 'This place works, but the plan does not need it' },
  rejected: { label: 'Ruled out', tone: 'danger' as const, blurb: 'This place will not work' },
};

export interface SiteDecisionsProps {
  candidates: Candidate[];
  graph: LogisticsGraph | null;
  solution: NetworkSolution | null;
  budgetLimit?: number;
}

export const SiteDecisions: React.FC<SiteDecisionsProps> = ({
  candidates,
  graph,
  solution,
  budgetLimit,
}) => {
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);

  const verdicts = useMemo(
    () => buildVerdicts(candidates, graph, solution),
    [candidates, graph, solution]
  );
  const summary = useMemo(() => summarizeScreening(candidates, solution), [candidates, solution]);
  const maxRisk = useMemo(
    () => Math.max(0, ...candidates.map((c) => c.composite_risk)),
    [candidates]
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return verdicts.filter((v) => {
      if (filter !== 'all' && v.outcome !== filter) return false;
      if (!q) return true;
      return (
        v.candidate.name.toLowerCase().includes(q) ||
        v.candidate.id.toLowerCase().includes(q) ||
        v.candidate.land_cover.toLowerCase().includes(q) ||
        v.candidate.rejection_reasons.some((r) => r.toLowerCase().includes(q))
      );
    });
  }, [verdicts, filter, query]);

  if (!candidates.length) {
    return (
      <Card>
        <EmptyState
          icon={<ShieldCheck className="h-5 w-5" />}
          title="Nothing checked yet"
          body="Start a plan and every place we check will be listed here."
        />
      </Card>
    );
  }

  const counts = {
    all: verdicts.length,
    selected: verdicts.filter((v) => v.outcome === 'selected').length,
    eligible: verdicts.filter((v) => v.outcome === 'eligible').length,
    rejected: verdicts.filter((v) => v.outcome === 'rejected').length,
  };

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="What we found"
          subtitle={`${summary.passed} of ${summary.total} places can take a warehouse. ${summary.selected} are in the plan.`}
        />
        <div className="mt-5 flex h-2.5 overflow-hidden rounded-full bg-sunken">
          <Segment value={counts.selected} total={counts.all} className="bg-accent" />
          <Segment value={counts.eligible} total={counts.all} className="bg-info/45" />
          <Segment value={counts.rejected} total={counts.all} className="bg-danger/35" />
        </div>
        <div className="mt-4 grid grid-cols-3 gap-3">
          <MiniStat label="In the plan" value={counts.selected} tone="accent" />
          <MiniStat label="Usable, not needed" value={counts.eligible} tone="info" />
          <MiniStat label="Ruled out" value={counts.rejected} tone="danger" />
        </div>

        {summary.reasonCounts.length > 0 && (
          <div className="mt-6 border-t border-line pt-4">
            <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
              Why places were ruled out
            </p>
            <ul className="mt-3 space-y-2.5">
              {summary.reasonCounts.map((r) => (
                <li key={r.label} className="flex items-center gap-3">
                  <span className="min-w-0 flex-1 truncate text-xs text-muted" title={r.label}>
                    {r.label}
                  </span>
                  <Meter
                    value={r.count}
                    max={Math.max(...summary.reasonCounts.map((x) => x.count))}
                    tone="danger"
                    className="w-32 shrink-0"
                  />
                  <span className="num w-6 shrink-0 text-right text-xs font-medium text-ink">
                    {r.count}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <Card flush>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <CardHeader
            title="Every place we checked"
            subtitle="Click any row to see the measurements behind the verdict."
          />
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search places or reasons"
                className="h-8 w-52 rounded-lg border border-line bg-surface pl-8 pr-7 text-xs text-ink outline-none transition-colors placeholder:text-faint focus:border-accent/50 focus:ring-4 focus:ring-accent/10"
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
                { value: 'all', label: `All ${counts.all}` },
                { value: 'selected', label: `In plan ${counts.selected}` },
                { value: 'eligible', label: `Usable ${counts.eligible}` },
                { value: 'rejected', label: `Ruled out ${counts.rejected}` },
              ]}
            />
          </div>
        </div>

        {visible.length === 0 ? (
          <EmptyState title="Nothing matches" body="Try a different filter or search term." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[52rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-line text-2xs uppercase tracking-[0.06em] text-faint">
                  <Th className="w-8" />
                  <Th>Place</Th>
                  <Th className="text-right">Steepness</Th>
                  <Th className="text-right">Height</Th>
                  <Th className="text-right">Land size</Th>
                  <Th className="text-right">Risk</Th>
                  <Th className="text-right">Cost a year</Th>
                  <Th className="text-right">Verdict</Th>
                </tr>
              </thead>
              <tbody>
                {visible.map((v) => (
                  <SiteRow
                    key={v.candidate.id}
                    verdict={v}
                    maxRisk={maxRisk}
                    expanded={expanded === v.candidate.id}
                    onToggle={() =>
                      setExpanded((cur) => (cur === v.candidate.id ? null : v.candidate.id))
                    }
                    budgetLimit={budgetLimit}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};

/* ------------------------------------------------------------------ rows */

const SiteRow: React.FC<{
  verdict: CandidateVerdict;
  maxRisk: number;
  expanded: boolean;
  onToggle: () => void;
  budgetLimit?: number;
}> = ({ verdict, maxRisk, expanded, onToggle, budgetLimit }) => {
  const c = verdict.candidate;
  const meta = OUTCOME_META[verdict.outcome];
  const shade = riskShade(c.composite_risk, maxRisk);

  return (
    <>
      <tr
        onClick={onToggle}
        className={cn(
          'cursor-pointer border-b border-line transition-colors',
          expanded ? 'bg-sunken' : 'hover:bg-sunken/60'
        )}
      >
        <Td>
          <ChevronRight
            className={cn(
              'h-3.5 w-3.5 text-faint transition-transform duration-200',
              expanded && 'rotate-90'
            )}
          />
        </Td>
        <Td>
          <div className="flex items-center gap-2.5">
            <span
              className={cn(
                'h-6 w-1 shrink-0 rounded-full',
                verdict.outcome === 'selected'
                  ? 'bg-accent'
                  : verdict.outcome === 'eligible'
                    ? 'bg-info/50'
                    : 'bg-danger/40'
              )}
            />
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium text-ink">{c.name}</div>
              <div className="num truncate font-mono text-2xs text-faint">
                {c.id} · {c.land_cover}
              </div>
            </div>
          </div>
        </Td>
        <Td className="num text-right text-xs text-muted">{c.terrain_slope_pct.toFixed(1)}%</Td>
        <Td className="num text-right text-xs text-muted">{num(c.elevation_m)} m</Td>
        <Td className="num text-right text-xs text-muted">
          {c.parcel_area_sqm > 0 ? `${num(c.parcel_area_sqm)} m²` : '0'}
        </Td>
        <Td className="text-right">
          <span className="inline-flex items-center gap-2">
            <span className="h-1.5 w-12 overflow-hidden rounded-full bg-sunken">
              <span
                className="block h-full rounded-full bg-danger/70"
                style={{ width: `${shade * 100}%` }}
              />
            </span>
            <span className="num w-8 text-right text-xs text-muted">
              {c.composite_risk.toFixed(2)}
            </span>
          </span>
        </Td>
        <Td className="num text-right text-xs text-muted">{usdShort(c.fixed_operating_cost)}</Td>
        <Td className="text-right">
          <Badge tone={meta.tone}>{meta.label}</Badge>
        </Td>
      </tr>

      {expanded && (
        <tr className="border-b border-line bg-sunken">
          <td colSpan={8} className="px-5 py-5">
            <SiteDetail verdict={verdict} budgetLimit={budgetLimit} />
          </td>
        </tr>
      )}
    </>
  );
};

const SiteDetail: React.FC<{ verdict: CandidateVerdict; budgetLimit?: number }> = ({
  verdict,
  budgetLimit,
}) => {
  const c = verdict.candidate;
  const meta = OUTCOME_META[verdict.outcome];

  return (
    <div className="grid animate-fade-in gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
      <div>
        <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">Our answer</p>
        <p className="mt-2 text-sm font-medium text-ink">{meta.blurb}</p>

        {c.rejection_reasons.length > 0 ? (
          <>
            <p className="num mt-3 font-mono text-2xs text-faint">rejection_reasons</p>
            <ul className="mt-1.5 space-y-2">
              {c.rejection_reasons.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-xs leading-relaxed text-danger">
                  <X className="mt-0.5 h-3 w-3 shrink-0" strokeWidth={2.5} />
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </>
        ) : verdict.outcome === 'selected' ? (
          <div className="mt-3 space-y-1.5 text-xs text-muted">
            <p>
              Assigned <span className="num font-medium text-ink">{num(verdict.demandServed)}</span>{' '}
              units across <span className="num font-medium text-ink">{verdict.customerCount}</span>{' '}
              demand zones.
            </p>
            <p>
              That is{' '}
              <span className="num font-medium text-ink">
                {c.capacity_units > 0
                  ? `${((verdict.demandServed / c.capacity_units) * 100).toFixed(0)}%`
                  : '—'}
              </span>{' '}
              of its {num(c.capacity_units)} units of capacity.
            </p>
            {budgetLimit != null && budgetLimit > 0 && (
              <p>
                Fixed cost is{' '}
                <span className="num font-medium text-ink">
                  {((c.fixed_operating_cost / budgetLimit) * 100).toFixed(1)}%
                </span>{' '}
                of the {usd(budgetLimit)} budget.
              </p>
            )}
          </div>
        ) : (
          <p className="mt-3 text-xs leading-relaxed text-muted">
            No rejection reasons were returned for this candidate, and it is not among the active
            plan&apos;s selected_warehouse_ids.
          </p>
        )}
      </div>

      <div>
        <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
          What we measured
        </p>
        <dl className="mt-2.5 divide-y divide-line rounded-lg border border-line bg-surface px-3">
          <Field k="terrain_slope_pct" v={c.terrain_slope_pct.toFixed(2)} />
          <Field k="elevation_m" v={num(c.elevation_m, 1)} />
          <Field k="parcel_area_sqm" v={num(c.parcel_area_sqm)} />
          <Field k="is_occupied" v={String(c.is_occupied)} />
          <Field k="land_cover" v={c.land_cover} />
          <Field k="flood_risk_score" v={c.flood_risk_score.toFixed(3)} />
          <Field k="hazard_score" v={c.hazard_score.toFixed(3)} />
          <Field k="composite_risk" v={c.composite_risk.toFixed(3)} />
          <Field k="capacity_units" v={num(c.capacity_units)} />
          <Field k="fixed_operating_cost" v={num(c.fixed_operating_cost)} />
          <Field k="lat, lon" v={`${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}`} />
        </dl>
      </div>

      <div>
        <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
          Where the data came from
        </p>
        {Object.keys(c.provenance ?? {}).length === 0 ? (
          <p className="mt-2.5 text-xs text-muted">No provenance was attached to this candidate.</p>
        ) : (
          <ul className="mt-2.5 space-y-2">
            {Object.entries(c.provenance).map(([layer, tag]) => (
              <ProvenanceRow key={layer} layer={layer} tag={tag} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

const Field: React.FC<{ k: string; v: string }> = ({ k, v }) => (
  <div className="flex items-baseline justify-between gap-3 py-1.5">
    <dt className="num font-mono text-2xs text-faint">{k}</dt>
    <dd className="num truncate text-xs text-ink">{v}</dd>
  </div>
);

/* ---------------------------------------------------------------- atoms */

const Th: React.FC<{ className?: string; children?: React.ReactNode }> = ({ className, children }) => (
  <th className={cn('px-4 py-2.5 font-medium first:pl-5 last:pr-5', className)}>{children}</th>
);

const Td: React.FC<{ className?: string; children?: React.ReactNode }> = ({ className, children }) => (
  <td className={cn('px-4 py-3 align-middle first:pl-5 last:pr-5', className)}>{children}</td>
);

const Segment: React.FC<{ value: number; total: number; className: string }> = ({
  value,
  total,
  className,
}) =>
  value <= 0 ? null : (
    <div
      className={cn('h-full transition-[width] duration-500', className)}
      style={{ width: `${(value / Math.max(total, 1)) * 100}%` }}
    />
  );

const MiniStat: React.FC<{ label: string; value: number; tone: 'accent' | 'info' | 'danger' }> = ({
  label,
  value,
  tone,
}) => (
  <div className="rounded-lg border border-line bg-sunken px-3 py-2.5">
    <div
      className={cn(
        'num font-display text-xl font-medium leading-none',
        tone === 'accent' ? 'text-accent' : tone === 'info' ? 'text-info' : 'text-danger'
      )}
    >
      {value}
    </div>
    <div className="mt-1 text-2xs text-muted">{label}</div>
  </div>
);

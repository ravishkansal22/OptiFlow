import React, { useMemo, useState } from 'react';
import {
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';
import { GitCompare } from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, Segmented, cn } from '../components/ui';
import { baselineSolution } from '../lib/domain';
import { num, pct, score, usd, usdShort } from '../lib/format';
import type { NetworkSolution } from '../types';

type Sort = 'cost' | 'resilience';

export interface TradeoffPanelProps {
  frontier: NetworkSolution[];
  activeId: string;
  onSelect: (id: string) => void;
  busy?: boolean;
}

interface Point {
  id: string;
  cost: number;
  resilience: number;
  hubs: number;
  name: string;
  demand: number;
  isActive: boolean;
  isBaseline: boolean;
}

export const TradeoffPanel: React.FC<TradeoffPanelProps> = ({
  frontier,
  activeId,
  onSelect,
  busy,
}) => {
  const [sort, setSort] = useState<Sort>('cost');

  const active = frontier.find((s) => s.solution_id === activeId) ?? frontier[0] ?? null;
  const baseline = useMemo(() => baselineSolution(frontier), [frontier]);
  const best = useMemo(
    () => (frontier.length ? frontier.reduce((a, b) => (b.resilience_score > a.resilience_score ? b : a)) : null),
    [frontier]
  );

  const points = useMemo<Point[]>(
    () =>
      frontier.map((s) => ({
        id: s.solution_id,
        cost: s.total_cost,
        resilience: s.resilience_score,
        hubs: s.selected_warehouse_ids.length,
        name: s.name,
        demand: s.demand_retained_pct,
        isActive: s.solution_id === activeId,
        isBaseline: s.is_baseline_cost_only,
      })),
    [frontier, activeId]
  );

  const sorted = useMemo(
    () =>
      [...frontier].sort((a, b) =>
        sort === 'cost' ? a.total_cost - b.total_cost : b.resilience_score - a.resilience_score
      ),
    [frontier, sort]
  );

  if (!frontier.length) {
    return (
      <Card>
        <EmptyState
          icon={<GitCompare className="h-5 w-5" />}
          title="No options yet"
          body="Once a plan runs, every worthwhile way to build it shows up here."
        />
      </Card>
    );
  }

  const premium = active && baseline ? active.total_cost - baseline.total_cost : 0;
  const gain = active && baseline ? (active.resilience_score - baseline.resilience_score) * 100 : 0;

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        {/* the curve */}
        <Card>
          <CardHeader
            title="Your options"
            subtitle={`${frontier.length} ways to build this. Further right costs more; higher up copes better with problems. Click one to use it.`}
          />
          <div className="mt-4 h-[19rem]">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 8, right: 12, bottom: 24, left: 8 }}>
                <CartesianGrid stroke="rgb(var(--c-line))" strokeDasharray="3 4" vertical={false} />
                <XAxis
                  type="number"
                  dataKey="cost"
                  name="Annual cost"
                  domain={['dataMin - 40000', 'dataMax + 40000']}
                  tickFormatter={(v) => usdShort(v)}
                  tick={{ fontSize: 10, fill: 'rgb(var(--c-faint))' }}
                  axisLine={{ stroke: 'rgb(var(--c-line))' }}
                  tickLine={false}
                  label={{
                    value: 'Cost a year',
                    position: 'insideBottom',
                    offset: -12,
                    style: { fontSize: 10, fill: 'rgb(var(--c-faint))' },
                  }}
                />
                <YAxis
                  type="number"
                  dataKey="resilience"
                  name="Resilience"
                  domain={['dataMin - 0.02', 'dataMax + 0.02']}
                  tickFormatter={(v) => v.toFixed(2)}
                  tick={{ fontSize: 10, fill: 'rgb(var(--c-faint))' }}
                  axisLine={{ stroke: 'rgb(var(--c-line))' }}
                  tickLine={false}
                  width={44}
                  label={{
                    value: 'Safety score',
                    angle: -90,
                    position: 'insideLeft',
                    offset: 14,
                    style: { fontSize: 10, fill: 'rgb(var(--c-faint))' },
                  }}
                />
                <ZAxis type="number" dataKey="hubs" range={[60, 260]} />
                <Tooltip cursor={{ strokeDasharray: '3 3', stroke: 'rgb(var(--c-line-strong))' }} content={<PointTip />} />
                <Scatter data={points} onClick={(p: any) => p?.id && onSelect(p.id)} cursor="pointer">
                  {points.map((p) => (
                    <Cell
                      key={p.id}
                      fill={
                        p.isActive
                          ? 'rgb(var(--c-accent))'
                          : p.isBaseline
                            ? 'rgb(var(--c-warn))'
                            : 'rgb(var(--c-line-strong))'
                      }
                      fillOpacity={p.isActive ? 1 : p.isBaseline ? 0.85 : 0.6}
                      stroke={p.isActive ? 'rgb(var(--c-accent))' : 'transparent'}
                      strokeWidth={p.isActive ? 8 : 0}
                      strokeOpacity={0.18}
                    />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-4 border-t border-line pt-3">
            <LegendDot className="bg-accent" label="Your plan" />
            <LegendDot className="bg-warn" label="Cheapest" />
            <LegendDot className="bg-strong" label="Other options" />
            <span className="ml-auto text-2xs text-faint">Bigger dot = more warehouses</span>
          </div>
        </Card>

        {/* the premium */}
        <Card>
          <CardHeader
            title="What extra safety costs"
            subtitle="Your plan next to the cheapest one we found."
          />
          {baseline && active && (
            <div className="mt-5 space-y-4">
              <CompareRow
                label="Cheapest"
                sub={`${baseline.selected_warehouse_ids.length} warehouses`}
                cost={baseline.total_cost}
                resilience={baseline.resilience_score}
                tone="warn"
              />
              <CompareRow
                label="Your plan"
                sub={`${active.selected_warehouse_ids.length} warehouses`}
                cost={active.total_cost}
                resilience={active.resilience_score}
                tone="accent"
              />
              {best && best.solution_id !== active.solution_id && (
                <CompareRow
                  label="Safest available"
                  sub={`${best.selected_warehouse_ids.length} warehouses`}
                  cost={best.total_cost}
                  resilience={best.resilience_score}
                  tone="neutral"
                  action={
                    <Button variant="secondary" size="sm" onClick={() => onSelect(best.solution_id)} disabled={busy}>
                      Switch
                    </Button>
                  }
                />
              )}

              <div className="rounded-lg border border-line bg-sunken p-4">
                {premium > 0 ? (
                  <p className="text-xs leading-relaxed text-muted">
                    The active plan costs{' '}
                    <span className="num font-semibold text-ink">{usd(premium)}</span> more a year
                    than the cheapest option — a{' '}
                    <span className="num font-semibold text-ink">
                      {pct((premium / baseline.total_cost) * 100)}
                    </span>{' '}
                    premium — and buys{' '}
                    <span className="num font-semibold text-accent">
                      {gain >= 0 ? '+' : ''}
                      {gain.toFixed(1)}
                    </span>{' '}
                    points of resilience.
                  </p>
                ) : premium < 0 ? (
                  <p className="text-xs leading-relaxed text-muted">
                    The active plan is{' '}
                    <span className="num font-semibold text-accent">{usd(Math.abs(premium))}</span>{' '}
                    cheaper a year than the baseline.
                  </p>
                ) : (
                  <p className="text-xs leading-relaxed text-muted">
                    The active plan is the cost-only baseline. Nothing has been spent on shielding the
                    network from disruption yet.
                  </p>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* full list */}
      <Card flush>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <CardHeader title="All options" subtitle="Each row is a different set of warehouses." />
          <Segmented<Sort>
            value={sort}
            onChange={setSort}
            options={[
              { value: 'cost', label: 'Cheapest first' },
              { value: 'resilience', label: 'Safest first' },
            ]}
          />
        </div>
        <div className="max-h-[28rem] overflow-y-auto">
          <ul className="divide-y divide-line">
            {sorted.map((s) => (
              <PlanRow
                key={s.solution_id}
                solution={s}
                active={s.solution_id === activeId}
                onSelect={() => onSelect(s.solution_id)}
                busy={busy}
              />
            ))}
          </ul>
        </div>
      </Card>
    </div>
  );
};

/* ---------------------------------------------------------------- pieces */

const PlanRow: React.FC<{
  solution: NetworkSolution;
  active: boolean;
  onSelect: () => void;
  busy?: boolean;
}> = ({ solution: s, active, onSelect, busy }) => (
  <li>
    <button
      onClick={onSelect}
      disabled={busy || active}
      className={cn(
        'grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-5 py-3.5 text-left transition-colors sm:grid-cols-[minmax(0,1fr)_repeat(4,minmax(0,auto))]',
        active ? 'bg-accent-soft' : 'hover:bg-sunken disabled:cursor-default'
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className={cn('h-7 w-1 shrink-0 rounded-full', active ? 'bg-accent' : 'bg-line')} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn('truncate text-[13px] font-medium', active ? 'text-accent' : 'text-ink')}>
              {s.name}
            </span>
            {s.is_baseline_cost_only && <Badge tone="warn">cheapest</Badge>}
            {active && <Badge tone="accent">using this</Badge>}
          </div>
          <p className="mt-0.5 truncate text-2xs text-faint">
            {s.selected_warehouse_ids.length} warehouses
          </p>
        </div>
      </div>
      <Cellv label="Cost a year" value={usdShort(s.total_cost)} />
      <Cellv label="Safety" value={score(s.resilience_score)} />
      <Cellv label="On time" value={pct(s.demand_retained_pct, 0)} />
      <Cellv label="Recovery cost" value={s.normalized_recovery_cost.toFixed(2)} />
    </button>
  </li>
);

const Cellv: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="hidden text-right sm:block">
    <div className="text-2xs text-faint">{label}</div>
    <div className="num text-xs font-medium text-ink">{value}</div>
  </div>
);

const CompareRow: React.FC<{
  label: string;
  sub: string;
  cost: number;
  resilience: number;
  tone: 'accent' | 'warn' | 'neutral';
  action?: React.ReactNode;
}> = ({ label, sub, cost, resilience, tone, action }) => (
  <div className="flex items-center gap-3 rounded-lg border border-line px-3.5 py-3">
    <span
      className={cn(
        'h-8 w-1 shrink-0 rounded-full',
        tone === 'accent' ? 'bg-accent' : tone === 'warn' ? 'bg-warn' : 'bg-line'
      )}
    />
    <div className="min-w-0 flex-1">
      <div className="truncate text-xs font-medium text-ink">{label}</div>
      <div className="text-2xs text-faint">{sub}</div>
    </div>
    <div className="text-right">
      <div className="num text-xs font-medium text-ink">{usdShort(cost)}</div>
      <div className="num text-2xs text-muted">{score(resilience)}</div>
    </div>
    {action}
  </div>
);

const PointTip: React.FC<any> = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const p: Point = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2.5 shadow-pop">
      <p className="max-w-[14rem] truncate text-2xs font-semibold text-ink">{p.name}</p>
      <dl className="mt-1.5 space-y-0.5">
        <TipRow k="Cost a year" v={usd(p.cost)} />
        <TipRow k="Safety score" v={score(p.resilience)} />
        <TipRow k="Orders on time" v={pct(p.demand, 0)} />
        <TipRow k="Warehouses" v={num(p.hubs)} />
      </dl>
      {!p.isActive && <p className="mt-1.5 text-2xs text-accent">Click to activate</p>}
    </div>
  );
};

const TipRow: React.FC<{ k: string; v: string }> = ({ k, v }) => (
  <div className="flex items-baseline justify-between gap-4">
    <dt className="text-2xs text-faint">{k}</dt>
    <dd className="num text-2xs font-medium text-ink">{v}</dd>
  </div>
);

const LegendDot: React.FC<{ className: string; label: string }> = ({ className, label }) => (
  <span className="inline-flex items-center gap-1.5 text-2xs text-muted">
    <span className={cn('h-2 w-2 rounded-full', className)} />
    {label}
  </span>
);

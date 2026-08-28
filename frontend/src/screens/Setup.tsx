import React, { useMemo, useState } from 'react';
import {
  ArrowRight,
  Building2,
  Check,
  ChevronDown,
  MapPin,
  Search,
  Truck,
  Users,
} from 'lucide-react';
import { Badge, Button, Card, CardHeader, Segmented, cn } from '../components/ui';
import { FileDrop } from '../components/FileDrop';
import { RegionPreview } from '../panels/RegionPreview';
import {
  checkCoordinate,
  coordRowsToText,
  parseCoordinateLines,
  type CoordRow,
  type HubFeasibility,
} from '../lib/domain';
import { num, usd } from '../lib/format';
import type {
  CustomerInput,
  InputSpec,
  OptimizationPreference,
  RegionInfo,
  RunParams,
  SupplierInput,
} from '../types';

/**
 * Input affordances only. These are starting points for a number the person is
 * choosing; none of them describes anything about the backend, and the defaults
 * come from whatever InputSpec the server reports.
 */
const SLA_CHOICES = [30, 45, 60, 90, 120];
const COVERAGE_CHOICES = [80, 90, 95, 99];
const BUDGET_CHOICES = [1_000_000, 2_500_000, 4_000_000, 6_000_000];
const HUB_CHOICES = [2, 3, 4, 5, 6, 7];

const PREFERENCES: {
  id: OptimizationPreference;
  title: string;
  body: string;
}[] = [
  {
    id: 'cost',
    title: 'Minimize Cost',
    body: 'Recommend the cheapest design on the frontier, however exposed it is.',
  },
  {
    id: 'balanced',
    title: 'Balance Cost & Resilience',
    body: 'Recommend a design that holds up under disruption without overspending.',
  },
  {
    id: 'resilience',
    title: 'Maximize Resilience',
    body: 'Recommend the design that copes best, and show what that costs.',
  },
];

type SiteSource = 'region' | 'own';
type NodeSource = 'region' | 'own';

export interface SetupProps {
  region: RegionInfo | null;
  defaults?: InputSpec | null;
  previous?: Partial<RunParams> | null;
  feasibility?: HubFeasibility | null;
  busy?: boolean;
  onAnalyze: (params: Partial<RunParams>) => void;
  /** Opens the standalone site screening tool. */
  onScreenSites?: () => void;
}

/**
 * Everything a run needs, on one page: where, what it has to achieve, and what
 * it is built from. Anything the backend can work out for itself stays folded
 * away until it is asked for.
 */
export const Setup: React.FC<SetupProps> = ({
  region,
  defaults,
  previous,
  feasibility,
  busy,
  onAnalyze,
  onScreenSites,
}) => {
  const seed = defaults ?? region?.defaults ?? null;

  const [name, setName] = useState(previous?.region_name ?? seed?.region_name ?? '');
  const [sla, setSla] = useState(previous?.service_radius_minutes ?? seed?.service_radius_minutes ?? 60);
  const [coverage, setCoverage] = useState(
    previous?.min_demand_coverage_pct ?? seed?.min_demand_coverage_pct ?? 90
  );
  const [budget, setBudget] = useState(previous?.budget_limit_usd ?? seed?.budget_limit_usd ?? 2_500_000);
  const [hubs, setHubs] = useState(previous?.target_warehouses ?? seed?.target_warehouses_to_open ?? 4);
  const [preference, setPreference] = useState<OptimizationPreference>(
    previous?.optimization_preference ?? seed?.optimization_preference ?? 'balanced'
  );

  const [siteSource, setSiteSource] = useState<SiteSource>(
    previous?.custom_sites?.length ? 'own' : 'region'
  );
  const [siteText, setSiteText] = useState(
    (previous?.custom_sites ?? [])
      .map((c) => [c.name, c.lat, c.lon].filter(Boolean).join(', '))
      .join('\n')
  );
  const [supplierSource, setSupplierSource] = useState<NodeSource>('region');
  const [supplierRows, setSupplierRows] = useState<CoordRow[]>([]);
  const [customerSource, setCustomerSource] = useState<NodeSource>('region');
  const [customerRows, setCustomerRows] = useState<CoordRow[]>([]);
  const [advanced, setAdvanced] = useState(false);

  const parsedSites = useMemo(() => parseCoordinateLines(siteText), [siteText]);
  const usingOwnSites = siteSource === 'own' && parsedSites.valid.length > 0;

  // Mireye answers for US coordinates only, and a dropped minus sign on
  // longitude is by far the most common way to fall outside that.
  const coordIssues = useMemo(
    () =>
      parsedSites.valid
        .map((c) => ({ site: c, issue: checkCoordinate(c.lat, c.lon) }))
        .filter((r) => r.issue !== null) as {
        site: CoordRow;
        issue: NonNullable<ReturnType<typeof checkCoordinate>>;
      }[],
    [parsedSites]
  );

  // Opening more hubs than there are sites is impossible; keep the request honest
  // rather than letting the backend silently clamp it.
  const effectiveHubs = usingOwnSites ? Math.min(hubs, parsedSites.valid.length) : hubs;

  const supplierCount = supplierSource === 'own' ? supplierRows.length : region?.suppliers.length ?? 0;
  const customerCount = customerSource === 'own' ? customerRows.length : region?.customers.length ?? 0;
  const siteCount = usingOwnSites
    ? parsedSites.valid.length
    : region?.candidate_warehouses.length ?? 0;

  const blocked =
    !name.trim() ||
    coordIssues.length > 0 ||
    (siteSource === 'own' && parsedSites.valid.length === 0) ||
    (supplierSource === 'own' && supplierRows.length === 0) ||
    (customerSource === 'own' && customerRows.length === 0);

  const submit = () => {
    if (blocked) return;
    const params: Partial<RunParams> = {
      region_name: name.trim(),
      target_warehouses: effectiveHubs,
      service_radius_minutes: sla,
      budget_limit_usd: budget,
      optimization_preference: preference,
      min_demand_coverage_pct: coverage,
    };
    if (usingOwnSites) params.custom_sites = parsedSites.valid;
    if (supplierSource === 'own' && supplierRows.length) {
      params.custom_suppliers = supplierRows.map<SupplierInput>((r) => ({
        name: r.name,
        lat: r.lat,
        lon: r.lon,
        capacity_units: r.capacity_units,
        unit_supply_cost: r.unit_supply_cost,
      }));
    }
    if (customerSource === 'own' && customerRows.length) {
      params.custom_customers = customerRows.map<CustomerInput>((r) => ({
        name: r.name,
        lat: r.lat,
        lon: r.lon,
        demand_units: r.demand_units,
        service_sla_minutes: r.service_sla_minutes,
        priority: r.priority,
      }));
    }
    onAnalyze(params);
  };

  return (
    <div className="space-y-6">
      <header className="animate-fade-up">
        <h1 className="font-display text-[1.75rem] font-medium leading-tight tracking-tight text-ink sm:text-[2rem]">
          Create Your Logistics Network
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          Three things: where the network goes, what it has to achieve, and what it is built from.
          Everything else OptiFlow works out for itself.
        </p>
      </header>

      {/* -------------------------------------------------------- 1. where */}
      <Card className="animate-fade-up [animation-delay:40ms]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <CardHeader
            title="Where are you designing your network?"
            subtitle="Suppliers, demand zones and hazard layers come from the region the server has loaded."
          />
          <Badge tone="neutral">step 1</Badge>
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
          <div className="space-y-4">
            <label className="block">
              <span className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
                Region
              </span>
              <div className="relative mt-2">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Name this network"
                  className="w-full rounded-xl border border-line bg-surface py-3 pl-9 pr-3 font-display text-base text-ink shadow-card outline-none transition-colors placeholder:text-faint focus:border-accent/50 focus:ring-4 focus:ring-accent/10"
                />
              </div>
            </label>

            {region && (
              <button
                onClick={() => setName(region.region_name)}
                className={cn(
                  'flex w-full items-start gap-2.5 rounded-xl border p-3.5 text-left transition-all focus-ring',
                  name === region.region_name
                    ? 'border-accent bg-accent-soft'
                    : 'border-line bg-surface hover:border-strong hover:bg-sunken'
                )}
              >
                <span
                  className={cn(
                    'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                    name === region.region_name ? 'border-accent bg-accent' : 'border-strong'
                  )}
                >
                  {name === region.region_name && <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />}
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
                    <MapPin className="h-3.5 w-3.5 text-accent" />
                    {region.region_name}
                  </span>
                  <span className="num mt-1 block text-2xs leading-relaxed text-muted">
                    {region.bounding_box.length === 4
                      ? `${region.bounding_box[0].toFixed(2)}, ${region.bounding_box[1].toFixed(2)} → ${region.bounding_box[2].toFixed(2)}, ${region.bounding_box[3].toFixed(2)}`
                      : 'bounds unavailable'}
                  </span>
                  <span className="mt-1.5 block text-2xs leading-relaxed text-muted">
                    {region.customers.length} demand zones · {region.suppliers.length} suppliers ·{' '}
                    {region.candidate_warehouses.length} candidate sites ·{' '}
                    {region.hazard_zones.length} hazard zones
                  </span>
                </span>
              </button>
            )}

            <p className="text-2xs leading-relaxed text-faint">
              Geospatial answers cover US coordinates only. To design somewhere else, supply your
              own sites, suppliers and demand zones below.
            </p>
          </div>

          <RegionPreview
            region={region}
            customSites={usingOwnSites ? parsedSites.valid : []}
            usingCustomSites={usingOwnSites}
          />
        </div>
      </Card>

      {/* ------------------------------------------------- 2. requirements */}
      <Card className="animate-fade-up [animation-delay:80ms]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <CardHeader
            title="What does this network have to achieve?"
            subtitle="These become the constraints the optimiser works to and the critic audits."
          />
          <Badge tone="neutral">step 2</Badge>
        </div>

        <div className="mt-5 grid gap-6 lg:grid-cols-3">
          <Field
            label="Maximum delivery time"
            hint="The drive time you want from a warehouse to a demand zone."
          >
            <div className="flex flex-wrap gap-2">
              {SLA_CHOICES.map((v) => (
                <Chip key={v} selected={sla === v} onClick={() => setSla(v)}>
                  {v} min
                </Chip>
              ))}
            </div>
          </Field>

          <Field
            label="Minimum demand coverage"
            hint="The share of demand that must arrive inside that window."
          >
            <div className="flex flex-wrap gap-2">
              {COVERAGE_CHOICES.map((v) => (
                <Chip key={v} selected={coverage === v} onClick={() => setCoverage(v)}>
                  {v}%
                </Chip>
              ))}
              <Chip selected={coverage === 0} onClick={() => setCoverage(0)}>
                No requirement
              </Chip>
            </div>
          </Field>

          <Field label="Budget" hint="Running costs plus transport, for one year.">
            <div className="flex flex-wrap gap-2">
              {BUDGET_CHOICES.map((v) => (
                <Chip key={v} selected={budget === v} onClick={() => setBudget(v)}>
                  {usd(v)}
                </Chip>
              ))}
            </div>
          </Field>
        </div>

        <div className="mt-7 border-t border-line pt-5">
          <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
            Optimization preference
          </p>
          <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
            {PREFERENCES.map((p) => (
              <button
                key={p.id}
                onClick={() => setPreference(p.id)}
                className={cn(
                  'flex flex-col items-start gap-1.5 rounded-xl border p-4 text-left transition-all duration-150 focus-ring',
                  preference === p.id
                    ? 'border-accent bg-accent-soft shadow-card'
                    : 'border-line bg-surface hover:border-strong hover:bg-sunken'
                )}
              >
                <span className="flex items-center gap-2">
                  <span
                    className={cn(
                      'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                      preference === p.id ? 'border-accent bg-accent' : 'border-strong'
                    )}
                  >
                    {preference === p.id && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
                  </span>
                  <span
                    className={cn(
                      'text-[13px] font-medium',
                      preference === p.id ? 'text-accent' : 'text-ink'
                    )}
                  >
                    {p.title}
                  </span>
                </span>
                <span className="text-xs leading-relaxed text-muted">{p.body}</span>
              </button>
            ))}
          </div>
          <p className="mt-2.5 text-2xs leading-relaxed text-faint">
            The full frontier is built either way. This only decides which design is recommended
            first — you can move along the curve afterwards.
          </p>
        </div>
      </Card>

      {/* --------------------------------------------------- 3. what it is built from */}
      <Card className="animate-fade-up [animation-delay:120ms]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <CardHeader
            title="What is it built from?"
            subtitle="Anything you do not supply comes from the loaded region."
          />
          <Badge tone="neutral">step 3</Badge>
        </div>

        <div className="mt-5 space-y-4">
          <SourceBlock
            icon={<Building2 className="h-4 w-4" />}
            title="Warehouse candidates"
            count={siteCount}
            unit="sites"
            source={siteSource}
            onSource={setSiteSource}
            regionLabel={`Generate from the region (${region?.candidate_warehouses.length ?? 0} sites)`}
            ownLabel="Upload or type my own"
          >
            <FileDrop
              className="mb-4"
              onRows={(rows) =>
                setSiteText((cur) => {
                  const merged = coordRowsToText(rows);
                  return cur.trim() ? `${cur.trim()}\n${merged}` : merged;
                })
              }
            />
            <label className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
              Or type them, one per line
            </label>
            <p className="mt-1 text-2xs text-muted">
              <span className="num font-mono text-ink">lat, lon</span> ·{' '}
              <span className="num font-mono text-ink">name, lat, lon</span> ·{' '}
              <span className="num font-mono text-ink">name, lat, lon, capacity, cost</span>
            </p>
            <textarea
              value={siteText}
              onChange={(e) => setSiteText(e.target.value)}
              rows={4}
              placeholder={'Kent Valley, 47.4124, -122.2415\n47.5751, -122.3341'}
              className="num mt-2.5 w-full resize-y rounded-lg border border-line bg-sunken px-3 py-2.5 font-mono text-xs text-ink outline-none focus:border-accent/50 focus:ring-4 focus:ring-accent/10"
            />
            <div className="mt-2.5 flex flex-wrap items-center gap-3 text-2xs">
              <span className={cn(parsedSites.valid.length ? 'text-accent' : 'text-faint')}>
                {parsedSites.valid.length} site{parsedSites.valid.length === 1 ? '' : 's'} recognised
              </span>
              {parsedSites.invalidLines.length > 0 && (
                <span className="text-danger">
                  line{parsedSites.invalidLines.length === 1 ? '' : 's'}{' '}
                  {parsedSites.invalidLines.join(', ')} could not be read
                </span>
              )}
              {onScreenSites && (
                <button
                  onClick={onScreenSites}
                  className="ml-auto font-medium text-accent underline-offset-4 hover:underline focus-ring"
                >
                  Screen sites individually first
                </button>
              )}
            </div>
            {coordIssues.length > 0 && (
              <div className="mt-3 rounded-lg border border-warn/30 bg-warn-soft px-3.5 py-3">
                <p className="text-2xs font-medium uppercase tracking-[0.08em] text-warn">
                  {coordIssues.length} location{coordIssues.length === 1 ? '' : 's'} outside coverage
                </p>
                <ul className="mt-2 space-y-1.5">
                  {coordIssues.slice(0, 4).map(({ site, issue }, i) => (
                    <li key={i} className="text-xs leading-relaxed text-ink">
                      <span className="num font-mono text-2xs text-muted">
                        {site.name ? `${site.name} ` : ''}
                        {site.lat}, {site.lon}
                      </span>{' '}
                      — {issue.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </SourceBlock>

          <SourceBlock
            icon={<Truck className="h-4 w-4" />}
            title="Suppliers"
            count={supplierCount}
            unit="origins"
            source={supplierSource}
            onSource={setSupplierSource}
            regionLabel={`Use the region (${region?.suppliers.length ?? 0} suppliers)`}
            ownLabel="Upload my own"
          >
            <FileDrop onRows={(rows) => setSupplierRows(rows)} />
            <p className="mt-3 text-2xs leading-relaxed text-muted">
              Columns read by name:{' '}
              <span className="num font-mono text-ink">name, lat, lon, capacity, unit_supply_cost</span>.
              {supplierRows.length > 0 && (
                <>
                  {' '}
                  <span className="text-accent">
                    {supplierRows.length} supplier{supplierRows.length === 1 ? '' : 's'} loaded.
                  </span>
                </>
              )}
            </p>
          </SourceBlock>

          <SourceBlock
            icon={<Users className="h-4 w-4" />}
            title="Customers"
            count={customerCount}
            unit="zones"
            source={customerSource}
            onSource={setCustomerSource}
            regionLabel={`Use the region (${region?.customers.length ?? 0} demand zones)`}
            ownLabel="Upload my own"
          >
            <FileDrop onRows={(rows) => setCustomerRows(rows)} />
            <p className="mt-3 text-2xs leading-relaxed text-muted">
              Columns read by name:{' '}
              <span className="num font-mono text-ink">name, lat, lon, demand, sla, priority</span>.
              Any zone without its own window uses the delivery time set above.
              {customerRows.length > 0 && (
                <>
                  {' '}
                  <span className="text-accent">
                    {customerRows.length} zone{customerRows.length === 1 ? '' : 's'} loaded
                    {customerRows.some((r) => r.demand_units == null)
                      ? ' — rows without a demand column will use the server default.'
                      : '.'}
                  </span>
                </>
              )}
            </p>
          </SourceBlock>
        </div>

        {/* ------------------------------------------- advanced, folded away */}
        <div className="mt-5 border-t border-line pt-4">
          <button
            onClick={() => setAdvanced((v) => !v)}
            className="flex items-center gap-1.5 text-xs font-medium text-muted transition-colors hover:text-ink focus-ring"
          >
            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', advanced && 'rotate-180')} />
            Advanced configuration
          </button>

          {advanced && (
            <div className="mt-4 animate-fade-in">
              <Field
                label="Warehouses this plan may open"
                hint="The most the optimiser is allowed to open. It may open fewer if fewer will do."
              >
                <div className="flex flex-wrap gap-2">
                  {HUB_CHOICES.filter(
                    (n) => !usingOwnSites || n <= parsedSites.valid.length
                  ).map((n) => {
                    // Capacity from the last run rules a count out; it never promises one works.
                    const short =
                      feasibility && feasibility.siteCount > 0
                        ? feasibility.capacityAt(n) < feasibility.totalDemand
                        : false;
                    return (
                      <Chip
                        key={n}
                        selected={effectiveHubs === n}
                        tone={short ? 'warn' : 'accent'}
                        onClick={() => setHubs(n)}
                      >
                        {n}
                        {short ? ' (short)' : ''}
                      </Chip>
                    );
                  })}
                </div>
                {feasibility && feasibility.siteCount > 0 && (
                  <p className="mt-2.5 text-2xs leading-relaxed text-muted">
                    In the last run the largest {effectiveHubs} of {feasibility.siteCount} qualifying
                    sites held{' '}
                    <span className="num font-medium text-ink">
                      {num(feasibility.capacityAt(effectiveHubs))}
                    </span>{' '}
                    units against{' '}
                    <span className="num font-medium text-ink">{num(feasibility.totalDemand)}</span>{' '}
                    of demand.
                  </p>
                )}
              </Field>
            </div>
          )}
        </div>
      </Card>

      {/* ------------------------------------------------------------ run */}
      <div className="sticky bottom-4 z-10 animate-fade-up [animation-delay:160ms]">
        <div className="flex flex-wrap items-center gap-4 rounded-xl border border-line bg-surface/95 p-4 shadow-lift backdrop-blur">
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-medium text-ink">
              {siteCount} candidate site{siteCount === 1 ? '' : 's'} · {customerCount} demand zone
              {customerCount === 1 ? '' : 's'} · {supplierCount} supplier
              {supplierCount === 1 ? '' : 's'}
            </p>
            <p className="mt-0.5 text-2xs leading-relaxed text-muted">
              {blocked
                ? !name.trim()
                  ? 'Name the network to continue.'
                  : coordIssues.length > 0
                    ? 'Fix the coordinates outside coverage to continue.'
                    : 'Add the data you chose to supply, or switch that section back to the region.'
                : `Every site is checked for terrain, land cover and flood exposure, then real drive times are measured. This takes a few minutes.`}
            </p>
          </div>
          <Button variant="primary" size="lg" onClick={submit} disabled={blocked} loading={busy}>
            Analyze Network
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
};

/* ---------------------------------------------------------------- pieces */

const Field: React.FC<{ label: string; hint: string; children: React.ReactNode }> = ({
  label,
  hint,
  children,
}) => (
  <div>
    <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</p>
    <p className="mt-1 text-2xs leading-relaxed text-muted">{hint}</p>
    <div className="mt-3">{children}</div>
  </div>
);

const Chip: React.FC<{
  selected: boolean;
  onClick: () => void;
  tone?: 'accent' | 'warn';
  children: React.ReactNode;
}> = ({ selected, onClick, tone = 'accent', children }) => (
  <button
    onClick={onClick}
    className={cn(
      'num inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium transition-all duration-150 focus-ring',
      selected
        ? tone === 'warn'
          ? 'border-warn bg-warn-soft text-warn shadow-card'
          : 'border-accent bg-accent-soft text-accent shadow-card'
        : 'border-line bg-surface text-ink hover:border-strong hover:bg-sunken'
    )}
  >
    {selected && <Check className="h-3 w-3" strokeWidth={3} />}
    {children}
  </button>
);

const SourceBlock: React.FC<{
  icon: React.ReactNode;
  title: string;
  count: number;
  unit: string;
  source: NodeSource;
  onSource: (v: NodeSource) => void;
  regionLabel: string;
  ownLabel: string;
  children: React.ReactNode;
}> = ({ icon, title, count, unit, source, onSource, regionLabel, ownLabel, children }) => (
  <div className="rounded-xl border border-line bg-sunken/50 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg border border-line bg-surface text-muted">
          {icon}
        </span>
        <div>
          <p className="text-[13px] font-medium text-ink">{title}</p>
          <p className="num text-2xs text-muted">
            {count} {unit}
          </p>
        </div>
      </div>
      <Segmented<NodeSource>
        value={source}
        onChange={onSource}
        options={[
          { value: 'region', label: regionLabel },
          { value: 'own', label: ownLabel },
        ]}
      />
    </div>
    {source === 'own' && (
      <div className="mt-4 animate-fade-in rounded-lg border border-line bg-surface p-4">
        {children}
      </div>
    )}
  </div>
);

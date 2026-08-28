import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ClipboardPaste, MapPin, Play, Plus, TriangleAlert, Trophy, X } from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, Meter, Spinner, cn } from '../components/ui';
import { DataSourceBanner } from '../components/DataSourceBanner';
import { FileDrop } from '../components/FileDrop';
import { checkCoordinate, type CoordRow } from '../lib/domain';
import { evaluateSites } from '../services/api';
import { num, usd, usdShort } from '../lib/format';
import type { EvaluatedSite, EvaluateSitesResponse, ScoreComponent, SiteInput } from '../types';

const STORAGE_KEY = 'optiflow-site-check-rows';

interface Row {
  key: string;
  name: string;
  lat: string;
  lon: string;
  capacity: string;
  cost: string;
}

const COMPONENT_LABEL: Record<ScoreComponent, string> = {
  hazard_headroom: 'Hazard headroom',
  slope_headroom: 'Slope headroom',
  parcel_adequacy: 'Parcel adequacy',
  capacity_share: 'Capacity share',
};

const blankRow = (): Row => ({
  key: Math.random().toString(36).slice(2),
  name: '',
  lat: '',
  lon: '',
  capacity: '',
  cost: '',
});

function loadRows(): Row[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length) return parsed;
    }
  } catch {
    /* storage unavailable */
  }
  return [blankRow(), blankRow()];
}

/**
 * Parses pasted lines. Accepts, per line:
 *   lat, lon
 *   name, lat, lon
 *   name, lat, lon, capacity, cost
 * Separators may be commas, tabs or runs of spaces.
 */
function parsePasted(text: string): Row[] {
  const rows: Row[] = [];
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/\s*[,\t]\s*|\s{2,}/).filter(Boolean);
    if (parts.length < 2) continue;

    const isNum = (v: string) => v !== '' && !Number.isNaN(Number(v));
    let name = '';
    let rest = parts;

    if (!isNum(parts[0])) {
      name = parts[0];
      rest = parts.slice(1);
    }
    if (rest.length < 2 || !isNum(rest[0]) || !isNum(rest[1])) continue;

    rows.push({
      key: Math.random().toString(36).slice(2),
      name,
      lat: rest[0],
      lon: rest[1],
      capacity: isNum(rest[2] ?? '') ? rest[2] : '',
      cost: isNum(rest[3] ?? '') ? rest[3] : '',
    });
  }
  return rows;
}

export interface SiteCheckPanelProps {
  /** Runs the full pipeline against the sites that passed. */
  onOptimise: (sites: SiteInput[]) => void;
  regionName?: string;
  /** Told about each finished check so other screens can show it. */
  onResult?: (result: EvaluateSitesResponse) => void;
  /** Bump to discard entered rows and results, e.g. after a data reset. */
  resetToken?: number;
}

export const SiteCheckPanel: React.FC<SiteCheckPanelProps> = ({
  onOptimise,
  regionName,
  onResult,
  resetToken = 0,
}) => {
  const [rows, setRows] = useState<Row[]>(loadRows);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState('');
  const [result, setResult] = useState<EvaluateSitesResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
    } catch {
      /* ignore */
    }
  }, [rows]);

  // A reset wipes stored rows; drop what this panel is holding too.
  const firstRender = React.useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    setRows([blankRow(), blankRow()]);
    setResult(null);
    setError(null);
    setExpanded(null);
  }, [resetToken]);

  const valid = useMemo<SiteInput[]>(
    () =>
      rows
        .map((r, i) => {
          const lat = Number(r.lat);
          const lon = Number(r.lon);
          if (r.lat.trim() === '' || r.lon.trim() === '') return null;
          if (Number.isNaN(lat) || Number.isNaN(lon)) return null;
          if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
          const site: SiteInput = { name: r.name.trim() || `Site ${i + 1}`, lat, lon };
          if (r.capacity.trim() && !Number.isNaN(Number(r.capacity)))
            site.capacity_units = Number(r.capacity);
          if (r.cost.trim() && !Number.isNaN(Number(r.cost))) site.fixed_cost = Number(r.cost);
          return site;
        })
        .filter((s): s is SiteInput => s !== null),
    [rows]
  );

  const invalidCount = rows.filter(
    (r) => (r.lat.trim() !== '' || r.lon.trim() !== '') && !isRowValid(r)
  ).length;

  // Mireye answers for US coordinates only. Catch the common dropped-minus-sign
  // case here rather than letting strict mode reject the whole request.
  const coverage = useMemo(
    () =>
      rows
        .filter(isRowValid)
        .map((r) => ({ row: r, issue: checkCoordinate(Number(r.lat), Number(r.lon)) }))
        .filter((x) => x.issue !== null) as {
        row: Row;
        issue: NonNullable<ReturnType<typeof checkCoordinate>>;
      }[],
    [rows]
  );
  const fixable = coverage.filter((c) => c.issue.fix);

  const applyFixes = () =>
    setRows((rs) =>
      rs.map((r) => {
        const hit = fixable.find((f) => f.row.key === r.key);
        return hit?.issue.fix ? { ...r, lon: String(hit.issue.fix.lon) } : r;
      })
    );

  /** Append rows read out of an uploaded file, keeping anything already typed. */
  const addRows = React.useCallback((incoming: CoordRow[]) => {
    setRows((rs) => [
      ...rs.filter(isRowFilled),
      ...incoming.map((c) => ({
        key: Math.random().toString(36).slice(2),
        name: c.name ?? '',
        lat: String(c.lat),
        lon: String(c.lon),
        capacity: c.capacity_units != null ? String(c.capacity_units) : '',
        cost: c.fixed_cost != null ? String(c.fixed_cost) : '',
      })),
    ]);
  }, []);

  const update = (key: string, field: keyof Row, value: string) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, [field]: value } : r)));

  const run = useCallback(async () => {
    if (!valid.length) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await evaluateSites(valid);
      setResult(res);
      onResult?.(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Evaluation failed.');
    } finally {
      setBusy(false);
    }
  }, [valid, onResult]);

  const passedInputs: SiteInput[] = useMemo(
    () =>
      (result?.sites ?? [])
        .filter((s) => s.passed)
        .map((s) => ({
          id: s.id,
          name: s.name,
          lat: s.lat,
          lon: s.lon,
          capacity_units: s.capacity_units,
          fixed_cost: s.fixed_operating_cost,
        })),
    [result]
  );

  return (
    <div className="space-y-5">
      {/* input */}
      <Card>
        <CardHeader
          title="Check specific locations"
          subtitle={
            <>
              Enter coordinates and POST them to{' '}
              <span className="num font-mono">/api/evaluate-sites</span>. Each one is screened by the
              same Site and Risk agents the full pipeline uses, then ranked.
            </>
          }
          action={
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => setPasteOpen((v) => !v)}>
                <ClipboardPaste className="h-3.5 w-3.5" />
                Paste
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setRows((r) => [...r, blankRow()])}>
                <Plus className="h-3.5 w-3.5" />
                Add
              </Button>
            </div>
          }
        />

        <FileDrop className="mt-4" onRows={addRows} />

        {pasteOpen && (
          <div className="mt-4 rounded-xl border border-line bg-sunken p-3.5">
            <p className="text-2xs text-muted">
              One site per line. <span className="num font-mono text-ink">lat, lon</span> or{' '}
              <span className="num font-mono text-ink">name, lat, lon</span> or{' '}
              <span className="num font-mono text-ink">name, lat, lon, capacity, cost</span>
            </p>
            <textarea
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              rows={4}
              placeholder={'Kent Valley, 47.4124, -122.2415\n47.3073, -122.2285'}
              className="num mt-2.5 w-full resize-y rounded-lg border border-line bg-surface px-3 py-2 font-mono text-2xs text-ink outline-none focus:border-accent/50 focus:ring-4 focus:ring-accent/10"
            />
            <div className="mt-2.5 flex items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                disabled={!parsePasted(pasteText).length}
                onClick={() => {
                  const parsed = parsePasted(pasteText);
                  if (!parsed.length) return;
                  setRows((r) => [...r.filter(isRowFilled), ...parsed]);
                  setPasteText('');
                  setPasteOpen(false);
                }}
              >
                Add {parsePasted(pasteText).length || ''} site
                {parsePasted(pasteText).length === 1 ? '' : 's'}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setPasteOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[44rem] border-collapse text-left">
            <thead>
              <tr className="border-b border-line text-2xs uppercase tracking-[0.06em] text-faint">
                <th className="px-2 py-2 font-medium">Name</th>
                <th className="px-2 py-2 font-medium">Latitude</th>
                <th className="px-2 py-2 font-medium">Longitude</th>
                <th className="px-2 py-2 font-medium">Capacity</th>
                <th className="px-2 py-2 font-medium">Fixed cost</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const bad = (r.lat.trim() !== '' || r.lon.trim() !== '') && !isRowValid(r);
                return (
                  <tr key={r.key} className="border-b border-line/60">
                    <Cell>
                      <input
                        value={r.name}
                        onChange={(e) => update(r.key, 'name', e.target.value)}
                        placeholder={`Site ${i + 1}`}
                        className="w-full bg-transparent text-xs text-ink outline-none placeholder:text-faint"
                      />
                    </Cell>
                    <Cell>
                      <input
                        value={r.lat}
                        onChange={(e) => update(r.key, 'lat', e.target.value)}
                        placeholder="47.4124"
                        className={cn(
                          'num w-full bg-transparent font-mono text-xs outline-none placeholder:text-faint',
                          bad ? 'text-danger' : 'text-ink'
                        )}
                      />
                    </Cell>
                    <Cell>
                      <input
                        value={r.lon}
                        onChange={(e) => update(r.key, 'lon', e.target.value)}
                        placeholder="-122.2415"
                        className={cn(
                          'num w-full bg-transparent font-mono text-xs outline-none placeholder:text-faint',
                          bad ? 'text-danger' : 'text-ink'
                        )}
                      />
                    </Cell>
                    <Cell>
                      <input
                        value={r.capacity}
                        onChange={(e) => update(r.key, 'capacity', e.target.value)}
                        placeholder="20000"
                        className="num w-full bg-transparent font-mono text-xs text-ink outline-none placeholder:text-faint"
                      />
                    </Cell>
                    <Cell>
                      <input
                        value={r.cost}
                        onChange={(e) => update(r.key, 'cost', e.target.value)}
                        placeholder="130000"
                        className="num w-full bg-transparent font-mono text-xs text-ink outline-none placeholder:text-faint"
                      />
                    </Cell>
                    <Cell>
                      <button
                        onClick={() => setRows((rs) => (rs.length > 1 ? rs.filter((x) => x.key !== r.key) : rs))}
                        className="rounded p-1 text-faint transition-colors hover:bg-sunken hover:text-danger focus-ring"
                        aria-label="Remove row"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Cell>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {coverage.length > 0 && (
          <div className="mt-4 rounded-lg border border-warn/30 bg-warn-soft px-3.5 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-2xs font-medium uppercase tracking-[0.08em] text-warn">
                {coverage.length} location{coverage.length === 1 ? '' : 's'} outside Mireye coverage
              </p>
              {fixable.length > 0 && (
                <Button variant="secondary" size="sm" onClick={applyFixes}>
                  Fix {fixable.length === 1 ? 'it' : 'them'}
                </Button>
              )}
            </div>
            <ul className="mt-2 space-y-1.5">
              {coverage.slice(0, 5).map(({ row, issue }, i) => (
                <li key={i} className="text-xs leading-relaxed text-ink">
                  <span className="num font-mono text-2xs text-muted">
                    {row.name ? `${row.name} ` : ''}
                    {row.lat}, {row.lon}
                  </span>{' '}
                  &mdash; {issue.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            size="md"
            onClick={run}
            disabled={!valid.length || coverage.length > 0}
            loading={busy}
          >
            <MapPin className="h-3.5 w-3.5" />
            {busy ? 'Screening…' : `Evaluate ${valid.length || ''} site${valid.length === 1 ? '' : 's'}`}
          </Button>
          {invalidCount > 0 && (
            <span className="text-2xs text-danger">
              {invalidCount} row{invalidCount === 1 ? '' : 's'} with an invalid coordinate
            </span>
          )}
          {busy && (
            <span className="text-2xs text-muted">
              Roughly 3 lookups per site; this can take a few seconds each against a live key.
            </span>
          )}
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-danger/25 bg-danger-soft px-3.5 py-3">
            <p className="text-2xs font-medium uppercase tracking-[0.08em] text-danger">
              Evaluation stopped
            </p>
            <p className="mt-1 text-xs leading-relaxed text-ink">{error}</p>
          </div>
        )}
      </Card>

      {/* results */}
      {result && (
        <>
          <DataSourceBanner data={result.data_source} className="animate-fade-up" />

          <Card className="animate-fade-up">
            <CardHeader
              title="Result"
              subtitle={`${result.passed} of ${result.evaluated} locations are usable for a warehouse.`}
              action={
                passedInputs.length > 0 && (
                  <Button variant="secondary" size="sm" onClick={() => onOptimise(passedInputs)}>
                    <Play className="h-3.5 w-3.5" />
                    Optimise these {passedInputs.length}
                  </Button>
                )
              }
            />

            {result.best_blocked_reason && (
              <div className="mt-4 flex items-start gap-3.5 rounded-xl border border-warn/30 bg-warn-soft p-4">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warn text-white">
                  <TriangleAlert className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-2xs font-medium uppercase tracking-[0.08em] text-warn">
                    No site recommended
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-ink">
                    {result.best_blocked_reason}
                  </p>
                </div>
              </div>
            )}

            {result.best_site_id && (
              <div className="mt-4 flex items-start gap-3.5 rounded-xl border border-accent/30 bg-accent-soft p-4">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white">
                  <Trophy className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <p className="text-2xs font-medium uppercase tracking-[0.08em] text-accent">
                    Best of the {result.passed} that passed
                  </p>
                  <p className="mt-1 font-display text-lg font-medium leading-tight tracking-tight text-ink">
                    {result.sites.find((s) => s.id === result.best_site_id)?.name}
                  </p>
                  <p className="num mt-1 text-xs text-muted">
                    suitability{' '}
                    {result.sites.find((s) => s.id === result.best_site_id)?.suitability_score.toFixed(3)}
                  </p>
                </div>
              </div>
            )}

            {passedInputs.length > 0 && (
              <p className="mt-3 text-2xs leading-relaxed text-faint">
                Optimising runs the full pipeline with these sites in place of the region
                dataset&apos;s candidates. Customers, suppliers and hazards still come from
                {regionName ? ` ${regionName}` : ' the dataset'}.
              </p>
            )}

            <div className="mt-4 border-t border-line pt-4">
              <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
                Score weights returned by the backend
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {(Object.entries(result.weights) as [ScoreComponent, number][]).map(([k, v]) => (
                  <Badge key={k} tone="neutral">
                    {COMPONENT_LABEL[k]} {(v * 100).toFixed(0)}%
                  </Badge>
                ))}
              </div>
            </div>
          </Card>

          <div className="space-y-2.5">
            {result.sites.map((s) => (
              <SiteResultCard
                key={s.id}
                site={s}
                isBest={s.id === result.best_site_id}
                expanded={expanded === s.id}
                onToggle={() => setExpanded((c) => (c === s.id ? null : s.id))}
              />
            ))}
          </div>
        </>
      )}

      {!result && !busy && (
        <Card>
          <EmptyState
            icon={<MapPin className="h-5 w-5" />}
            title="No locations checked yet"
            body="Add coordinates above and evaluate them. Each site is judged against the same slope, elevation, parcel and hazard gates the full pipeline applies."
          />
        </Card>
      )}
    </div>
  );
};

/* ---------------------------------------------------------------- pieces */

const SiteResultCard: React.FC<{
  site: EvaluatedSite;
  isBest: boolean;
  expanded: boolean;
  onToggle: () => void;
}> = ({ site, isBest, expanded, onToggle }) => (
  <Card
    flush
    className={cn('animate-fade-up overflow-hidden', isBest && 'border-accent/40 shadow-lift')}
  >
    <button
      onClick={onToggle}
      className="flex w-full items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-sunken/60"
    >
      <span
        className={cn(
          'num flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-xs font-semibold',
          site.passed ? 'bg-accent text-white' : 'bg-danger-soft text-danger'
        )}
      >
        {site.rank ?? '—'}
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[13px] font-medium text-ink">{site.name}</span>
          {isBest && <Badge tone="accent">best</Badge>}
          <Badge tone={site.passed ? 'pass' : 'danger'}>{site.passed ? 'Suitable' : 'Not suitable'}</Badge>
          {!site.all_live && (
            <Badge tone="warn">
              simulated{' '}
              {Object.entries(site.layer_live)
                .filter(([, live]) => !live)
                .map(([layer]) => layer)
                .join(', ')}
            </Badge>
          )}
        </span>
        <span className="num mt-0.5 block truncate font-mono text-2xs text-faint">
          {site.lat.toFixed(4)}, {site.lon.toFixed(4)} · {site.land_cover}
        </span>
      </span>

      {site.passed ? (
        <span className="hidden w-40 shrink-0 sm:block">
          <span className="flex items-baseline justify-between">
            <span className="text-2xs text-faint">suitability</span>
            <span className="num text-xs font-medium text-ink">
              {site.suitability_score.toFixed(3)}
            </span>
          </span>
          <Meter value={site.suitability_score} tone="accent" className="mt-1" />
        </span>
      ) : (
        <span className="hidden max-w-[16rem] shrink-0 truncate text-2xs text-danger sm:block">
          {site.rejection_reasons[0]}
        </span>
      )}
    </button>

    {expanded && (
      <div className="grid animate-fade-in gap-6 border-t border-line bg-sunken px-5 py-5 lg:grid-cols-3">
        <div>
          <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">Verdict</p>
          {site.rejection_reasons.length > 0 ? (
            <ul className="mt-2.5 space-y-2">
              {site.rejection_reasons.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-xs leading-relaxed text-danger">
                  <X className="mt-0.5 h-3 w-3 shrink-0" strokeWidth={2.5} />
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2.5 text-xs leading-relaxed text-muted">
              Cleared every screening gate. Ranked #{site.rank} with a suitability score of{' '}
              <span className="num font-medium text-ink">{site.suitability_score.toFixed(3)}</span>.
            </p>
          )}
        </div>

        <div>
          <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
            Score components
          </p>
          {site.passed ? (
            <ul className="mt-2.5 space-y-2.5">
              {(Object.entries(site.score_components) as [ScoreComponent, number][]).map(([k, v]) => (
                <li key={k}>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-2xs text-muted">{COMPONENT_LABEL[k]}</span>
                    <span className="num text-2xs font-medium text-ink">{v.toFixed(3)}</span>
                  </div>
                  <Meter value={v} tone="accent" className="mt-1 h-1" />
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2.5 text-xs text-muted">Not scored — the site failed screening.</p>
          )}
        </div>

        <div>
          <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
            Values returned
          </p>
          <dl className="mt-2.5 divide-y divide-line rounded-lg border border-line bg-surface px-3">
            <Field k="terrain_slope_pct" v={site.terrain_slope_pct.toFixed(2)} />
            <Field k="elevation_m" v={num(site.elevation_m, 1)} />
            <Field k="parcel_area_sqm" v={num(site.parcel_area_sqm)} />
            <Field k="is_occupied" v={String(site.is_occupied)} />
            <Field k="flood_risk_score" v={site.flood_risk_score.toFixed(3)} />
            <Field k="composite_risk" v={site.composite_risk.toFixed(3)} />
            <Field k="capacity_units" v={num(site.capacity_units)} />
            <Field k="fixed_operating_cost" v={usdShort(site.fixed_operating_cost)} />
          </dl>
          {Object.keys(site.provenance ?? {}).length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {Object.entries(site.provenance).map(([layer, tag]) => (
                <Badge key={layer} tone={tag.live ? 'pass' : 'warn'}>
                  {layer} · {tag.source} · #{tag.response_hash?.slice(0, 6)}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>
    )}
  </Card>
);

const Cell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <td className="px-2 py-1.5">{children}</td>
);

const Field: React.FC<{ k: string; v: string }> = ({ k, v }) => (
  <div className="flex items-baseline justify-between gap-3 py-1.5">
    <dt className="num font-mono text-2xs text-faint">{k}</dt>
    <dd className="num truncate text-xs text-ink">{v}</dd>
  </div>
);

const isRowValid = (r: Row) => {
  const lat = Number(r.lat);
  const lon = Number(r.lon);
  return (
    r.lat.trim() !== '' &&
    r.lon.trim() !== '' &&
    !Number.isNaN(lat) &&
    !Number.isNaN(lon) &&
    lat >= -90 &&
    lat <= 90 &&
    lon >= -180 &&
    lon <= 180
  );
};

const isRowFilled = (r: Row) => r.lat.trim() !== '' || r.lon.trim() !== '' || r.name.trim() !== '';

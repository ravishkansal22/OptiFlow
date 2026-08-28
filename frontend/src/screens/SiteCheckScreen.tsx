import React from 'react';
import { ArrowLeft, Home as HomeIcon, LayoutGrid, Moon, Sun } from 'lucide-react';
import { Button, Mark } from '../components/ui';
import { SiteCheckPanel } from '../panels/SiteCheckPanel';
import { DataSourceBanner } from '../components/DataSourceBanner';
import type { Theme } from '../lib/theme';
import type { DataSource, EvaluateSitesResponse, SiteInput } from '../types';

export interface SiteCheckScreenProps {
  onBack: () => void;
  onOptimise: (sites: SiteInput[]) => void;
  regionName?: string;
  theme: Theme;
  onToggleTheme: () => void;
  dataSource?: DataSource | null;
  onReset?: () => void;
  resetting?: boolean;
  resetToken?: number;
  /** Present when a finished plan exists to return to. */
  onOpenPlan?: () => void;
  onResult?: (result: EvaluateSitesResponse) => void;
}

/** Standalone site check, for use before any network has been solved. */
export const SiteCheckScreen: React.FC<SiteCheckScreenProps> = ({
  onBack,
  onOptimise,
  regionName,
  theme,
  onToggleTheme,
  dataSource,
  onReset,
  resetting,
  resetToken,
  onOpenPlan,
  onResult,
}) => (
  <div className="min-h-[100dvh]">
    <header className="border-b border-line bg-canvas/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-5xl items-center gap-4 px-5 py-3 sm:px-8">
        <div className="flex items-center gap-2.5">
          <Mark />
          <span className="font-display text-base font-medium tracking-tight text-ink">OptiFlow</span>
          <span className="text-faint">/</span>
          <span className="text-xs text-muted">Check a location</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {onOpenPlan && (
            <Button variant="primary" size="sm" onClick={onOpenPlan}>
              <LayoutGrid className="h-3.5 w-3.5" />
              Open my network
            </Button>
          )}
          <Button variant="secondary" size="sm" onClick={onBack} title="Back to the control room">
            <HomeIcon className="h-3.5 w-3.5" />
            Home
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            className="px-2"
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </header>

    <main className="mx-auto max-w-5xl px-5 py-7 sm:px-8">
      <DataSourceBanner
        data={dataSource ?? null}
        onReset={onReset}
        resetting={resetting}
        className="mb-5"
      />

      <div className="mb-6">
        <h1 className="font-display text-2xl font-medium tracking-tight text-ink">
Is this a good place for a warehouse?
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
          Paste in as many map coordinates as you like. We check the same things for each one
          &mdash; how steep it is, how high, whether the land is free, and the flood risk &mdash;
          then rank them so the best one is obvious.
        </p>
      </div>
      <SiteCheckPanel
        onOptimise={onOptimise}
        regionName={regionName}
        resetToken={resetToken}
        onResult={onResult}
      />
    </main>
  </div>
);

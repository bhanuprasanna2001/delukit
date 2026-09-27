import { Download as DownloadIcon, Info } from "lucide-react";
import type { View } from "../App";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Tooltip } from "../components/ui/tooltip";
import { targetLabel, unitFor } from "../lib/api";
import { MAX_GAP, useExportForm } from "./useExportForm";

const GATE_INFO =
  "05:30 publishes all six forecast quantities for both horizons. 11:30 publishes price forecasts for both horizons using the later modeled input cutoff. Older runs remain available where published.";

const FORMAT_HINTS: Record<string, string> = {
  xlsx: "Excel workbook, one sheet.",
  csv: "Plain text, opens anywhere.",
  parquet: "Smallest, for Python and R.",
};

function Field({
  id,
  label,
  hint,
  info,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  info?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-w-0 content-start gap-1.5">
      <label htmlFor={id} className="flex items-center gap-1.5 text-sm font-medium">
        {label}
        {info}
      </label>
      {children}
      {hint ? <p className="text-xs leading-relaxed text-ink-faint">{hint}</p> : null}
    </div>
  );
}

export function ExportForm({ go }: { go: (v: View) => void }) {
  const {
    opts, optionsError, retryOptions, start, setStart, end, setEnd, target, setTarget, setGate,
    kind, setKind, tz, setTz, horizon, setHorizon, format, setFormat,
    accepted, setAccepted, pending, error, derived, applyPreset, download,
  } = useExportForm();

  if (optionsError) {
    return (
      <Card>
        <CardContent className="grid gap-3 pt-6">
          <p className="text-sm text-ink-soft">Could not load the available forecasts. Try again.</p>
          <div><Button variant="outline" onClick={retryOptions}>Retry</Button></div>
        </CardContent>
      </Card>
    );
  }

  if (!opts) {
    return (
      <div className="grid gap-4" aria-busy="true" aria-label="Loading export options">
        <div>
          <div className="h-8 w-56 animate-pulse rounded-md bg-line" />
          <div className="mt-2 h-4 w-96 max-w-full animate-pulse rounded bg-line" />
        </div>
        <div className="h-80 animate-pulse rounded-lg bg-line" />
      </div>
    );
  }

  if (opts.dates.length === 0) {
    return (
      <div className="grid gap-4">
        <h1 className="font-display text-2xl font-bold tracking-tight">Download Forecasts</h1>
        <Card><CardContent className="pt-6 text-sm text-ink-soft">No forecasts are published yet. Check back after the next run.</CardContent></Card>
      </div>
    );
  }

  const canDownload =
    !pending && accepted && !!start && !!end && derived.contiguous && !derived.overLimit && derived.availableGates.length > 0;

  return (
    <div className="grid gap-4">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight">Download Forecasts</h1>
        <p className="mt-1 text-sm text-ink-soft">
          Pick a range, run and format — one file for the DE-LU bidding zone.
        </p>
      </div>

      <Card>
        <CardContent className="grid gap-5 pt-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="dl-target" label="Forecast Quantity" hint={unitFor(target)}>
              <Select
                id="dl-target"
                name="target"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                {(opts.targets ?? []).map((t) => (
                  <option key={t} value={t}>
                    {targetLabel(t)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              id="dl-kind"
              label="Forecast Type"
              hint={kind === "point" ? "One median column: p50." : "Nine quantile columns: p10 through p90."}
            >
              <Select id="dl-kind" name="kind" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="point">Point Forecast</option>
                <option value="probabilistic">Probabilistic</option>
              </Select>
            </Field>
          </div>

          <div className="grid gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span id="dl-range-label" className="text-sm font-medium">
                Origin Date Range
              </span>
              <div className="flex flex-wrap gap-1.5" aria-label="Range presets">
                {[
                  { label: "Last 8 days", days: 8 },
                  { label: "Last 30 days", days: 30 },
                  { label: "Last 60 days", days: 60 },
                ].map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => applyPreset(p.days)}
                    className="h-7 cursor-pointer touch-manipulation rounded-full border border-line px-2.5 text-xs font-medium text-ink-soft transition-colors hover:border-ink-faint hover:text-ink"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2" role="group" aria-labelledby="dl-range-label">
              <Field id="dl-start" label="Start">
                <Select
                  id="dl-start"
                  name="start"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                >
                  {derived.dates.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field id="dl-end" label="End">
                <Select
                  id="dl-end"
                  name="end"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                >
                  {derived.dates.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div aria-live="polite">
              {derived.contiguous && !derived.overLimit ? (
                <div className="grid gap-1.5">
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="font-medium text-ink-soft tnum">
                      {derived.dayCount} {derived.dayCount === 1 ? "origin day" : "origin days"} · 15-minute
                      steps
                    </span>
                    <span className="text-ink-faint tnum">Max {MAX_GAP} days between start and end</span>
                  </div>
                  <div
                    role="progressbar"
                    aria-valuenow={derived.gap}
                    aria-valuemin={0}
                    aria-valuemax={MAX_GAP}
                    aria-label="Range length against the 75-day limit"
                    className="h-1.5 overflow-hidden rounded-full bg-line"
                  >
                    <div
                      className="h-full rounded-full bg-brand transition-[width]"
                      style={{ width: `${Math.min(100, (derived.gap / MAX_GAP) * 100)}%` }}
                    />
                  </div>
                </div>
              ) : null}
              {derived.overLimit ? (
                <p className="text-sm text-red-700">
                  That range spans {derived.gap} days. Shorten it to {MAX_GAP} days or less.
                </p>
              ) : null}
              {!derived.contiguous && start && end ? (
                <p className="text-sm text-red-700">End sits before start. Swap them to continue.</p>
              ) : null}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field
              id="dl-gate"
              label="Model Run"
              hint={derived.runLabel}
              info={
                <Tooltip
                  label="About the two daily runs"
                  trigger={
                    <button
                      type="button"
                      aria-label="About the two daily runs"
                      className="cursor-pointer text-ink-faint hover:text-brand"
                    >
                      <Info aria-hidden="true" className="size-4" />
                    </button>
                  }
                  content={GATE_INFO}
                />
              }
            >
              <Select id="dl-gate" name="gate" value={derived.selectedGate} onChange={(e) => setGate(e.target.value)}>
                <option value="0530" disabled={!derived.availableGates.includes("0530")}>05:30 Europe/Berlin</option>
                <option value="1130" disabled={!derived.availableGates.includes("1130")}>11:30 Europe/Berlin</option>
              </Select>
            </Field>
            <Field
              id="dl-horizon"
              label="Horizon in Days Ahead"
              hint={
                derived.overlapping
                  ? "Overlapping series, one per origin date."
                  : "One clean day-ahead strip per origin."
              }
            >
              <Select
                id="dl-horizon"
                name="horizon"
                value={horizon}
                onChange={(e) => setHorizon(e.target.value)}
              >
                {Array.from({ length: 10 }, (_, i) => String(i + 1)).map((h) => (
                  <option key={h} value={h}>
                    {h} {h === "1" ? "day" : "days"}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="dl-tz" label="Time Zone" hint="Applies to target_time only.">
              <Select id="dl-tz" name="tz" value={tz} onChange={(e) => setTz(e.target.value)}>
                <option value="Europe/Berlin">Europe/Berlin</option>
                <option value="UTC">UTC</option>
              </Select>
            </Field>
          </div>

          <Field id="dl-format" label="Format" hint={FORMAT_HINTS[format]}>
            <Select
              id="dl-format"
              name="format"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
            >
              <option value="xlsx">XLSX</option>
              <option value="csv">CSV</option>
              <option value="parquet">Parquet</option>
            </Select>
          </Field>

          <div className="border-t border-line" />

          <p
            className="truncate rounded-md bg-paper px-3 py-2 font-mono text-xs text-ink-soft tnum"
            title={derived.fileName}
            translate="no"
          >
            {derived.fileName} · ~{derived.rows.toLocaleString("en-GB")} rows
          </p>

          <div aria-live="polite">
            {error ? <p className="text-sm text-red-700">{error}</p> : null}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <span className="flex items-center gap-2 text-sm">
              <input
                id="dl-terms"
                type="checkbox"
                checked={accepted}
                onChange={(e) => setAccepted(e.target.checked)}
                className="size-4 shrink-0 cursor-pointer accent-brand"
              />
              <label htmlFor="dl-terms" className="cursor-pointer">
                I have read and accept the{" "}
              </label>
              <button
                type="button"
                onClick={() => go("terms")}
                className="cursor-pointer font-medium text-brand-deep underline decoration-brand/40 underline-offset-2 hover:decoration-brand-deep"
              >
                Terms of Use
              </button>
            </span>
            <span className="ml-auto">
              <Button onClick={download} disabled={!canDownload}>
                <DownloadIcon aria-hidden="true" />
                {pending ? "Preparing…" : `Download ${format.toUpperCase()}`}
              </Button>
            </span>
          </div>
        </CardContent>
      </Card>

      <details className="rounded-lg border border-line bg-card px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium">Citation and fair use</summary>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          Cite this work if you use the forecasts in research. State which run you used. You may use
          the forecasts as a benchmark or baseline, including in publications. Do not use them to
          build competing forecasts of the same target quantities for public benchmarks or
          leaderboards.
        </p>
      </details>
    </div>
  );
}

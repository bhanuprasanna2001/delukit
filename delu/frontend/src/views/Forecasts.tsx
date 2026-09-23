import { ChevronLeft, ChevronRight, Info } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ForecastChart } from "../components/ForecastChart";
import { Card, CardContent } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Tooltip } from "../components/ui/tooltip";
import {
  formatRunDay,
  getOptions,
  publicForecast,
  targetLabel,
  unitFor,
  type ForecastData,
  type Options,
} from "../lib/api";
import { cn } from "../lib/utils";

interface Sel {
  date: string;
  gate: string;
  span: string;
  target: string;
  kind: "point" | "probabilistic";
}

type ForecastResult =
  | { key: string; kind: "ok"; data: ForecastData }
  | { key: string; kind: "error"; message: string };

const GATE_INFO =
  "Two model runs a day. 05:30 runs before the morning auctions. 11:30 sees the EXAA results and the ENTSO-E day-ahead load forecast, so its day-ahead read is cleaner.";

const seg =
  "inline-flex h-8 cursor-pointer items-center rounded-[5px] px-3 text-sm font-medium transition-colors";

export function Forecasts() {
  const [opts, setOpts] = useState<Options | null>(null);
  const [sel, setSel] = useState<Sel>(() => ({
    date: "",
    gate: "1130",
    span: "d1",
    target: "",
    kind: "probabilistic",
  }));
  const [result, setResult] = useState<ForecastResult | null>(null);
  const [optionsError, setOptionsError] = useState("");

  useEffect(() => {
    getOptions().then(setOpts).catch((e: Error) => setOptionsError(e.message));
  }, []);

  const eff = useMemo((): Sel | null => {
    if (!opts || opts.dates.length === 0) return null;
    const date = opts.dates.includes(sel.date) ? sel.date : opts.dates[opts.dates.length - 1];
    const gates = opts.runs?.[date]?.[sel.span] ?? opts.gates;
    const gate = gates.includes(sel.gate)
      ? sel.gate
      : gates.includes("1130")
        ? "1130"
        : gates[0];
    const target = opts.targets.includes(sel.target)
      ? sel.target
      : opts.targets.includes("load_actual_mw")
        ? "load_actual_mw"
        : opts.targets[0];
    return { date, gate, span: sel.span, target, kind: sel.kind };
  }, [opts, sel]);

  const requestKey = eff ? JSON.stringify(eff) : null;
  const current = result?.key === requestKey ? result : null;
  const loading = !!eff && current === null;
  const data = current?.kind === "ok" ? current.data : null;
  const error = optionsError || (current?.kind === "error" ? current.message : "");

  useEffect(() => {
    if (!eff) return;
    let active = true;
    const key = JSON.stringify(eff);
    publicForecast(eff)
      .then((d) => {
        if (active) setResult({ key, kind: "ok", data: d });
      })
      .catch((e: Error) => {
        if (active) setResult({ key, kind: "error", message: e.message });
      });
    return () => {
      active = false;
    };
  }, [eff]);

  if (!opts) {
    if (optionsError) {
      return <p className="text-sm text-red-700">Could not load forecasts: {optionsError}</p>;
    }
    return (
      <div className="grid gap-3">
        <div className="h-10 w-64 animate-pulse rounded-md bg-line" />
        <div className="h-72 animate-pulse rounded-lg bg-line" />
      </div>
    );
  }

  if (opts.dates.length === 0) {
    return (
      <Card>
        <CardContent className="pt-6">
          <p className="text-sm text-ink-soft">
            No forecasts published yet. The next gate run will appear here.
          </p>
        </CardContent>
      </Card>
    );
  }

  const gates = opts.runs?.[eff?.date ?? ""]?.[eff?.span ?? "d1"] ?? opts.gates;

  const dayIdx = eff ? opts.dates.indexOf(eff.date) : -1;
  const prevDay = dayIdx > 0 ? opts.dates[dayIdx - 1] : null;
  const nextDay = dayIdx >= 0 && dayIdx < opts.dates.length - 1 ? opts.dates[dayIdx + 1] : null;

  const stepBtn =
    "flex h-9 w-8 flex-none cursor-pointer items-center justify-center rounded-md border border-line bg-card text-ink-soft transition-colors hover:border-ink-faint hover:text-ink disabled:cursor-default disabled:opacity-35 disabled:hover:border-line disabled:hover:text-ink-soft";

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-[1800px] flex-1 flex-col px-4 sm:px-6 lg:min-h-0">
      <div className="flex-none pt-4">
        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <div className="grid gap-1">
            <span id="runday-label" className="text-sm font-medium">
              Run day
            </span>
            <div className="flex items-center gap-1" role="group" aria-labelledby="runday-label">
              <button
                type="button"
                aria-label={prevDay ? `Previous run day, ${formatRunDay(prevDay)}` : "No earlier run day"}
                title={prevDay ? `Previous day (${formatRunDay(prevDay)})` : "No earlier day"}
                disabled={!prevDay}
                onClick={() => prevDay && setSel((s) => ({ ...s, date: prevDay }))}
                className={stepBtn}
              >
                <ChevronLeft aria-hidden="true" />
              </button>
              <Select
                value={eff?.date ?? ""}
                aria-label="Run day"
                onChange={(e) => setSel((s) => ({ ...s, date: e.target.value }))}
                className="w-[136px] text-center tnum"
              >
                {opts.dates.map((d) => (
                  <option key={d} value={d}>
                    {formatRunDay(d)}
                  </option>
                ))}
              </Select>
              <button
                type="button"
                aria-label={nextDay ? `Next run day, ${formatRunDay(nextDay)}` : "No later run day"}
                title={nextDay ? `Next day (${formatRunDay(nextDay)})` : "No later day"}
                disabled={!nextDay}
                onClick={() => nextDay && setSel((s) => ({ ...s, date: nextDay }))}
                className={stepBtn}
              >
                <ChevronRight aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="grid gap-1">
            <span className="flex items-center gap-1 text-sm font-medium">
              Run
              <Tooltip
                label="About the two daily runs"
                trigger={
                  <button
                    type="button"
                    aria-label="About the two daily runs"
                    className="cursor-pointer text-ink-faint hover:text-brand"
                  >
                    <Info className="size-4" aria-hidden="true" />
                  </button>
                }
                content={GATE_INFO}
              />
            </span>
            <div className="inline-flex gap-0.5 rounded-md border border-line bg-card p-0.5">
              {["0530", "1130"].map((g) => (
                <button
                  key={g}
                  type="button"
                  disabled={!gates.includes(g)}
                  onClick={() => setSel((s) => ({ ...s, gate: g }))}
                  className={cn(
                    seg,
                    "tnum",
                    eff?.gate === g
                      ? "bg-ink text-white"
                      : "text-ink-soft hover:text-ink disabled:opacity-35 disabled:hover:text-ink-soft",
                  )}
                >
                  {g.slice(0, 2)}:{g.slice(2)}
                </button>
              ))}
            </div>
          </div>

          <div className="grid gap-1">
            <span className="text-sm font-medium">Horizon</span>
            <div className="inline-flex gap-0.5 rounded-md border border-line bg-card p-0.5">
              {(
                [
                  ["d1", "Day-ahead"],
                  ["d10", "10-day"],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setSel((s) => ({ ...s, span: v }))}
                  className={cn(
                    seg,
                    eff?.span === v
                      ? "bg-ink text-white"
                      : "text-ink-soft hover:text-ink",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <label className="grid gap-1 text-sm font-medium">
            Series
            <Select
              value={eff?.target ?? ""}
              onChange={(e) => setSel((s) => ({ ...s, target: e.target.value }))}
            >
              {opts.targets.map((t) => (
                <option key={t} value={t}>
                  {targetLabel(t)}
                </option>
              ))}
            </Select>
          </label>

          <div className="grid gap-1">
            <span className="text-sm font-medium">Type</span>
            <div className="inline-flex gap-0.5 rounded-md border border-line bg-card p-0.5">
              {(
                [
                  ["point", "Point"],
                  ["probabilistic", "Probabilistic"],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setSel((s) => ({ ...s, kind: v }))}
                  className={cn(
                    seg,
                    eff?.kind === v
                      ? "bg-ink text-white"
                      : "text-ink-soft hover:text-ink",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {error ? (
        <p className="flex-none pt-3 text-sm text-red-700">
          Could not load the forecast: {error}
        </p>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col py-3">
        {loading ? (
          <div className="min-h-0 flex-1 animate-pulse rounded-xl bg-line" />
        ) : data ? (
          <div className="flex min-h-[380px] flex-1 flex-col overflow-hidden rounded-xl border border-line lg:min-h-0">
            <ForecastChart
              timestamps={data.timestamps}
              p50={data.p50}
              p10={data.p10}
              p90={data.p90}
              actual={data.actual}
              unit={unitFor(data.meta.target)}
              builtAt={data.meta.generated_at}
              target={eff?.target ?? data.meta.target}
            />
          </div>
        ) : (
          <div className="min-h-0 flex-1" />
        )}
      </div>

      {data && data.meta.model !== "xgboost" && !loading ? (
        <p className="flex-none pb-3 text-sm text-ink-soft">
          The primary model could not run at this gate, so this is fallback
          output. Treat it as degraded, not business as usual.
        </p>
      ) : null}
    </div>
  );
}

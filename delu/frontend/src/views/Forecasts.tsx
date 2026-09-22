import { Info } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ForecastChart } from "../components/ForecastChart";
import { Card, CardContent } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Tooltip } from "../components/ui/tooltip";
import {
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
  const [data, setData] = useState<ForecastData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getOptions().then(setOpts).catch((e: Error) => setError(e.message));
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

  useEffect(() => {
    if (!eff) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    publicForecast(eff)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, [eff?.date, eff?.gate, eff?.span, eff?.target, eff?.kind]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!opts) {
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

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-[1800px] flex-1 flex-col px-4 sm:px-6 lg:min-h-0">
      <div className="flex-none pt-4">
        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <label className="grid gap-1 text-sm font-medium">
            Run day
            <Select
              value={eff?.date ?? ""}
              onChange={(e) => setSel((s) => ({ ...s, date: e.target.value }))}
            >
              {opts.dates.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
          </label>

          <div className="grid gap-1">
            <span className="flex items-center gap-1 text-sm font-medium">
              Run
              <Tooltip
                label="About the two daily runs"
                trigger={
                  <button
                    type="button"
                    className="cursor-pointer text-ink-faint hover:text-brand"
                  >
                    <Info className="size-4" />
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
        {loading || !data ? (
          <div className="min-h-0 flex-1 animate-pulse rounded-xl bg-line" />
        ) : (
          <div className="flex min-h-[380px] flex-1 flex-col overflow-hidden rounded-xl border border-line lg:min-h-0">
            <ForecastChart
              timestamps={data.timestamps}
              p50={data.p50}
              p10={data.p10}
              p90={data.p90}
              actual={data.actual}
              unit={unitFor(data.meta.target)}
              builtAt={data.meta.generated_at}
            />
          </div>
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

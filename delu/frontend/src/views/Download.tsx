import { Download as DownloadIcon } from "lucide-react";
import { useEffect, useState } from "react";
import type { View } from "../App";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { getOptions, targetLabel, type Me, type Options } from "../lib/api";

const RUNS = [
  ["0530", "05:30 UTC"],
  ["1130", "11:30 Europe/Berlin"],
] as const;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="text-[13px] font-semibold">{label}</span>
      {children}
    </label>
  );
}

export function Download({
  me,
  onSignIn,
  go,
}: {
  me: Me | null;
  onSignIn: () => void;
  go: (v: View) => void;
}) {
  const [opts, setOpts] = useState<Options | null>(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [target, setTarget] = useState("gen_actual_photovoltaics_mwh");
  const [gate, setGate] = useState("0530");
  const [kind, setKind] = useState("point");
  const [tz, setTz] = useState("Europe/Berlin");
  const [horizon, setHorizon] = useState("1");
  const [format, setFormat] = useState("xlsx");
  const [accepted, setAccepted] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getOptions()
      .then((o) => {
        setOpts(o);
        if (o.dates.length > 0) {
          setEnd(o.dates[o.dates.length - 1]);
          setStart(o.dates[Math.max(0, o.dates.length - 9)]);
        }
        if (o.targets.includes("gen_actual_photovoltaics_mwh")) {
          setTarget("gen_actual_photovoltaics_mwh");
        } else if (o.targets.length > 0) {
          setTarget(o.targets[0]);
        }
      })
      .catch(() => undefined);
  }, []);

  async function download() {
    setPending(true);
    setError("");
    try {
      const q = new URLSearchParams({
        start,
        end,
        target,
        gate,
        kind,
        tz,
        horizon_days: horizon,
        format,
      });
      const res = await fetch(`/api/export?${q}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? "Download failed.");
      }
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") ?? "";
      const name = cd.match(/filename="([^"]+)"/)?.[1] ?? `delu-export.${format}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed.");
    } finally {
      setPending(false);
    }
  }

  if (!me) {
    return (
      <Card className="max-w-xl">
        <CardContent className="grid gap-3 pt-6">
          <p className="text-sm text-ink-soft">
            Exports are for account holders. Signing up takes a minute and also
            gives you the API key.
          </p>
          <div>
            <Button onClick={onSignIn}>Sign in</Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!me.verified) {
    return (
      <Card className="max-w-xl">
        <CardContent className="pt-6">
          <p className="text-sm text-ink-soft">
            Confirm your email to unlock downloads. Check your inbox for the
            confirmation link.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[280px_1fr]">
      <Card>
        <CardContent className="grid gap-4 pt-6">
          <Field label="Start">
            <Select value={start} onChange={(e) => setStart(e.target.value)}>
              {(opts?.dates ?? []).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="End">
            <Select value={end} onChange={(e) => setEnd(e.target.value)}>
              {(opts?.dates ?? []).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Forecast Quantity">
            <Select value={target} onChange={(e) => setTarget(e.target.value)}>
              {(opts?.targets ?? []).map((t) => (
                <option key={t} value={t}>
                  {targetLabel(t)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Model Run">
            <Select value={gate} onChange={(e) => setGate(e.target.value)}>
              {RUNS.map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Forecast Type">
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="point">Point Forecast</option>
              <option value="probabilistic">Probabilistic</option>
            </Select>
          </Field>
          <Field label="Time Zone">
            <Select value={tz} onChange={(e) => setTz(e.target.value)}>
              <option value="Europe/Berlin">Europe/Berlin</option>
              <option value="UTC">UTC</option>
            </Select>
          </Field>
          <Field label="Horizon in Days ahead">
            <Select value={horizon} onChange={(e) => setHorizon(e.target.value)}>
              {Array.from({ length: 10 }, (_, i) => String(i + 1)).map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Format">
            <Select value={format} onChange={(e) => setFormat(e.target.value)}>
              <option value="xlsx">XLSX</option>
              <option value="csv">CSV</option>
              <option value="parquet">Parquet</option>
            </Select>
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="grid gap-4 pt-6">
          <h2 className="font-display text-2xl font-semibold tracking-tight text-brand-deep">
            Download Forecasts for Bidding Zone DE-LU
          </h2>
          <p className="rounded-md bg-paper px-3 py-2 font-mono text-xs tnum">
            {targetLabel(target)} · {RUNS.find(([v]) => v === gate)?.[1]} ·{" "}
            {kind === "point" ? "Point" : "Probabilistic"} · {tz} · {start || "…"} →{" "}
            {end || "…"} · {format.toUpperCase()}
          </p>
          <p className="text-sm text-ink-soft">
            Set the export parameters on the left, then download the file for
            the DE-LU bidding zone.
          </p>
          <ul className="grid list-disc gap-2 pl-5 text-sm text-ink-soft">
            <li>
              Date range — origin dates with available forecasts; maximum 75
              days between start and end
            </li>
            <li>Horizon — limits how far ahead of each issue the timesteps go</li>
            <li>
              Horizon &gt; 1 day — the export contains multiple overlapping
              forecast timeseries, one per <em>origin_date</em>, rather than a
              single continuous timeseries
            </li>
            <li>
              Contents — <em>origin_date</em>, <em>origin_time</em> (05:30 UTC
              early run, or 11:30 Europe/Berlin midday run) and{" "}
              <em>target_time</em> in the selected timezone,{" "}
              <em>horizon_in_hours</em> from that origin, and the requested
              forecast columns
            </li>
          </ul>
          <div className="rounded-lg border border-brand/25 bg-brand-tint/50 px-4 py-3">
            <p className="text-sm leading-relaxed text-ink-soft">
              <strong className="font-semibold text-ink">Citation:</strong>{" "}
              Please cite this work if you use the forecasts in research, e.g.
              in energy system models or downstream studies — a citation
              reference will be added here once the paper is out. Two runs are
              published daily, the early run (05:30 UTC) and the midday run
              (11:30 Europe/Berlin), and any benchmark must state which run was
              used. You&apos;re free to use the forecasts as a benchmark or
              baseline, including in publications; the one restriction is that
              they may not be used to build competing forecasts of the same
              target quantities (SDAC/EPEX day-ahead prices, load, wind, PV)
              submitted to public benchmarks or leaderboards.
            </p>
          </div>
          {error ? <p className="text-sm text-red-700">{error}</p> : null}
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={accepted}
                onChange={(e) => setAccepted(e.target.checked)}
                className="size-4 accent-brand"
              />
              I have read and accept the{" "}
              <button
                type="button"
                className="cursor-pointer underline"
                onClick={() => go("terms")}
              >
                Terms of Use
              </button>
            </label>
            <span className="ml-auto">
              <Button onClick={download} disabled={pending || !accepted || !start || !end}>
                <DownloadIcon />
                {pending ? "Preparing…" : "Download"}
              </Button>
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

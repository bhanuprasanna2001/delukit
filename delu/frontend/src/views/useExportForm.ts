import { useEffect, useMemo, useState } from "react";
import { getOptions, type Options } from "../lib/api";

export const MAX_GAP = 75;
const STEPS_PER_DAY = 96;

export function useExportForm() {
  const [opts, setOpts] = useState<Options | null>(null);
  const [optionsError, setOptionsError] = useState(false);
  const [retry, setRetry] = useState(0);
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
        if (!o.targets.includes("gen_actual_photovoltaics_mwh") && o.targets.length > 0) {
          setTarget(o.targets[0]);
        }
      })
      .catch(() => setOptionsError(true));
  }, [retry]);

  function retryOptions() {
    setOptionsError(false);
    setRetry((attempt) => attempt + 1);
  }

  const derived = useMemo(() => {
    const dates = opts?.dates ?? [];
    const si = dates.indexOf(start);
    const ei = dates.indexOf(end);
    const contiguous = si >= 0 && ei >= 0 && ei >= si;
    const gap = contiguous ? ei - si : 0;
    const dayCount = contiguous ? gap + 1 : 0;
    const overLimit = gap > MAX_GAP;
    const h = Math.max(1, Number.parseInt(horizon, 10) || 1);
    const availableGates = opts?.gates.filter((candidate) =>
      contiguous && dates.slice(si, ei + 1).every((day) => {
        const products = opts.products[day]?.[candidate];
        return h === 1
          ? products?.d1?.includes(target) || products?.d10?.includes(target)
          : products?.d10?.includes(target);
      }),
    ) ?? [];
    const selectedGate = availableGates.includes(gate) ? gate : availableGates[0] ?? "0530";
    const rows = dayCount > 0 ? dayCount * h * STEPS_PER_DAY : 0;
    const overlapping = h > 1;
    const runLabel = selectedGate === "0530" ? "05:30 Europe/Berlin" : "11:30 Europe/Berlin";
    const fileName =
      start && end
        ? `delu_${target}_${start}_${end}_${selectedGate}_${kind}_h${h}d.${format}`
        : `delu_export.${format}`;
    return { dates, contiguous, gap, dayCount, overLimit, h, rows, overlapping, runLabel, fileName, availableGates, selectedGate };
  }, [opts, start, end, horizon, gate, target, kind, format]);

  function applyPreset(days: number) {
    const dates = opts?.dates ?? [];
    if (dates.length === 0) return;
    setEnd(dates[dates.length - 1]);
    setStart(dates[Math.max(0, dates.length - days)]);
  }

  async function download() {
    setPending(true);
    setError("");
    try {
      const q = new URLSearchParams({
        start,
        end,
        target,
        gate: derived.selectedGate,
        kind,
        tz,
        horizon_days: horizon,
        format,
      });
      const res = await fetch(`/api/export?${q}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? "Download failed. Check the range and try again.");
      }
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") ?? "";
      const name = cd.match(/filename="([^"]+)"/)?.[1] ?? derived.fileName;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed. Check the range and try again.");
    } finally {
      setPending(false);
    }
  }

  return {
    opts, optionsError, retryOptions, start, setStart, end, setEnd, target, setTarget, setGate,
    kind, setKind, tz, setTz, horizon, setHorizon, format, setFormat,
    accepted, setAccepted, pending, error, derived, applyPreset, download,
  };
}

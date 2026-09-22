import { useEffect, useMemo, useRef, useState } from "react";
import { accentFor, berlinDay, berlinLong, targetLabel } from "../lib/api";

interface Props {
  timestamps: string[];
  p50: (number | null)[];
  p10: (number | null)[] | null;
  p90: (number | null)[] | null;
  actual: (number | null)[];
  unit: string;
  builtAt: string;
  target: string;
}

const PAD = { l: 68, r: 16, t: 30, b: 30 };

const ACTUAL = "#e9eeea";
const GRID = "#22332a";
const TEXT = "#8fa096";
const NIGHT = "#101815";

function fmt(n: number): string {
  return n.toLocaleString("en-GB", { maximumFractionDigits: 1 });
}

function hexToRgba(hex: string, alpha: number): string {
  const m = hex.replace("#", "");
  const v = m.length === 3 ? m.split("").map((c) => c + c).join("") : m;
  const r = parseInt(v.slice(0, 2), 16);
  const g = parseInt(v.slice(2, 4), 16);
  const b = parseInt(v.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function niceTicks(lo: number, hi: number, target = 4): number[] {
  const raw = (hi - lo) / target;
  if (raw <= 0) return [lo];
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = (raw / mag >= 5 ? 10 : raw / mag >= 2 ? 5 : raw / mag >= 1 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

interface BerlinInfo {
  dateKey: string;
  weekday: number;
}

const partsFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin",
  weekday: "short",
  day: "numeric",
  month: "numeric",
});

const hmFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin",
  hour: "2-digit",
  minute: "2-digit",
});

function berlinInfo(iso: string): BerlinInfo {
  const parts = partsFmt.formatToParts(new Date(iso));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const wd = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 }[get("weekday")] ?? 1;
  return { dateKey: `${get("day")}.${get("month")}`, weekday: wd };
}

export function ForecastChart({
  timestamps,
  p50,
  p10,
  p90,
  actual,
  unit,
  builtAt,
  target,
}: Props) {
  const accent = accentFor(target);
  const plotRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = plotRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setSize({
        w: entry.contentRect.width,
        h: entry.contentRect.height,
      });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const geom = useMemo(() => {
    const { w, h } = size;
    if (w < 80 || h < 80 || timestamps.length === 0) return null;

    const vals: number[] = [];
    for (const v of p50) if (v !== null) vals.push(v);
    if (p10) for (const v of p10) if (v !== null) vals.push(v);
    if (p90) for (const v of p90) if (v !== null) vals.push(v);
    for (const v of actual) if (v !== null) vals.push(v);
    if (vals.length === 0) return null;

    let lo = Math.min(...vals);
    let hi = Math.max(...vals);
    if (lo === hi) {
      lo -= 1;
      hi += 1;
    }
    const pad = (hi - lo) * 0.06;
    lo -= pad;
    hi += pad;

    const iw = w - PAD.l - PAD.r;
    const ih = h - PAD.t - PAD.b;
    const n = timestamps.length;
    const x = (i: number) => PAD.l + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
    const y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo)) * ih;

    // Segmented path: restarts after every null so gaps never bridge.
    const segPath = (series: (number | null)[]) => {
      let d = "";
      let pen = false;
      for (let i = 0; i < series.length; i++) {
        const v = series[i];
        if (v === null) {
          pen = false;
          continue;
        }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
        pen = true;
      }
      return d;
    };

    // Band only where P10 and P90 both exist, split into contiguous runs.
    const bandPath = () => {
      if (!p10 || !p90) return "";
      let d = "";
      let run: number[] = [];
      const flush = () => {
        if (run.length > 1) {
          const a = run[0];
          const b = run[run.length - 1];
          let s = `M${x(a).toFixed(1)},${y(p10[a] as number).toFixed(1)}`;
          for (let k = 1; k < run.length; k++) {
            s += `L${x(run[k]).toFixed(1)},${y(p10[run[k]] as number).toFixed(1)}`;
          }
          for (let k = run.length - 1; k >= 0; k--) {
            s += `L${x(run[k]).toFixed(1)},${y(p90[run[k]] as number).toFixed(1)}`;
          }
          d += `${s}Z`;
          void b;
        }
        run = [];
      };
      for (let i = 0; i < n; i++) {
        if (p10[i] !== null && p90[i] !== null) run.push(i);
        else flush();
      }
      flush();
      return d;
    };

    const line = segPath(p50);
    const q10 = p10 ? segPath(p10) : "";
    const q90 = p90 ? segPath(p90) : "";
    const band = bandPath();
    const actualLine = segPath(actual);
    const area =
      !band && line
        ? `${line}L${x(n - 1).toFixed(1)},${(PAD.t + ih).toFixed(1)}L${x(0).toFixed(1)},${(PAD.t + ih).toFixed(1)}Z`
        : "";
    const gateIdx = p50.findIndex((v) => v !== null);
    const hasBands = q10 !== "" || q90 !== "";

    const yticks = niceTicks(lo, hi);

    // Group sample indices by Berlin calendar day; drives labels,
    // separators and weekend shading for long spans.
    const days: { start: number; end: number; key: string; weekend: boolean }[] = [];
    let info = berlinInfo(timestamps[0]);
    let cur = { start: 0, end: 0, key: info.dateKey, weekend: info.weekday >= 6 };
    for (let i = 1; i < n; i++) {
      info = berlinInfo(timestamps[i]);
      if (info.dateKey !== cur.key) {
        days.push(cur);
        cur = { start: i, end: i, key: info.dateKey, weekend: info.weekday >= 6 };
      }
      cur.end = i;
    }
    days.push(cur);

    const longSpan = days.length > 2;
    const xticks = longSpan
      ? days.map((d) => ({
          i: Math.round((d.start + d.end) / 2),
          label: berlinDay(timestamps[d.start]),
        }))
      : timestamps.flatMap((t, i) => {
          const hm = hmFmt.format(new Date(t));
          return Number(hm.slice(0, 2)) % 3 === 0 && hm.endsWith("00") ? [{ i, label: hm }] : [];
        });

    const originLabel =
      gateIdx > 0
        ? longSpan
          ? berlinDay(timestamps[gateIdx])
          : hmFmt.format(new Date(timestamps[gateIdx]))
        : "";

    return {
      w,
      h,
      ih,
      lo,
      hi,
      x,
      y,
      line,
      area,
      band,
      q10,
      q90,
      actualLine,
      gateIdx,
      hasBands,
      yticks,
      xticks,
      days,
      longSpan,
      n,
      originLabel,
      showZero: lo < 0 && hi > 0,
    };
  }, [size, timestamps, p50, p10, p90, actual]);

  if (size.w >= 80 && geom === null) {
    return (
      <div className="flex flex-1 items-center justify-center bg-night text-sm text-white/60">
        No values in this forecast.
      </div>
    );
  }

  const hv = hover;
  const hvx = geom && hv !== null ? geom.x(hv) : 0;
  const tipLeft = geom ? (hvx > geom.w * 0.6 ? hvx - 14 : hvx + 14) : 0;
  const tipSide = geom && hvx > geom.w * 0.6 ? "right" : "left";

  const bandFill = hexToRgba(accent, 0.13);
  const bandEdge = hexToRgba(accent, 0.03);
  const qLine = hexToRgba(accent, 0.62);
  const gateX = geom && geom.gateIdx > 0 ? geom.x(geom.gateIdx) : 0;
  const gateLabelX = geom
    ? Math.min(Math.max(gateX, PAD.l + 64), geom.w - PAD.r - 64)
    : 0;
  const histWide = geom && geom.gateIdx > 0 ? gateX - PAD.l > 96 : false;

  const swatch = (stroke: string, dashed = false) => (
    <svg width="22" height="8" aria-hidden="true">
      <line
        x1="1"
        y1="4"
        x2="21"
        y2="4"
        stroke={stroke}
        strokeWidth={dashed ? 1.5 : 2.25}
        strokeDasharray={dashed ? "4 3" : undefined}
        strokeLinecap="round"
      />
    </svg>
  );

  const dot = (fill: string, hollow = false) => (
    <span
      aria-hidden="true"
      className="inline-block size-2 flex-none rounded-full"
      style={
        hollow
          ? { border: `1.5px solid ${fill}`, background: "transparent" }
          : { background: fill }
      }
    />
  );

  const hvActual = hv !== null ? actual[hv] : null;
  const hvP50 = hv !== null ? p50[hv] : null;
  const hvP10 = hv !== null ? p10?.[hv] ?? null : null;
  const hvP90 = hv !== null ? p90?.[hv] ?? null : null;
  const hvDelta =
    hvActual != null && hvP50 != null ? hvActual - hvP50 : null;
  const hvWidth = hvP10 != null && hvP90 != null ? hvP90 - hvP10 : null;

  const stepHover = (d: number) => {
    if (!geom) return;
    setHover((prev) => {
      const base = prev ?? geom.gateIdx ?? 0;
      return Math.max(0, Math.min(geom.n - 1, base + d));
    });
  };

  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-night">
      <div className="flex flex-none flex-wrap items-center justify-between gap-2 px-5 pt-4 pb-1">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-white/70">
          <span className="flex items-center gap-2">
            {swatch(ACTUAL)}
            Actual
          </span>
          <span className="flex items-center gap-2">
            {swatch(accent)}
            {geom?.hasBands ? "Median · P50" : "Forecast"}
          </span>
          {geom?.hasBands ? (
            <>
              <span className="flex items-center gap-2">
                {swatch(qLine, true)}
                P10
              </span>
              <span className="flex items-center gap-2">
                {swatch(qLine, true)}
                P90
              </span>
            </>
          ) : null}
        </div>
        <span className="flex items-center gap-2 text-xs tnum">
          <span
            aria-hidden="true"
            className="inline-block size-2 rounded-full"
            style={{ background: accent }}
          />
          <span translate="no" className="font-semibold text-white/90">
            {targetLabel(target)}
          </span>
          <span aria-hidden="true" className="text-white/40">
            ·
          </span>
          <span className="text-white/40">{unit}</span>
          <span aria-hidden="true" className="text-white/40">
            ·
          </span>
          <span className="text-white/40">Built {berlinLong(builtAt)}</span>
        </span>
      </div>

      <div
        ref={plotRef}
        className="relative min-h-[320px] flex-1 px-2 pb-2 outline-none lg:min-h-0"
        onPointerLeave={() => setHover(null)}
        tabIndex={0}
        role="application"
        aria-label={`${targetLabel(target)} forecast chart. Use left and right arrow keys to inspect values.`}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") {
            e.preventDefault();
            stepHover(-1);
          } else if (e.key === "ArrowRight") {
            e.preventDefault();
            stepHover(1);
          } else if (e.key === "Home") {
            e.preventDefault();
            setHover(0);
          } else if (e.key === "End") {
            e.preventDefault();
            if (geom) setHover(geom.n - 1);
          } else if (e.key === "Escape") {
            setHover(null);
          }
        }}
      >
        {geom ? (
          <>
            <svg
              width={geom.w}
              height={geom.h}
              className="block touch-pan-y"
              role="img"
              aria-label={`${targetLabel(target)} forecast, ${geom.n} points`}
              onPointerMove={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const px = e.clientX - rect.left;
                const i = Math.round(
                  ((px - PAD.l) / (geom.w - PAD.l - PAD.r)) * (geom.n - 1),
                );
                setHover(Math.max(0, Math.min(geom.n - 1, i)));
              }}
              onPointerDown={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const px = e.clientX - rect.left;
                const i = Math.round(
                  ((px - PAD.l) / (geom.w - PAD.l - PAD.r)) * (geom.n - 1),
                );
                setHover(Math.max(0, Math.min(geom.n - 1, i)));
              }}
            >
              <defs>
                <linearGradient id="band-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={bandFill} />
                  <stop offset="100%" stopColor={bandEdge} />
                </linearGradient>
                <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={hexToRgba(accent, 0.16)} />
                  <stop offset="100%" stopColor={hexToRgba(accent, 0)} />
                </linearGradient>
              </defs>

              {geom.longSpan
                ? geom.days
                    .filter((d) => d.weekend)
                    .map((d, k) => (
                      <rect
                        key={k}
                        x={geom.x(d.start)}
                        y={PAD.t}
                        width={Math.max(0, geom.x(d.end) - geom.x(d.start))}
                        height={geom.ih}
                        fill="rgba(255,255,255,0.03)"
                      />
                    ))
                : null}

              {geom.yticks.map((v, k) => (
                <g key={k}>
                  <line
                    x1={PAD.l}
                    x2={geom.w - PAD.r}
                    y1={geom.y(v)}
                    y2={geom.y(v)}
                    stroke={GRID}
                    strokeWidth={1}
                  />
                  <text x={PAD.l - 10} y={geom.y(v) + 4} textAnchor="end" fontSize={11} fill={TEXT}>
                    {fmt(v)}
                  </text>
                </g>
              ))}

              {geom.showZero ? (
                <line
                  x1={PAD.l}
                  x2={geom.w - PAD.r}
                  y1={geom.y(0)}
                  y2={geom.y(0)}
                  stroke="#3c5246"
                  strokeWidth={1}
                  strokeDasharray="4 4"
                />
              ) : null}

              {geom.longSpan
                ? geom.days.slice(1).map((d, k) => (
                    <line
                      key={k}
                      x1={geom.x(d.start)}
                      x2={geom.x(d.start)}
                      y1={PAD.t}
                      y2={PAD.t + geom.ih}
                      stroke={GRID}
                      strokeWidth={1}
                    />
                  ))
                : null}

              {geom.gateIdx > 0 ? (
                <rect
                  x={PAD.l}
                  y={PAD.t}
                  width={Math.max(0, gateX - PAD.l)}
                  height={geom.ih}
                  fill="rgba(255,255,255,0.025)"
                />
              ) : null}

              {geom.band ? <path d={geom.band} fill="url(#band-grad)" /> : null}
              {geom.q10 ? (
                <path d={geom.q10} fill="none" stroke={qLine} strokeWidth={1.25} strokeDasharray="4 3" />
              ) : null}
              {geom.q90 ? (
                <path d={geom.q90} fill="none" stroke={qLine} strokeWidth={1.25} strokeDasharray="4 3" />
              ) : null}
              {geom.actualLine ? (
                <path d={geom.actualLine} fill="none" stroke={ACTUAL} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
              ) : null}
              {!geom.band && geom.area ? <path d={geom.area} fill="url(#area-grad)" /> : null}
              {geom.line ? (
                <path d={geom.line} fill="none" stroke={accent} strokeWidth={2.25} strokeLinejoin="round" strokeLinecap="round" />
              ) : null}

              {geom.gateIdx > 0 ? (
                <g>
                  <line
                    x1={gateX}
                    x2={gateX}
                    y1={PAD.t}
                    y2={PAD.t + geom.ih}
                    stroke="#46584d"
                    strokeWidth={1}
                    strokeDasharray="3 3"
                  />
                  {histWide ? (
                    <text x={PAD.l + 10} y={PAD.t - 10} fontSize={11} fill={TEXT}>
                      Actual
                    </text>
                  ) : null}
                  <text
                    x={gateLabelX}
                    y={PAD.t - 10}
                    textAnchor="middle"
                    fontSize={11}
                    fill={TEXT}
                  >
                    {`Forecast ▸ ${geom.originLabel}`}
                  </text>
                </g>
              ) : null}

              {geom.xticks.map((t, k) => (
                <text
                  key={k}
                  x={Math.min(Math.max(geom.x(t.i), PAD.l + 18), geom.w - PAD.r - 18)}
                  y={geom.h - 8}
                  textAnchor="middle"
                  fontSize={11}
                  fill={TEXT}
                >
                  {t.label}
                </text>
              ))}

              {hv !== null ? (
                <g>
                  <line
                    x1={geom.x(hv)}
                    x2={geom.x(hv)}
                    y1={PAD.t}
                    y2={PAD.t + geom.ih}
                    stroke="#ffffff"
                    strokeOpacity={0.35}
                    strokeWidth={1}
                  />
                  {hvP50 !== null && hvP50 !== undefined ? (
                    <circle
                      cx={geom.x(hv)}
                      cy={geom.y(hvP50)}
                      r={4}
                      fill={accent}
                      stroke={NIGHT}
                      strokeWidth={2}
                    />
                  ) : null}
                  {hvActual !== null && hvActual !== undefined ? (
                    <circle
                      cx={geom.x(hv)}
                      cy={geom.y(hvActual)}
                      r={4}
                      fill={ACTUAL}
                      stroke={NIGHT}
                      strokeWidth={2}
                    />
                  ) : null}
                  {hvP10 !== null && hvP10 !== undefined ? (
                    <circle
                      cx={geom.x(hv)}
                      cy={geom.y(hvP10)}
                      r={3}
                      fill={NIGHT}
                      stroke={qLine}
                      strokeWidth={1.5}
                    />
                  ) : null}
                  {hvP90 !== null && hvP90 !== undefined ? (
                    <circle
                      cx={geom.x(hv)}
                      cy={geom.y(hvP90)}
                      r={3}
                      fill={NIGHT}
                      stroke={qLine}
                      strokeWidth={1.5}
                    />
                  ) : null}
                </g>
              ) : null}
            </svg>

            {hv !== null ? (
              <div
                aria-live="polite"
                className="pointer-events-none absolute top-8 min-w-[228px] rounded-md border border-white/10 bg-[#1a2620] px-3 py-2 text-xs shadow-xl tnum"
                style={tipSide === "left" ? { left: tipLeft } : { right: geom.w - tipLeft }}
              >
                <div className="font-medium text-white/90">{berlinLong(timestamps[hv])}</div>
                <dl className="mt-1 grid gap-1">
                  {hvActual !== null && hvActual !== undefined ? (
                    <div className="flex items-baseline justify-between gap-6">
                      <dt className="flex items-center gap-2 text-white/60">
                        {dot(ACTUAL)}
                        Actual
                      </dt>
                      <dd className="font-semibold text-white/90">
                        {fmt(hvActual)} {unit}
                      </dd>
                    </div>
                  ) : null}
                  {hvP50 !== null && hvP50 !== undefined ? (
                    <div className="flex items-baseline justify-between gap-6">
                      <dt className="flex items-center gap-2 text-white/60">
                        {dot(accent)}
                        Median · P50
                      </dt>
                      <dd className="font-semibold" style={{ color: accent }}>
                        {fmt(hvP50)} {unit}
                      </dd>
                    </div>
                  ) : null}
                  {hvP10 !== null && hvP10 !== undefined ? (
                    <div className="flex items-baseline justify-between gap-6">
                      <dt className="flex items-center gap-2 text-white/60">
                        {dot(qLine, true)}
                        P10
                      </dt>
                      <dd className="text-white/80">
                        {fmt(hvP10)} {unit}
                      </dd>
                    </div>
                  ) : null}
                  {hvP90 !== null && hvP90 !== undefined ? (
                    <div className="flex items-baseline justify-between gap-6">
                      <dt className="flex items-center gap-2 text-white/60">
                        {dot(qLine, true)}
                        P90
                      </dt>
                      <dd className="text-white/80">
                        {fmt(hvP90)} {unit}
                      </dd>
                    </div>
                  ) : null}
                </dl>
                {hvDelta !== null || hvWidth !== null ? (
                  <div className="mt-1.5 border-t border-white/10 pt-1.5 text-white/45">
                    {hvDelta !== null ? (
                      <div className="flex items-baseline justify-between gap-6">
                        <span>Actual − P50</span>
                        <span>
                          {hvDelta >= 0 ? "+" : "−"}
                          {fmt(Math.abs(hvDelta))} {unit}
                        </span>
                      </div>
                    ) : null}
                    {hvWidth !== null ? (
                      <div className="flex items-baseline justify-between gap-6">
                        <span>90% interval width</span>
                        <span>
                          {fmt(hvWidth)} {unit}
                        </span>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

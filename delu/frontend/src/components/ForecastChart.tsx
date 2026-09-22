import { useEffect, useMemo, useRef, useState } from "react";
import { berlinDay, berlinLong } from "../lib/api";

interface Props {
  timestamps: string[];
  p50: (number | null)[];
  p10: (number | null)[] | null;
  p90: (number | null)[] | null;
  actual: (number | null)[];
  unit: string;
  builtAt: string;
}

const PAD = { l: 64, r: 16, t: 12, b: 32 };

const ACTUAL = "#dfe5df";
const LINE = "#57d98a";
const QLINE = "rgba(87, 217, 138, 0.55)";
const GRID = "#22322a";
const TEXT = "#8fa096";
const BAND_TOP = "rgba(87, 217, 138, 0.14)";
const BAND_BOTTOM = "rgba(87, 217, 138, 0.03)";

function fmt(n: number): string {
  return n.toLocaleString("en-GB", { maximumFractionDigits: 1 });
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

export function ForecastChart({ timestamps, p50, p10, p90, actual, unit, builtAt }: Props) {
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

    const path = (series: (number | null)[], reverse = false) => {
      let d = "";
      const visit = (i: number) => {
        const v = series[i];
        if (v === null) return;
        d += `${d && !reverse ? "L" : reverse ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      };
      if (!reverse) {
        for (let i = 0; i < series.length; i++) visit(i);
      } else {
        for (let i = series.length - 1; i >= 0; i--) visit(i);
      }
      return d;
    };

    const line = path(p50);
    const base = (PAD.t + ih).toFixed(1);
    const area = line
      ? `${line}L${x(n - 1).toFixed(1)},${base}L${x(0).toFixed(1)},${base}Z`
      : "";

    let band = "";
    let q10 = "";
    let q90 = "";
    if (p10 && p90) {
      q10 = path(p10);
      q90 = path(p90);
      const top = q10;
      const bottom = path(p90, true);
      if (top && bottom) band = `${top}${bottom}Z`;
    }
    const actualLine = path(actual);
    const gateIdx = p50.findIndex((v) => v !== null);

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

    return {
      w,
      h,
      iw,
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
      yticks,
      xticks,
      days,
      longSpan,
      n,
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
  const tipAnchor = geom && hvx > geom.w * 0.6 ? "right" : "left";

  const swatch = (stroke: string, dashed = false) => (
    <svg width="22" height="8" aria-hidden="true">
      <line
        x1="1"
        y1="4"
        x2="21"
        y2="4"
        stroke={stroke}
        strokeWidth={dashed ? 1.5 : 2}
        strokeDasharray={dashed ? "3 2" : undefined}
      />
    </svg>
  );

  return (
    <div className="relative flex min-h-0 flex-1 flex-col bg-night">
      <div className="flex flex-none flex-wrap items-center justify-between gap-2 px-5 pt-4 pb-1">
        <div className="flex flex-wrap items-center gap-5 text-xs text-white/70">
          <span className="flex items-center gap-2">
            {swatch(ACTUAL)}
            Actual
          </span>
          <span className="flex items-center gap-2">
            {swatch(LINE)}
            P50
          </span>
          <span className="flex items-center gap-2">
            {swatch(QLINE, true)}
            P10 / P90
          </span>
        </div>
        <span className="text-xs text-white/40 tnum">
          Europe/Berlin · {unit} · Built {berlinLong(builtAt)}
        </span>
      </div>

      <div
        ref={plotRef}
        className="relative min-h-[320px] flex-1 px-2 pb-2 lg:min-h-0"
        onPointerLeave={() => setHover(null)}
      >
        {geom ? (
          <>
            <svg
              width={geom.w}
              height={geom.h}
              className="block touch-pan-y"
              role="img"
              aria-label="Forecast chart"
              onPointerMove={(e) => {
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
                  <stop offset="0%" stopColor={BAND_TOP} />
                  <stop offset="100%" stopColor={BAND_BOTTOM} />
                </linearGradient>
                <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="rgba(87,217,138,0.14)" />
                  <stop offset="100%" stopColor="rgba(87,217,138,0)" />
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
                        width={geom.x(d.end) - geom.x(d.start)}
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

              {geom.band ? <path d={geom.band} fill="url(#band-grad)" /> : null}
              {geom.q10 ? (
                <path d={geom.q10} fill="none" stroke={QLINE} strokeWidth={1.25} strokeDasharray="4 3" />
              ) : null}
              {geom.q90 ? (
                <path d={geom.q90} fill="none" stroke={QLINE} strokeWidth={1.25} strokeDasharray="4 3" />
              ) : null}
              {geom.actualLine ? (
                <path d={geom.actualLine} fill="none" stroke={ACTUAL} strokeWidth={1.75} strokeLinejoin="round" />
              ) : null}
              {!geom.band && geom.area ? <path d={geom.area} fill="url(#area-grad)" /> : null}
              <path d={geom.line} fill="none" stroke={LINE} strokeWidth={2} strokeLinejoin="round" />

              {geom.gateIdx > 0 ? (
                <line
                  x1={geom.x(geom.gateIdx)}
                  x2={geom.x(geom.gateIdx)}
                  y1={PAD.t}
                  y2={PAD.t + geom.ih}
                  stroke="#3c5246"
                  strokeWidth={1}
                />
              ) : null}

              {geom.xticks.map((t, k) => (
                <text
                  key={k}
                  x={Math.min(Math.max(geom.x(t.i), PAD.l + 18), geom.w - PAD.r - 18)}
                  y={geom.h - 10}
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
                  {p50[hv] !== null ? (
                    <circle
                      cx={geom.x(hv)}
                      cy={geom.y(p50[hv] as number)}
                      r={4}
                      fill={LINE}
                      stroke="#101815"
                      strokeWidth={2}
                    />
                  ) : null}
                  {actual[hv] !== null && actual[hv] !== undefined ? (
                    <circle
                      cx={geom.x(hv)}
                      cy={geom.y(actual[hv] as number)}
                      r={4}
                      fill={ACTUAL}
                      stroke="#101815"
                      strokeWidth={2}
                    />
                  ) : null}
                </g>
              ) : null}
            </svg>

            {hv !== null ? (
              <div
                className="pointer-events-none absolute top-2 rounded-md border border-white/10 bg-[#1a2620] px-3 py-2 text-xs shadow-xl tnum"
                style={tipAnchor === "left" ? { left: tipLeft } : { right: geom.w - tipLeft }}
              >
                <div className="font-medium text-white/90">{berlinLong(timestamps[hv])}</div>
                {actual[hv] !== null && actual[hv] !== undefined ? (
                  <div className="mt-1 font-semibold text-white/80">
                    Actual {fmt(actual[hv] as number)} {unit}
                  </div>
                ) : null}
                {p50[hv] !== null ? (
                  <div className="mt-1 font-semibold" style={{ color: LINE }}>
                    P50 {fmt(p50[hv] as number)} {unit}
                  </div>
                ) : null}
                {p10?.[hv] != null && p90?.[hv] != null ? (
                  <div className="text-white/60">
                    P10–P90 {fmt(p10[hv] as number)} – {fmt(p90[hv] as number)} {unit}
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

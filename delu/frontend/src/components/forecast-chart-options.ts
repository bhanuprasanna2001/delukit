import type { EChartsOption, LineSeriesOption } from "echarts";
import type { ForecastData } from "../lib/api";

export const HOUR = 3_600_000;
export type ChartTheme = "light" | "dark";

const CHART_COLORS: Record<ChartTheme, Record<string, string>> = {
  light: {
    load_actual_mw: "#166d63",
    gen_actual_total_mwh: "#704a95",
    gen_actual_wind_offshore_mwh: "#206c9b",
    gen_actual_wind_onshore_mwh: "#537235",
    gen_actual_photovoltaics_mwh: "#9a650b",
    price_sdac_seq1_eur_mwh: "#a23f59",
  },
  dark: {
    load_actual_mw: "#6bd6c1",
    gen_actual_total_mwh: "#c1a2ef",
    gen_actual_wind_offshore_mwh: "#7dc6f2",
    gen_actual_wind_onshore_mwh: "#add184",
    gen_actual_photovoltaics_mwh: "#f2c66d",
    price_sdac_seq1_eur_mwh: "#f0a2b5",
  },
};

export const CHART_PALETTE = {
  light: {
    surface: "#fafafa", text: "#252525", muted: "#555555", line: "#d4d4d4",
    grid: "#e5e5e5", actual: "#777777", navigator: "#888888",
    navigatorFill: "#e8e8e8", selection: "rgba(37,37,37,0.10)",
    shadow: "rgba(37,37,37,0.10)", bandOpacity: 0.075, bandKeyOpacity: 0.25,
  },
  dark: {
    surface: "#303030", text: "#fafafa", muted: "#d1d1d1", line: "#535353",
    grid: "#484848", actual: "#a6a6a6", navigator: "#b8b8b8",
    navigatorFill: "#424242", selection: "rgba(250,250,250,0.12)",
    shadow: "rgba(37,37,37,0.30)", bandOpacity: 0.105, bandKeyOpacity: 0.36,
  },
} satisfies Record<ChartTheme, Record<string, string | number>>;

export function forecastColor(target: string, theme: ChartTheme): string {
  return CHART_COLORS[theme][target] ?? CHART_COLORS[theme].load_actual_mw;
}

export interface TimeWindow {
  start: number;
  end: number;
}

export interface ChartVisibility {
  actual: boolean;
  forecast: boolean;
  intervals: boolean;
}

const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin", hour: "2-digit", minute: "2-digit",
});
const dayFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin", day: "numeric", month: "short",
});
const fullFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin", weekday: "short", day: "numeric", month: "short",
  hour: "2-digit", minute: "2-digit", timeZoneName: "short",
});
export const formatTime = (value: number) => timeFormat.format(value);
export const formatDay = (value: number) => dayFormat.format(value);
export const formatTimestamp = (value: number) => fullFormat.format(value);
export const formatValue = (value: number) => value.toLocaleString("en-GB", { maximumFractionDigits: 1 });

export function withTimeGaps(data: ForecastData): ForecastData {
  const timestamps: string[] = [];
  const indices: (number | null)[] = [];
  data.timestamps.forEach((timestamp, index) => {
    if (index > 0 && Date.parse(timestamp) - Date.parse(data.timestamps[index - 1]) > HOUR / 4) {
      timestamps.push(new Date(Date.parse(data.timestamps[index - 1]) + HOUR / 4).toISOString());
      indices.push(null);
    }
    timestamps.push(timestamp);
    indices.push(index);
  });
  const align = (values: (number | null)[]) => indices.map((index) => index === null ? null : values[index] ?? null);
  const quantile = (values: (number | null)[] | null) => values === null ? null : align(values);
  return {
    ...data, timestamps, actual: align(data.actual), p50: align(data.p50),
    p10: quantile(data.p10), p20: quantile(data.p20), p30: quantile(data.p30), p40: quantile(data.p40),
    p60: quantile(data.p60), p70: quantile(data.p70), p80: quantile(data.p80), p90: quantile(data.p90),
  };
}

export function forecastDomain(data: ForecastData): TimeWindow | null {
  if (!data.timestamps.length) return null;
  return { start: Date.parse(data.timestamps[0]), end: Date.parse(data.timestamps.at(-1) ?? data.timestamps[0]) };
}

export function chartTimeScale(data: ForecastData) {
  const realDomain = forecastDomain(data);
  const identity = (time: number) => time;
  if (!realDomain) return { domain: { start: 0, end: HOUR }, project: identity, unproject: identity, shortenedGap: null };

  const firstForecast = data.p50.findIndex((value) => value !== null);
  const lastActual = data.actual.findLastIndex((value, index) => value !== null && index < firstForecast);
  if (firstForecast < 0 || lastActual < 0) {
    return { domain: realDomain, project: identity, unproject: identity, shortenedGap: null };
  }

  const forecastStart = Date.parse(data.timestamps[firstForecast]);
  const actualEnd = Date.parse(data.timestamps[lastActual]);
  const gap = forecastStart - actualEnd;
  const forecastDuration = realDomain.end - forecastStart;
  const desiredPast = forecastDuration * (1 - 0.618) / 0.618;
  const displayedGap = desiredPast - (actualEnd - realDomain.start);
  if (gap <= 0 || forecastDuration <= 0 || displayedGap <= 0 || displayedGap >= gap) {
    return { domain: realDomain, project: identity, unproject: identity, shortenedGap: null };
  }

  const removed = Math.round((gap - displayedGap) / HOUR) * HOUR;
  if (removed <= 0 || removed >= gap) {
    return { domain: realDomain, project: identity, unproject: identity, shortenedGap: null };
  }
  const shortenedGap = { start: actualEnd, end: forecastStart - removed };
  const gapRatio = (gap - removed) / gap;
  const project = (time: number) => time <= actualEnd ? time
    : time < forecastStart ? actualEnd + (time - actualEnd) * gapRatio : time - removed;
  const unproject = (time: number) => time <= actualEnd ? time
    : time < shortenedGap.end ? actualEnd + (time - actualEnd) / gapRatio : time + removed;
  return {
    domain: { start: realDomain.start, end: realDomain.end - removed },
    project, unproject, shortenedGap,
  };
}

export function fitWindow(start: number, duration: number, domain: TimeWindow): TimeWindow {
  const width = Math.min(Math.max(duration, Math.min(HOUR, domain.end - domain.start)), domain.end - domain.start);
  const left = Math.max(domain.start, Math.min(start, domain.end - width));
  return { start: left, end: left + width };
}

export function zoomWindow(window: TimeWindow, factor: number, domain: TimeWindow): TimeWindow {
  const duration = (window.end - window.start) * factor;
  return fitWindow((window.start + window.end - duration) / 2, duration, domain);
}

export function windowFromZoom(event: unknown, domain: TimeWindow): TimeWindow | null {
  if (!event || typeof event !== "object") return null;
  if ("batch" in event && Array.isArray(event.batch)) return windowFromZoom(event.batch[0], domain);
  if ("startValue" in event && "endValue" in event && typeof event.startValue === "number" && typeof event.endValue === "number") {
    return fitWindow(event.startValue, event.endValue - event.startValue, domain);
  }
  if (!("start" in event) || !("end" in event)) return null;
  if (typeof event.start !== "number" || typeof event.end !== "number") return null;
  if (!Number.isFinite(event.start) || !Number.isFinite(event.end)) return null;
  const extent = domain.end - domain.start;
  return fitWindow(domain.start + extent * event.start / 100, extent * (event.end - event.start) / 100, domain);
}

export function visibleExtent(data: ForecastData, window: TimeWindow, visibility: ChartVisibility): [number, number] {
  const scale = chartTimeScale(data);
  let min = Infinity;
  let max = -Infinity;
  for (let i = 0; i < data.timestamps.length; i++) {
    const time = scale.project(Date.parse(data.timestamps[i]));
    const before = scale.project(Date.parse(data.timestamps[Math.max(0, i - 1)]));
    const after = scale.project(Date.parse(data.timestamps[Math.min(data.timestamps.length - 1, i + 1)]));
    if (time < window.start && after < window.start || time > window.end && before > window.end) continue;
    const values = [visibility.actual ? data.actual[i] : null, visibility.forecast ? data.p50[i] : null];
    if (visibility.forecast && visibility.intervals) values.push(data.p10?.[i] ?? null, data.p90?.[i] ?? null);
    for (const value of values) {
      if (value != null && Number.isFinite(value)) {
        min = Math.min(min, value);
        max = Math.max(max, value);
      }
    }
  }
  if (!Number.isFinite(min)) return [0, 1];
  const padding = Math.max((max - min) * 0.12, Math.abs(max) * 0.01, 1);
  return [min - padding, max + padding];
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character] ?? character);
}

export function tooltipHtml(data: ForecastData, index: number, unit: string, visibility: ChartVisibility, theme: ChartTheme = "light"): string {
  const timestamp = data.timestamps[index];
  if (!timestamp) return "";
  const color = forecastColor(data.meta.target, theme);
  const actual = data.actual[index];
  const median = data.p50[index];
  const safeUnit = escapeHtml(unit);
  const value = (number: number) => `${formatValue(number)} <small>${safeUnit}</small>`;
  const pointRow = (label: string, number: number, ink: string) =>
    `<div class="forecast-tooltip-row"><span><i style="background:${ink}"></i>${label}</span><strong>${value(number)}</strong></div>`;
  const pairs = [
    ["P10–P90", data.p10?.[index], data.p90?.[index]],
    ["P20–P80", data.p20?.[index], data.p80?.[index]],
    ["P30–P70", data.p30?.[index], data.p70?.[index]],
    ["P40–P60", data.p40?.[index], data.p60?.[index]],
  ] as const;
  const ranges = visibility.forecast && visibility.intervals ? pairs
    .flatMap(([label, lower, upper]) => lower != null && upper != null
      ? [`<div class="forecast-tooltip-row forecast-tooltip-range"><span>${label}</span><strong>${formatValue(lower)}–${value(upper)}</strong></div>`] : []).join("") : "";
  return `<div class="forecast-tooltip"><div class="forecast-tooltip-time">${escapeHtml(formatTimestamp(Date.parse(timestamp)))}</div>${visibility.forecast && median != null ? pointRow("P50 · median", median, color) : ""}${visibility.actual && actual != null ? pointRow("Actual", actual, CHART_PALETTE[theme].actual) : ""}${ranges ? `<div class="forecast-tooltip-ranges">${ranges}</div>` : ""}${visibility.forecast && visibility.actual && actual != null && median != null ? pointRow("Actual − median", actual - median, CHART_PALETTE[theme].actual) : ""}</div>`;
}

export function chartOptions({ data, unit, window, visibility, compact, theme, onInspect }: {
  data: ForecastData;
  unit: string;
  window: TimeWindow;
  visibility: ChartVisibility;
  compact: boolean;
  theme: ChartTheme;
  onInspect: (index: number) => void;
}): EChartsOption {
  const scale = chartTimeScale(data);
  const times = data.timestamps.map((timestamp) => scale.project(Date.parse(timestamp)));
  const domain = scale.domain;
  const extent = Math.max(1, domain.end - domain.start);
  const accent = forecastColor(data.meta.target, theme);
  const palette = CHART_PALETTE[theme];
  const forecastStart = data.p50.findIndex((value) => value !== null);
  const builtAt = scale.project(Date.parse(data.meta.generated_at));
  const annotationNearRight = times[forecastStart] > window.start + (window.end - window.start) * 0.8;
  const buildNearLeft = builtAt < window.start + (window.end - window.start) * 0.08;
  const buildAlignment: "left" | "right" = buildNearLeft ? "left" : "right";
  const startAlignment: "left" | "right" = annotationNearRight ? "right" : "left";
  const [min, max] = visibleExtent(data, window, visibility);
  const left = compact ? 54 : 72;
  const right = compact ? 18 : 28;
  const line = (name: string, values: (number | null)[], color: string): LineSeriesOption => ({
    name, type: "line", data: times.map((time, i) => [time, values[i]]),
    showSymbol: false, symbol: "circle", symbolSize: 7, connectNulls: false,
    lineStyle: { color, width: 2.5 }, itemStyle: { color },
    emphasis: { disabled: true }, clip: true, z: 5,
  });
  const series: LineSeriesOption[] = [];
  if (visibility.forecast) series.push({
    ...line("Median forecast · P50", data.p50, accent),
    markLine: {
      silent: true, symbol: "none", animation: false,
      lineStyle: { color: palette.navigator, width: 1, type: "dashed" },
      label: {
        color: palette.muted, fontSize: 11, position: "end", rotate: 0,
        verticalAlign: "bottom", distance: 0,
      },
      data: [
        ...(builtAt >= window.start && builtAt <= window.end ? [{
          xAxis: builtAt,
          label: { formatter: "Forecast built", align: buildAlignment, offset: [buildNearLeft ? 8 : -8, -8] },
        }] : []),
        ...(forecastStart > 0 && times[forecastStart] >= window.start && times[forecastStart] <= window.end ? [{
          xAxis: times[forecastStart],
          label: { formatter: "Forecast begins", align: startAlignment, offset: [annotationNearRight ? -8 : 8, -8] },
        }] : []),
      ],
    },
  });
  if (visibility.actual) series.push({
    ...line("Actual", data.actual, palette.actual),
    lineStyle: { color: palette.actual, width: 2, type: "dashed" },
  });
  if (visibility.forecast && visibility.intervals) {
    const bands = [
      [data.p10, data.p90, "80%"], [data.p20, data.p80, "60%"],
      [data.p30, data.p70, "40%"], [data.p40, data.p60, "20%"],
    ] as const;
    for (const [lower, upper, name] of bands) {
      if (!lower || !upper) continue;
      const base = lower.map((value, i) => value != null && upper[i] != null ? value : null);
      const width = upper.map((value, i) => value != null && lower[i] != null ? value - lower[i] : null);
      series.push(
        { ...line(`${name} base`, base, "transparent"), stack: name, stackStrategy: "all", silent: true, z: 1, tooltip: { show: false } },
        { ...line(`${name} interval`, width, "transparent"), stack: name, stackStrategy: "all", silent: true, z: 1,
          areaStyle: { color: accent, opacity: palette.bandOpacity }, tooltip: { show: false } },
      );
    }
  }
  series.push({
    ...line("Full timeline", data.p50.map((value, i) => value ?? data.actual[i]), palette.navigator),
    xAxisIndex: 1, yAxisIndex: 1, silent: true, z: 1,
    lineStyle: { color: palette.navigator, width: 1 },
    areaStyle: { color: palette.navigatorFill, opacity: 0.8 }, tooltip: { show: false },
  });
  return {
    animation: false, backgroundColor: palette.surface,
    textStyle: { fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif' },
    grid: [
      { left, right, top: 30, bottom: 140 },
      { left, right, height: 44, bottom: 28 },
    ],
    xAxis: [
      {
        type: "time", min: domain.start, max: domain.end, boundaryGap: [0, 0],
        axisLine: { lineStyle: { color: palette.line } }, axisTick: { show: false }, splitLine: { show: false },
        splitNumber: compact ? 3 : 7,
        axisLabel: { color: palette.muted, fontSize: 11, margin: 14, hideOverlap: true,
          formatter: (value: number) => {
            if (scale.shortenedGap && value > scale.shortenedGap.start && value < scale.shortenedGap.end) return "";
            const realTime = scale.unproject(value);
            return window.end - window.start > 3 * 24 * HOUR
              ? `\n${formatDay(realTime)}` : `${formatTime(realTime)}\n${formatDay(realTime)}`;
          }, lineHeight: 17 },
        axisPointer: { label: { show: false }, lineStyle: { color: palette.navigator, type: "dashed" } },
      },
      { type: "time", gridIndex: 1, min: domain.start, max: domain.end, show: false, boundaryGap: [0, 0] },
    ],
    yAxis: [
      {
        type: "value", min: Math.floor(min), max: Math.ceil(max), splitNumber: compact ? 4 : 5,
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: palette.muted, fontSize: 11, margin: 12, showMinLabel: false, showMaxLabel: false,
          formatter: (value: number) => Math.abs(value) >= 1000 ? `${Number((value / 1000).toFixed(1))}k` : formatValue(value) },
        splitLine: { lineStyle: { color: palette.grid, type: "dashed" } },
        name: unit, nameLocation: "end", nameTextStyle: { color: palette.muted, align: "right", padding: [0, 12, 0, 0], fontSize: 11 },
        axisPointer: { show: false },
      },
      { type: "value", gridIndex: 1, show: false, scale: true },
    ],
    tooltip: {
      trigger: "axis", confine: true, backgroundColor: palette.surface, borderColor: palette.line, borderWidth: 1,
      padding: 0, extraCssText: `box-shadow:0 6px 18px ${palette.shadow};border-radius:8px;`,
      axisPointer: { type: "line", snap: true }, transitionDuration: 0,
      formatter: (params) => {
        const point = Array.isArray(params) ? params.find((entry) => entry.seriesName === "Median forecast · P50" || entry.seriesName === "Actual") : params;
        if (!point || point.seriesName === "Full timeline") return "";
        onInspect(point.dataIndex);
        return tooltipHtml(data, point.dataIndex, unit, visibility, theme);
      },
    },
    toolbox: {
      itemSize: 0, itemGap: 0, showTitle: false,
      feature: { dataZoom: { xAxisIndex: 0, yAxisIndex: "none", filterMode: "none", icon: { zoom: "path://M0,0", back: "path://M0,0" } } },
    },
    dataZoom: [
      {
        type: "inside", xAxisIndex: 0, filterMode: "none", minValueSpan: Math.min(HOUR, extent),
        start: (window.start - domain.start) / extent * 100, end: (window.end - domain.start) / extent * 100,
        zoomOnMouseWheel: "ctrl", moveOnMouseMove: true, moveOnMouseWheel: false, preventDefaultMouseMove: false,
        throttle: 60,
      },
      {
        type: "slider", xAxisIndex: 0, filterMode: "none", bottom: 28, height: 44, left, right,
        minValueSpan: Math.min(HOUR, extent),
        start: (window.start - domain.start) / extent * 100, end: (window.end - domain.start) / extent * 100,
        showDataShadow: false, showDetail: false, brushSelect: false,
        backgroundColor: "transparent", borderColor: palette.line, fillerColor: palette.selection,
        handleSize: "100%", handleStyle: { color: palette.surface, borderColor: palette.navigator, borderWidth: 1 },
        moveHandleSize: 0, emphasis: { handleStyle: { borderColor: accent, color: palette.navigatorFill } },
      },
    ],
    series,
  };
}

import type { EChartsOption, LineSeriesOption } from "echarts";
import type { ForecastData } from "../lib/api";

export const HOUR = 3_600_000;
export const ACTUAL_COLOR = "#64748b";
export const CHART_COLORS: Record<string, string> = {
  load_actual_mw: "#19734b",
  gen_actual_total_mwh: "#8051b0",
  gen_actual_wind_offshore_mwh: "#1675a3",
  gen_actual_wind_onshore_mwh: "#087f78",
  gen_actual_photovoltaics_mwh: "#a46b0a",
  price_sdac_seq1_eur_mwh: "#bd405a",
};

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
  let min = Infinity;
  let max = -Infinity;
  for (let i = 0; i < data.timestamps.length; i++) {
    const time = Date.parse(data.timestamps[i]);
    const before = Date.parse(data.timestamps[Math.max(0, i - 1)]);
    const after = Date.parse(data.timestamps[Math.min(data.timestamps.length - 1, i + 1)]);
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

export function tooltipHtml(data: ForecastData, index: number, unit: string, visibility: ChartVisibility): string {
  const timestamp = data.timestamps[index];
  if (!timestamp) return "";
  const rows: [string, number | null | undefined, string][] = [];
  const color = CHART_COLORS[data.meta.target] ?? CHART_COLORS.load_actual_mw;
  if (visibility.forecast) rows.push(["Forecast · P50", data.p50[index], color]);
  if (visibility.actual) rows.push(["Actual", data.actual[index], ACTUAL_COLOR]);
  if (visibility.forecast && visibility.intervals) rows.push(["Upper · P90", data.p90?.[index], color], ["Lower · P10", data.p10?.[index], color]);
  const actual = data.actual[index];
  const median = data.p50[index];
  if (visibility.forecast && visibility.actual && actual != null && median != null) rows.push(["Actual − forecast", actual - median, ACTUAL_COLOR]);
  return `<div class="forecast-tooltip"><div class="forecast-tooltip-time">${escapeHtml(formatTimestamp(Date.parse(timestamp)))}</div>${rows.filter(([, value]) => value != null).map(([label, value, ink]) => `<div class="forecast-tooltip-row"><span><i style="background:${ink}"></i>${label}</span><strong>${value == null ? "" : formatValue(value)} <small>${escapeHtml(unit)}</small></strong></div>`).join("")}</div>`;
}

export function chartOptions({ data, unit, window, visibility, compact, onInspect }: {
  data: ForecastData;
  unit: string;
  window: TimeWindow;
  visibility: ChartVisibility;
  compact: boolean;
  onInspect: (index: number) => void;
}): EChartsOption {
  const times = data.timestamps.map(Date.parse);
  const domain = forecastDomain(data) ?? window;
  const extent = Math.max(1, domain.end - domain.start);
  const accent = CHART_COLORS[data.meta.target] ?? CHART_COLORS.load_actual_mw;
  const forecastStart = data.p50.findIndex((value) => value !== null);
  const annotationNearRight = times[forecastStart] > window.start + (window.end - window.start) * 0.8;
  const [min, max] = visibleExtent(data, window, visibility);
  const left = compact ? 54 : 72;
  const right = compact ? 18 : 28;
  const line = (name: string, values: (number | null)[], color: string): LineSeriesOption => ({
    name, type: "line", data: times.map((time, i) => [time, values[i]]),
    showSymbol: false, symbol: "circle", symbolSize: 7, connectNulls: false,
    lineStyle: { color, width: 2 }, itemStyle: { color },
    emphasis: { disabled: true }, clip: true, z: 5,
  });
  const series: LineSeriesOption[] = [];
  if (visibility.forecast) series.push({
    ...line("Forecast · P50", data.p50, accent),
    markLine: {
      silent: true, symbol: "none", animation: false,
      lineStyle: { color: "#a3b2aa", width: 1, type: "dashed" },
      label: {
        color: "#5b6b62", fontSize: 11, formatter: "Forecast begins", position: "end", rotate: 0,
        align: annotationNearRight ? "right" : "left", verticalAlign: "bottom",
        offset: [annotationNearRight ? -8 : 8, -8], distance: 0,
      },
      data: forecastStart > 0 && times[forecastStart] >= window.start && times[forecastStart] <= window.end
        ? [{ xAxis: times[forecastStart] }] : [],
    },
  });
  if (visibility.actual) series.push(line("Actual", data.actual, ACTUAL_COLOR));
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
          areaStyle: { color: accent, opacity: 0.075 }, tooltip: { show: false } },
      );
    }
  }
  series.push({
    ...line("Full timeline", data.p50.map((value, i) => value ?? data.actual[i]), "#839d8e"),
    xAxisIndex: 1, yAxisIndex: 1, silent: true, z: 1,
    lineStyle: { color: "#839d8e", width: 1 },
    areaStyle: { color: "#e8eeea", opacity: 0.8 }, tooltip: { show: false },
  });
  return {
    animation: false, backgroundColor: "#ffffff",
    textStyle: { fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif' },
    grid: [
      { left, right, top: 30, bottom: 116 },
      { left, right, height: 44, bottom: 28 },
    ],
    xAxis: [
      {
        type: "time", min: domain.start, max: domain.end, boundaryGap: [0, 0],
        axisLine: { lineStyle: { color: "#dce5df" } }, axisTick: { show: false }, splitLine: { show: false },
        splitNumber: compact ? 3 : 7,
        axisLabel: { color: "#586960", fontSize: 11, margin: 14, hideOverlap: true,
          formatter: (value: number) => window.end - window.start > 3 * 24 * HOUR
            ? formatDay(value) : `${formatTime(value)}\n${formatDay(value)}`, lineHeight: 17 },
        axisPointer: { label: { show: false }, lineStyle: { color: "#86998c", type: "dashed" } },
      },
      { type: "time", gridIndex: 1, min: domain.start, max: domain.end, show: false, boundaryGap: [0, 0] },
    ],
    yAxis: [
      {
        type: "value", min: Math.floor(min), max: Math.ceil(max), splitNumber: compact ? 4 : 5,
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: "#586960", fontSize: 11, margin: 12, showMinLabel: false, showMaxLabel: false,
          formatter: (value: number) => Math.abs(value) >= 1000 ? `${Number((value / 1000).toFixed(1))}k` : formatValue(value) },
        splitLine: { lineStyle: { color: "#e9eeeb", type: "dashed" } },
        name: unit, nameLocation: "end", nameTextStyle: { color: "#586960", align: "right", padding: [0, 12, 0, 0], fontSize: 11 },
        axisPointer: { show: false },
      },
      { type: "value", gridIndex: 1, show: false, scale: true },
    ],
    tooltip: {
      trigger: "axis", confine: true, backgroundColor: "#fff", borderColor: "#dce5df", borderWidth: 1,
      padding: 0, extraCssText: "box-shadow:0 6px 18px rgba(23,33,28,0.08);border-radius:8px;",
      axisPointer: { type: "line", snap: true }, transitionDuration: 0,
      formatter: (params) => {
        const point = Array.isArray(params) ? params.find((entry) => entry.seriesName === "Forecast · P50" || entry.seriesName === "Actual") : params;
        if (!point || point.seriesName === "Full timeline") return "";
        onInspect(point.dataIndex);
        return tooltipHtml(data, point.dataIndex, unit, visibility);
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
        backgroundColor: "transparent", borderColor: "#dce5df", fillerColor: "rgba(30,122,76,0.07)",
        handleSize: "100%", handleStyle: { color: "#fff", borderColor: "#7b9886", borderWidth: 1 },
        moveHandleSize: 0, emphasis: { handleStyle: { borderColor: accent, color: "#e3efe7" } },
      },
    ],
    series,
  };
}

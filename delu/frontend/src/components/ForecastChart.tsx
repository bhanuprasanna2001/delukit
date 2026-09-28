import { ChevronLeft, ChevronRight, Download, Maximize2, Minimize2, Minus, MousePointer2, Move, Plus, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { init, use as registerCharts, type EChartsType } from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, MarkLineComponent, ToolboxComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { berlinLong, targetLabel, type ForecastData } from "../lib/api";
import {
  CHART_PALETTE, HOUR, chartOptions, chartTimeScale, fitWindow, forecastColor,
  formatDay, formatTimestamp, formatValue, windowFromZoom, withTimeGaps, zoomWindow,
  type ChartTheme, type ChartVisibility,
} from "./forecast-chart-options";
import "./forecast-chart.css";

registerCharts([LineChart, DataZoomComponent, GridComponent, MarkLineComponent, ToolboxComponent, TooltipComponent, CanvasRenderer]);

export function ForecastChart({ data, unit, theme, controls }: { data: ForecastData; unit: string; theme: ChartTheme; controls: ReactNode }) {
  const chartData = useMemo(() => withTimeGaps(data), [data]);
  return <InteractiveForecastChart data={chartData} unit={unit} theme={theme} controls={controls} />;
}

function InteractiveForecastChart({ data, unit, theme, controls }: { data: ForecastData; unit: string; theme: ChartTheme; controls: ReactNode }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const scale = useMemo(() => chartTimeScale(data), [data]);
  const domain = scale.domain;
  const [window, setWindow] = useState(domain);
  const [visibility, setVisibility] = useState<ChartVisibility>({ actual: true, forecast: true, intervals: true });
  const [compact, setCompact] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [inspectedIndex, setInspectedIndex] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const accent = forecastColor(data.meta.target, theme);
  const palette = CHART_PALETTE[theme];
  const hasActual = data.actual.some((value) => value !== null);
  const hasForecast = data.p50.some((value) => value !== null);
  const hasIntervals = data.p10?.some((value, i) => value != null && data.p90?.[i] != null) ?? false;
  const fullRange = Math.abs(window.start - domain.start) < 1000 && Math.abs(window.end - domain.end) < 1000;
  const duration = scale.unproject(window.end) - scale.unproject(window.start);
  const inspect = useCallback((index: number) => setInspectedIndex(index), []);
  const options = useMemo(() => chartOptions({ data, unit, window, visibility, compact, theme, onInspect: inspect }), [data, unit, window, visibility, compact, theme, inspect]);

  useEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    const chart = init(plot, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    chart.on("datazoom", (event: unknown) => {
      const next = windowFromZoom(event, domain);
      if (next) { setWindow(next); setInspectedIndex(null); }
    });
    let resizeFrame = 0;
    const observer = new ResizeObserver(([entry]) => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        setCompact(entry.contentRect.width < 600);
        chart.resize({ width: entry.contentRect.width, height: entry.contentRect.height });
      });
    });
    observer.observe(plot);
    return () => { observer.disconnect(); cancelAnimationFrame(resizeFrame); chart.dispose(); chartRef.current = null; };
  }, [domain]);

  useEffect(() => {
    chartRef.current?.setOption(options, { replaceMerge: ["series"] });
  }, [options]);

  useEffect(() => {
    const onFullscreen = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener("fullscreenchange", onFullscreen);
    return () => document.removeEventListener("fullscreenchange", onFullscreen);
  }, []);

  const changeMode = (selected: boolean) => {
    setSelectionMode(selected);
    chartRef.current?.dispatchAction({ type: "takeGlobalCursor", key: "dataZoomSelect", dataZoomSelectActive: selected });
  };
  const reset = () => {
    setWindow(domain); setInspectedIndex(null); changeMode(false);
    chartRef.current?.dispatchAction({ type: "hideTip" });
  };
  const pan = (direction: number) => setWindow((current) => fitWindow(current.start + direction * (current.end - current.start) * 0.75, current.end - current.start, domain));
  const zoom = (factor: number) => setWindow((current) => zoomWindow(current, factor, domain));
  const selectHours = (hours: number) => {
    const firstForecast = data.p50.findIndex((value) => value !== null);
    const forecastStart = firstForecast < 0 ? scale.unproject(domain.start) : Date.parse(data.timestamps[firstForecast]);
    const realEnd = Math.min((fullRange ? forecastStart : scale.unproject(window.start)) + hours * HOUR, scale.unproject(domain.end));
    const realStart = Math.max(scale.unproject(domain.start), realEnd - hours * HOUR);
    setWindow({ start: scale.project(realStart), end: scale.project(realEnd) });
    setInspectedIndex(null);
  };
  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await rootRef.current?.requestFullscreen();
    } catch { setAnnouncement("Fullscreen is unavailable in this browser."); }
  };
  const exportImage = async () => {
    const chart = chartRef.current;
    if (!chart) return;
    const image = new Image();
    image.src = chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: palette.surface, excludeComponents: ["toolbox"] });
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(image.width, 1400);
    canvas.height = image.height + 220;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.fillStyle = palette.surface;
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = palette.text;
    context.font = "600 32px sans-serif";
    context.fillText(`${targetLabel(data.meta.target)} forecast`, 48, 48);
    context.fillStyle = palette.muted;
    context.font = "22px sans-serif";
    context.fillText(`${formatTimestamp(scale.unproject(window.start))} to ${formatTimestamp(scale.unproject(window.end))}`, 48, 86);
    const keys = [
      { label: "Median forecast · P50", color: accent, band: false, visible: visibility.forecast },
      { label: "Actual", color: palette.actual, band: false, visible: visibility.actual },
      { label: "Quantile ranges · P10–P90", color: accent, band: true, visible: hasIntervals && visibility.forecast && visibility.intervals },
    ];
    let legendX = 48;
    for (const key of keys.filter((entry) => entry.visible)) {
      context.fillStyle = key.color;
      context.globalAlpha = key.band ? palette.bandKeyOpacity : 1;
      if (key.label === "Actual") {
        for (let x = 0; x < 32; x += 9) context.fillRect(legendX + x, 111, 5, 3);
      } else {
        context.fillRect(legendX, key.band ? 105 : 111, 32, key.band ? 16 : 3);
      }
      context.globalAlpha = 1;
      context.fillStyle = palette.muted;
      context.fillText(key.label, legendX + 44, 120);
      legendX += 44 + context.measureText(key.label).width + 40;
    }
    context.drawImage(image, 0, 140);
    context.fillText(`DELU · Built ${berlinLong(data.meta.generated_at)} · Europe/Berlin · ${unit}${scale.shortenedGap ? " · Empty time gap shortened" : ""}`, 48, canvas.height - 32);
    const link = document.createElement("a");
    link.download = `delu-${data.meta.target}-${data.meta.date}-${data.meta.span}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click(); setAnnouncement("Chart image saved.");
  };
  const inspectPoint = (direction: number, edge?: "start" | "end") => {
    const first = Math.max(0, data.timestamps.findIndex((value) => scale.project(Date.parse(value)) >= window.start));
    const last = data.timestamps.findLastIndex((value) => scale.project(Date.parse(value)) <= window.end);
    const index = edge === "start" ? first : edge === "end" ? last : Math.max(first, Math.min(last, (inspectedIndex ?? first - direction) + direction));
    if (index < 0) return;
    setInspectedIndex(index);
    chartRef.current?.dispatchAction({ type: "showTip", seriesIndex: 0, dataIndex: index });
    const forecast = visibility.forecast ? data.p50[index] : null;
    const actual = visibility.actual ? data.actual[index] : null;
    setAnnouncement(`${formatTimestamp(Date.parse(data.timestamps[index]))}. ${forecast != null ? `Median forecast P50 ${formatValue(forecast)} ${unit}.` : ""} ${actual != null ? `Actual ${formatValue(actual)} ${unit}.` : ""}`);
  };
  const presets = data.meta.span === "d10" ? [{ label: "24h", hours: 24 }, { label: "48h", hours: 48 }, { label: "7d", hours: 168 }]
    : [{ label: "6h", hours: 6 }, { label: "12h", hours: 12 }, { label: "24h", hours: 24 }];
  const title = `${targetLabel(data.meta.target)} forecast`;

  return (
    <div className="forecast-chart" ref={rootRef}>
      <div className="forecast-chart-heading">
        <h2 className="forecast-chart-title">{title}</h2>
        {controls}
      </div>

      <div className="forecast-chart-toolbar">
        <div className="forecast-range-presets" role="group" aria-label="Visible time range">
          <button type="button" aria-pressed={fullRange} onClick={reset}>Full horizon</button>
          {presets.filter(({ hours }) => hours * HOUR < scale.unproject(domain.end) - scale.unproject(domain.start)).map(({ label, hours }) => (
            <button key={label} type="button" aria-pressed={!fullRange && Math.abs(duration - hours * HOUR) < 1000} onClick={() => selectHours(hours)}>{label}</button>
          ))}
        </div>
        <div className="forecast-chart-tools">
          <div role="group" aria-label="Navigate chart">
            <button type="button" aria-label="Pan earlier" title="Pan earlier" disabled={window.start <= domain.start} onClick={() => pan(-1)}><ChevronLeft /></button>
            <button type="button" aria-label="Zoom in" title="Zoom in (+)" disabled={duration <= HOUR} onClick={() => zoom(0.5)}><Plus /></button>
            <button type="button" aria-label="Zoom out" title="Zoom out (−)" disabled={fullRange} onClick={() => zoom(2)}><Minus /></button>
            <button type="button" aria-label="Pan later" title="Pan later" disabled={window.end >= domain.end} onClick={() => pan(1)}><ChevronRight /></button>
          </div>
          <div role="group" aria-label="Chart interaction">
            <button type="button" aria-label="Pan mode" title="Drag to pan" aria-pressed={!selectionMode} onClick={() => changeMode(false)}><Move /></button>
            <button type="button" aria-label="Select to zoom" title="Drag across the plot to zoom" aria-pressed={selectionMode} onClick={() => changeMode(true)}><MousePointer2 /></button>
          </div>
          <div role="group" aria-label="Chart actions">
            <button type="button" aria-label="Reset chart range" title="Reset to full horizon" disabled={fullRange && !selectionMode} onClick={reset}><RotateCcw /></button>
            <button type="button" aria-label="Save chart image" title="Save chart as PNG" onClick={exportImage}><Download /></button>
            <button type="button" aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen chart"} title={fullscreen ? "Exit fullscreen" : "Fullscreen"} onClick={toggleFullscreen}>{fullscreen ? <Minimize2 /> : <Maximize2 />}</button>
          </div>
        </div>
      </div>

      <div className="forecast-chart-legend" role="group" aria-label="Chart series">
        <button type="button" aria-pressed={visibility.forecast} disabled={!hasForecast || !visibility.actual || !hasActual} onClick={() => setVisibility((current) => ({ ...current, forecast: !current.forecast }))}>
          <span className="forecast-line-key" style={{ backgroundColor: accent }} />Median forecast · P50
        </button>
        <button type="button" aria-pressed={visibility.actual} disabled={!hasActual || !visibility.forecast || !hasForecast} onClick={() => setVisibility((current) => ({ ...current, actual: !current.actual }))}>
          <span className="forecast-line-key forecast-actual-key" style={{ color: palette.actual }} />Actual
        </button>
        {hasIntervals ? <button type="button" aria-pressed={visibility.intervals} disabled={!visibility.forecast} onClick={() => setVisibility((current) => ({ ...current, intervals: !current.intervals }))} title="Show or hide P10–P90, P20–P80, P30–P70, and P40–P60 quantile ranges">
          <span className="forecast-band-key" style={{ backgroundColor: accent, opacity: palette.bandKeyOpacity }} />Quantile ranges · P10–P90
        </button> : null}
        {scale.shortenedGap ? <span className="forecast-chart-gap-note" title="The empty period between the last actual value and the forecast is shortened on this timeline.">Empty time gap shortened</span> : null}
      </div>

      <div className="forecast-chart-canvas" ref={plotRef} tabIndex={0} role="group"
        aria-label={`${title}. Left and right arrows inspect values. Plus and minus zoom. Shift and arrow keys pan. Home and End inspect the edges. Escape clears the tooltip.`}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            const direction = event.key === "ArrowLeft" ? -1 : 1;
            if (event.shiftKey) pan(direction); else inspectPoint(direction);
          } else if (event.key === "+" || event.key === "=" || event.key === "-") {
            event.preventDefault(); zoom(event.key === "-" ? 2 : 0.5);
          } else if (event.key === "Home" || event.key === "End") {
            event.preventDefault(); inspectPoint(0, event.key === "Home" ? "start" : "end");
          } else if (event.key === "Escape") {
            setInspectedIndex(null); changeMode(false); chartRef.current?.dispatchAction({ type: "hideTip" });
          }
        }}
      />
      {!hasForecast && !hasActual ? <p className="forecast-chart-empty">No values in this forecast.</p> : null}
      <div className="forecast-navigator-labels" aria-hidden="true"><span>{formatDay(scale.unproject(domain.start))}</span><span>{formatDay(scale.unproject(domain.end))}</span></div>
      <div className="forecast-chart-footer">
        <span className="forecast-window-label" aria-live="polite">{formatTimestamp(scale.unproject(window.start))} <span aria-hidden="true">→</span> {formatTimestamp(scale.unproject(window.end))}</span>
        <div className="forecast-chart-meta">
          <span className="forecast-chart-published">Built {berlinLong(data.meta.generated_at)}</span>
          <span>Europe/Berlin</span>
        </div>
      </div>
      <span className="sr-only" role="status">{announcement}</span>
    </div>
  );
}

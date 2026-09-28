import assert from "node:assert/strict";
import { test } from "node:test";
import type { ForecastData } from "../src/lib/api.ts";
import { fitWindow, formatTimestamp, HOUR, tooltipHtml, visibleExtent, windowFromZoom, withTimeGaps, zoomWindow } from "../src/components/forecast-chart-options.ts";

const data: ForecastData = {
  meta: { date: "2026-10-24", gate: "0530", span: "d1", target: "price_sdac_seq1_eur_mwh", model: "xgboost", rows: 4, generated_at: "2026-10-24T03:30:00Z" },
  timestamps: ["2026-10-25T00:00:00Z", "2026-10-25T00:15:00Z", "2026-10-25T01:00:00Z", "2026-10-25T01:15:00Z"],
  p50: [null, -20, 10, 30], actual: [-35, null, 15, null],
  p10: [null, -40, -10, 10], p90: [null, 0, 30, 50],
  p20: null, p30: null, p40: null, p60: null, p70: null, p80: null,
};
const visible = { actual: true, forecast: true, intervals: true };

test("panning stops at the horizon edges without shortening the selected window", () => {
  assert.deepEqual(fitWindow(-HOUR, 6 * HOUR, { start: 0, end: 24 * HOUR }), { start: 0, end: 6 * HOUR });
  assert.deepEqual(fitWindow(23 * HOUR, 6 * HOUR, { start: 0, end: 24 * HOUR }), { start: 18 * HOUR, end: 24 * HOUR });
});

test("zoom is centered and cannot shrink below one hour or escape the horizon", () => {
  assert.deepEqual(zoomWindow({ start: 0, end: 24 * HOUR }, 0.5, { start: 0, end: 24 * HOUR }), { start: 6 * HOUR, end: 18 * HOUR });
  assert.deepEqual(fitWindow(0, 1, { start: 0, end: 24 * HOUR }), { start: 0, end: HOUR });
  assert.deepEqual(fitWindow(0, 2 * HOUR, { start: 0, end: 0 }), { start: 0, end: 0 });
});

test("slider and rectangular selections produce the same visible timestamps", () => {
  const domain = { start: 0, end: 10 * HOUR };
  assert.deepEqual(windowFromZoom({ start: 20, end: 40 }, domain), { start: 2 * HOUR, end: 4 * HOUR });
  assert.deepEqual(windowFromZoom({ batch: [{ startValue: 2 * HOUR, endValue: 4 * HOUR }] }, domain), { start: 2 * HOUR, end: 4 * HOUR });
  assert.equal(windowFromZoom({ start: "20", end: 40 }, domain), null);
});

test("missing quarters break lines and bands without moving observations", () => {
  const result = withTimeGaps(data);
  assert.deepEqual(result.timestamps, ["2026-10-25T00:00:00Z", "2026-10-25T00:15:00Z", "2026-10-25T00:30:00.000Z", "2026-10-25T01:00:00Z", "2026-10-25T01:15:00Z"]);
  assert.deepEqual(result.actual, [-35, null, null, 15, null]);
  assert.deepEqual(result.p50, [null, -20, null, 10, 30]);
  assert.deepEqual(result.p10, [null, -40, null, -10, 10]);
  assert.equal(result.p20, null);
});

test("Berlin's repeated autumn hour has distinct timezone labels", () => {
  assert.match(formatTimestamp(Date.parse("2026-10-25T00:00:00Z")), /02:00 CEST$/);
  assert.match(formatTimestamp(Date.parse("2026-10-25T01:00:00Z")), /02:00 CET$/);
});

test("negative price intervals remain within the visible y range", () => {
  assert.deepEqual(visibleExtent(data, { start: Date.parse(data.timestamps[0]), end: Date.parse(data.timestamps[3]) }, visible), [-50.8, 60.8]);
});

test("inspection reports exact values, differences, and missing actuals honestly", () => {
  const tooltip = tooltipHtml(data, 2, "€/MWh", visible);
  assert.match(tooltip, /Forecast · P50/);
  assert.ok(tooltip.includes("<strong>10 <small>€/MWh"));
  assert.match(tooltip, /Actual − forecast/);
  assert.ok(tooltip.includes("<strong>5 <small>€/MWh"));
  assert.doesNotMatch(tooltipHtml(data, 1, "€/MWh", visible), />Actual</);
  assert.doesNotMatch(tooltipHtml(data, 2, "€/MWh", { ...visible, intervals: false }), /P90|P10/);
});

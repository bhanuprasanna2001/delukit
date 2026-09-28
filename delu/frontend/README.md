<div align="center">

<img src="../../public/delu.svg" alt="delu logo" width="80" />

# 🎨 delu frontend

**Forecast exploration with Apache ECharts, downloads, and API keys.**

[![React 19](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite)](https://vitejs.dev/)
[![Tailwind 4](https://img.shields.io/badge/Tailwind-4-38BDF8?style=flat-square&logo=tailwindcss)](https://tailwindcss.com/)

[⬆️ Serving layer](../README.md) · [🏠 Project root](../../README.md)

</div>

---

## 🚀 Run it

```bash
npm ci
npm run dev     # dev server
npm run build   # outputs to dist; Docker copies it into backend/static
npm run lint
npm test
```

The DELU Docker image copies the production build into FastAPI's static directory. For local development, Vite proxies API requests to `localhost:8000`.

## 👀 Views

| View | What it does |
|---|---|
| 📈 `Forecasts` | Run-day stepper, 05:30/11:30 toggle, day-ahead and 10-day horizons, nested P10–P90 intervals, actuals, timeline navigator, zoom, and inspection |
| 📥 `Download` | Range, horizon, timezone & format picker — verified accounts only |
| 🔑 `Dashboard` | Key display, daily usage bar, refresh, in-app Swagger for `/v1/forecast` |
| 📄 `About`, `Legal`, `Auth` | Explainer, terms / privacy / attribution / contact, signup & login |

## 🧩 Where things live

- `lib/api.ts` — typed client + labels
- `components/ForecastChart.tsx` — chart lifecycle, navigation, keyboard inspection, fullscreen, and PNG export
- `components/forecast-chart-options.ts` — timestamp formatting, gap handling, visible ranges, series, and ECharts options
- `components/forecast-chart.css` — chart layout and controls
- `tests/forecast-chart.test.ts` — range boundaries, missing quarters, negative prices, DST labels, and exact tooltip values

## Explore a forecast

Both horizon choices open with all available values, including historical actuals. When the gap between the last actual and the first day-ahead forecast is long enough, the chart shortens that empty period so the forecast takes about 62% of the width. The original timestamps remain in labels and tooltips. Choose a range preset or drag the timeline handles to narrow the view. Drag the plot to pan. Select the pointer tool to drag a region for zooming, or hold Ctrl while scrolling. **Full horizon** resets the view.

The legend toggles actuals and each available quantile range separately. The tooltip and PNG show only the selected P10–P90, P20–P80, P30–P70, and P40–P60 ranges. The y-axis adapts to the visible data. Point forecasts have no area fill. Missing quarters break the plotted lines and bands. All time labels use Europe/Berlin; tooltips and range labels include the daylight-saving offset name.

Focus the plot to inspect values with the arrow keys. Home and End select the visible edges. Plus and minus zoom, Shift with an arrow key pans, and Escape clears inspection. Native buttons provide keyboard access to the range presets, fullscreen, and PNG export.

## Chart library choice

Apache ECharts supplies zoom, pan, tooltips, canvas rendering, and range selection under the Apache 2.0 license. The chart imports only the components it uses and loads in a separate chunk. See the [ECharts features](https://echarts.apache.org/en/feature.html) and [license](https://github.com/apache/echarts/blob/master/LICENSE).

[Highcharts Stock](https://www.highcharts.com/docs/stock/navigator) has a mature navigator and timeline controls, but introduces a commercial licensing decision. [TradingView Lightweight Charts](https://tradingview.github.io/lightweight-charts/plugins) supports custom range series and plugins, but this forecast interface would require more bespoke navigation and interval integration. ECharts fits the existing React application without a wrapper or a new licensing requirement.

---

<div align="center">
  <sub>Forecast navigation stays in the frontend. Published values and product selection stay with the API.</sub>
</div>

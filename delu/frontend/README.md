# delu frontend

Chart, download and API-key UI for DELU. React 19 + Vite + Tailwind 4, no chart library — the forecast plot is a small custom SVG.

## Run it

```bash
npm ci
npm run dev     # dev server
npm run build   # outputs to ../backend/static
npm run lint
```

## Views

- `Forecasts` — run-day stepper, 05:30/11:30 toggle, D+1/10-day horizon, P10/P50/P90 band with actuals and hover tooltip
- `Download` — range, horizon, timezone and format picker, verified accounts only
- `Dashboard` — key display, daily usage bar, refresh, in-app Swagger for `/v1/forecast`
- `About`, `Legal`, `Auth` — explainer, terms/privacy/attribution/contact, signup and login

`lib/api.ts` holds the typed client and labels. `components/ForecastChart.tsx` is the plot.

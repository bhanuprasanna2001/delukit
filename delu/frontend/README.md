<div align="center">

<img src="../../public/delu.svg" alt="delu logo" width="80" />

# 🎨 delu frontend

**Chart, download & API-key UI — no chart library, just a small custom SVG.**

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
npm run build   # outputs to ../backend/static
npm run lint
```

`npm run build` is what the FastAPI process serves — no separate deploy.

## 👀 Views

| View | What it does |
|---|---|
| 📈 `Forecasts` | Run-day stepper, 05:30/11:30 toggle, D+1 / 10-day horizon, P10/P50/P90 band with actuals + hover tooltip |
| 📥 `Download` | Range, horizon, timezone & format picker — verified accounts only |
| 🔑 `Dashboard` | Key display, daily usage bar, refresh, in-app Swagger for `/v1/forecast` |
| 📄 `About`, `Legal`, `Auth` | Explainer, terms / privacy / attribution / contact, signup & login |

## 🧩 Where things live

- `lib/api.ts` — typed client + labels
- `components/ForecastChart.tsx` — the custom SVG plot

---

<div align="center">
  <sub>Custom SVG on purpose — one less dependency, full control over bands & tooltips.</sub>
</div>

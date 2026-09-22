import { Clock, Database, KeyRound, Quote } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import type { View } from "../App";

const STATS: [string, string][] = [
  ["2", "runs every day, 05:30 and 11:30"],
  ["6", "forecast series, load to price"],
  ["10-day", "probabilistic horizon"],
  ["5,000", "API calls a day, per key"],
];

const CARDS = [
  {
    icon: Clock,
    title: "Two runs a day",
    body: "The 05:30 run lands before the morning auctions. The 11:30 run additionally sees the EXAA results and the ENTSO-E day-ahead load forecast, so its day-ahead read is cleaner.",
  },
  {
    icon: Database,
    title: "Actuals included",
    body: "Every run carries the most recent realised values from ENTSO-E and SMARD, so each forecast can be judged against what really happened. The white line on the chart is measured history, not model output.",
  },
  {
    icon: KeyRound,
    title: "Built to be used",
    body: "Read forecasts in the browser, export the history as CSV, parquet or XLSX, or call the one-endpoint API. Sign up, confirm the email, and the key is yours.",
  },
  {
    icon: Quote,
    title: "Cite it",
    body: "Free to use as a benchmark or baseline, including in publications — state which run the result is based on. Building competing forecasts for public leaderboards is the one thing excluded.",
  },
] as const;

export function About({ go }: { go: (v: View) => void }) {
  return (
    <div className="grid gap-8">
      <p className="max-w-2xl text-base leading-relaxed text-ink-soft">
        DELU publishes day-ahead and 10-day point and probabilistic forecasts
        for the German–Luxembourgian bidding zone — load, solar, onshore and
        offshore wind, total generation, and the day-ahead price — rebuilt
        twice daily by a gradient-boosted model.
      </p>

      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
        {STATS.map(([n, label]) => (
          <div key={label} className="grid gap-1 bg-card px-4 py-5">
            <dt className="order-2 text-xs leading-snug text-ink-soft">{label}</dt>
            <dd className="order-1 font-display text-2xl font-bold tracking-tight tnum">
              {n}
            </dd>
          </div>
        ))}
      </dl>

      <div className="grid gap-4 sm:grid-cols-2">
        {CARDS.map((c) => (
          <Card key={c.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <c.icon className="size-4 text-brand" />
                {c.title}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-relaxed text-ink-soft">{c.body}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <p className="text-sm text-ink-soft">
        Forecasts are model output, not financial advice — see the{" "}
        <button type="button" className="cursor-pointer underline" onClick={() => go("terms")}>
          terms of use
        </button>
        . Market data:{" "}
        <button type="button" className="cursor-pointer underline" onClick={() => go("attribution")}>
          data attribution
        </button>
        . Questions:{" "}
        <button type="button" className="cursor-pointer underline" onClick={() => go("contact")}>
          contact
        </button>
        .
      </p>
    </div>
  );
}

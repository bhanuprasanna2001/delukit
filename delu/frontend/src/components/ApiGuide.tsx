import { ChevronDown } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";

const parameters = [
  ["date", "Latest matching origin date", "YYYY-MM-DD, for example 2026-09-21"],
  ["gate", "Latest available run", "0530 or 1130, in Europe/Berlin"],
  ["span", "d1", "d1 for day ahead; d10 for ten days"],
  ["target", "load_actual_mw", "A published quantity from /api/options"],
  ["type", "probabilistic", "probabilistic for P10-P90; point for P50"],
];

const pythonExample = `import os
import requests

base_url = "https://YOUR_DELU_HOST"
response = requests.get(
    f"{base_url}/v1/forecast",
    headers={"X-API-Key": os.environ["DELU_API_KEY"]},
    params={
        "span": "d1",
        "target": "load_actual_mw",
        "type": "probabilistic",
    },
    timeout=20,
)
response.raise_for_status()
forecast = response.json()

for timestamp, median in zip(forecast["timestamps"], forecast["p50"]):
    print(timestamp, median)`;

function GuideSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="group py-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium marker:content-none [&::-webkit-details-marker]:hidden">
        {title}
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-ink-soft transition-transform duration-200 group-open:rotate-180" />
      </summary>
      <div className="pt-3 text-sm leading-relaxed text-ink-soft [&_code]:font-mono [&_code]:text-xs">
        {children}
      </div>
    </details>
  );
}

export function ApiGuide() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>How to use the API</CardTitle>
        <CardDescription>Call the forecast endpoint from Python, choose a run, and read the result.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="divide-y divide-line border-y border-line">
          <GuideSection title="Python quickstart">
            <div className="grid gap-3">
              <p>
                Confirm your email and copy your key when it appears. Install <code>requests</code>{" "}
                with <code>python -m pip install requests</code>, set <code>DELU_API_KEY</code> in
                your environment, and replace the base URL with this site&apos;s address.
              </p>
              <pre className="overflow-x-auto rounded-md bg-night px-4 py-3 text-xs leading-relaxed text-on-night"><code>{pythonExample}</code></pre>
              <p>
                You can also send <code>Authorization: Bearer YOUR_KEY</code>. Use the Authorize
                button in the reference below to try the endpoint in your browser.
              </p>
            </div>
          </GuideSection>

          <GuideSection title="Query parameters">
            <p className="mb-3">
              All parameters are optional. Omit date and gate for the latest published run that
              matches the requested quantity and span. Check <a className="text-brand-deep underline underline-offset-2" href="/api/options">/api/options</a> for available dates, gates, spans, and targets.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[540px] text-left text-sm">
                <thead className="border-b border-line text-ink">
                  <tr><th className="py-2 pr-4 font-medium">Parameter</th><th className="py-2 pr-4 font-medium">Default</th><th className="py-2 font-medium">Use</th></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {parameters.map(([name, defaultValue, use]) => (
                    <tr key={name}>
                      <td className="py-2 pr-4 font-mono text-xs text-ink">{name}</td>
                      <td className="py-2 pr-4">{defaultValue}</td>
                      <td className="py-2">{use}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GuideSection>

          <GuideSection title="Response, limits, and errors">
            <div className="grid gap-3">
              <p>
                <code>timestamps</code> and every value array align by position. <code>p50</code>
                {" "}is the median. A probabilistic request also returns <code>p10</code> through{" "}
                <code>p90</code>; a point request sets those arrays to null. <code>actual</code>{" "}
                contains observations where available. Individual null values mean missing data.{" "}
                <code>meta</code> identifies the origin date, gate, span, target, and model.
              </p>
              <p>
                A key allows 60 requests per minute and 5,000 per day. A 401 means the key is
                missing or invalid, 404 means that run has no matching forecast, and 429 means a
                limit was reached. On 429, check the <code>Retry-After</code> header before retrying.
              </p>
            </div>
          </GuideSection>
        </div>
      </CardContent>
    </Card>
  );
}

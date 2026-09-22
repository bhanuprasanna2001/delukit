import {
  AlertCircle,
  ArrowUpRight,
  BadgeCheck,
  CheckCircle2,
  Database,
  Loader2,
  Lock,
  Mail,
  Scale,
  Send,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { sendContact } from "../lib/api";

export const CONTACT_EMAIL = "bhanu.prasanna2001@gmail.com";
const UPDATED = "September 2026";

function Hero({ lede }: { lede: string }) {
  return (
    <div className="grid gap-3">
      <p className="max-w-2xl text-base leading-relaxed text-ink-soft">{lede}</p>
      <p className="flex items-center gap-1.5 text-xs text-ink-faint">
        <BadgeCheck className="size-3.5" />
        Last updated {UPDATED} · Plain language, no legal fog
      </p>
    </div>
  );
}

function Section({
  n,
  icon: Icon,
  title,
  children,
}: {
  n: string;
  icon: typeof ShieldCheck;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2.5 text-base">
          <span className="flex size-7 items-center justify-center rounded-md bg-brand-tint text-brand-deep">
            <Icon className="size-4" />
          </span>
          <span>
            <span className="mr-2 font-mono text-xs font-normal text-ink-faint">{n}</span>
            {title}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm leading-relaxed text-ink-soft">
        {children}
      </CardContent>
    </Card>
  );
}

function DataTable({ rows }: { rows: [string, string, string][] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <table className="w-full text-left text-[13px]">
        <thead>
          <tr className="bg-paper text-xs text-ink-faint">
            <th className="px-3 py-2 font-medium">Data</th>
            <th className="px-3 py-2 font-medium">Why</th>
            <th className="px-3 py-2 font-medium">Legal basis</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-card">
          {rows.map(([d, w, b]) => (
            <tr key={d}>
              <td className="px-3 py-2 font-medium text-ink">{d}</td>
              <td className="px-3 py-2">{w}</td>
              <td className="px-3 py-2 text-ink-faint">{b}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Privacy() {
  return (
    <div className="grid gap-6">
      <Hero lede="DELU collects the minimum needed to run accounts and the forecast API — nothing else. No analytics, no trackers, no ads. You can delete everything yourself at any time."
      />

      <div className="grid gap-4">
        <Section n="01" icon={Database} title="What we store, and why">
          <DataTable
            rows={[
              ["Email address", "Account identity, verification, replies", "Contract · Art. 6(1)(b)"],
              ["Password hash (PBKDF2, 200k rounds)", "Sign-in. The password itself is never stored", "Contract · Art. 6(1)(b)"],
              ["Email confirmed? + API key id", "Unlock the key, enforce one key per account", "Contract · Art. 6(1)(b)"],
              ["API call counters (per min / per day)", "Rate limits. Counts only — never call contents", "Legitimate interest · Art. 6(1)(f)"],
              ["Session cookie (7 days, HttpOnly)", "Keep you signed in. No tracking data", "Strictly necessary"],
              ["Contact messages", "Answer you, then only as long as the thread needs", "Legitimate interest · Art. 6(1)(f)"],
            ]}
          />
          <p>
            Controller: DELU, run by Bhanu Prasanna —{" "}
            <a className="underline" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>
            . Giving account data is required to use the API; without an email
            there is no account to verify or key to issue.
          </p>
        </Section>

        <Section n="02" icon={Send} title="Who else touches your data">
          <p>
            Email delivery runs through{" "}
            <a
              className="underline"
              href="https://resend.com"
              target="_blank"
              rel="noreferrer"
            >
              Resend
            </a>{" "}
            (verification mails, contact-form forwarding) under its data
            processing terms. Nothing else: no analytics scripts, no
            third-party trackers, no advertising, no sale of personal data —
            ever.
          </p>
        </Section>

        <Section n="03" icon={Lock} title="How long we keep it">
          <ul className="grid gap-1.5">
            {[
              "Account + key: until you delete the account. Deletion removes the account, key and usage counters immediately.",
              "Sessions: expire after 7 days. Verification links: expire after 24 hours.",
              "Contact messages: kept only as long as the conversation needs, then deleted on request.",
            ].map((t) => (
              <li key={t} className="flex gap-2">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-brand" />
                {t}
              </li>
            ))}
          </ul>
        </Section>

        <Section n="04" icon={ShieldCheck} title="Your rights (GDPR Arts. 15–21)">
          <p>
            Access, rectify, erase, restrict, port, or object — write to{" "}
            <a className="underline" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>{" "}
            from your account email and requests are answered within one month.
            Self-serve deletion lives under API &amp; keys → Delete account
            (password confirmation required). No account access? Email us and it
            is removed anyway.
          </p>
          <p className="text-[13px] text-ink-faint">
            You also have the right to lodge a complaint with your national data
            protection authority. No automated decision-making or profiling
            takes place on this service.
          </p>
        </Section>
      </div>
    </div>
  );
}

export function Terms() {
  return (
    <div className="grid gap-6">
      <Hero lede="Short version: use the forecasts for research and operations, cite the run you used, keep your key secret, and don't resell the API as a competing forecast leaderboard."
      />

      <div className="grid gap-4">
        <Section n="01" icon={Database} title="The service">
          <p>
            DELU publishes day-ahead and 10-day point and probabilistic (P10 /
            P50 / P90) forecasts for the German–Luxembourgian bidding zone —
            load, solar, onshore and offshore wind, total generation, and the
            day-ahead price — rebuilt twice daily (05:30 and 11:30
            Europe/Berlin). Each verified account gets one API key with 5,000
            calls a day (per-minute limits also apply). Calls made with your key
            count as yours: keep it secret, rotate it from API &amp; keys if
            exposed.
          </p>
        </Section>

        <Section n="02" icon={BadgeCheck} title="Citation and fair use">
          <p>
            You may use the forecasts as a benchmark or baseline, including in
            publications — please cite this work once the paper reference is
            published, and always state which run (05:30 or 11:30) a result is
            based on. The one restriction: the forecasts may not be used to
            build competing forecasts of the same target quantities for
            submission to public benchmarks or leaderboards.
          </p>
        </Section>

        <Section n="03" icon={AlertCircle} title="No warranty, no advice">
          <p>
            Forecasts are model output, not financial, trading, or operational
            advice. No warranty on completeness, accuracy, or availability; the
            service may change, rate-limit, or stop at any time. Underlying
            realised data comes from third parties (see Data attribution) and
            can arrive late or be revised.
          </p>
        </Section>

        <Section n="04" icon={Scale} title="Acceptable use and termination">
          <p>
            Don't scrape around rate limits, share keys across people, attack
            the service, or break the law with it. Accounts that do are blocked;
            you can delete yours at any time. Liability is limited to the
            extent permitted by law — the service is free research
            infrastructure. If these terms change materially, the update is
            noted here with a new date; continued use means acceptance.
          </p>
        </Section>
      </div>
    </div>
  );
}

const TOPICS = [
  "Data correction",
  "Data question",
  "Benchmark citation",
  "Privacy / deletion request",
  "API problem",
  "Something else",
];

export function Contact() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [topic, setTopic] = useState(TOPICS[0]);
  const [message, setMessage] = useState("");
  const [state, setState] = useState<
    { status: "idle" } | { status: "busy" } | { status: "ok"; detail: string } | { status: "error"; detail: string }
  >({ status: "idle" });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState({ status: "busy" });
    try {
      const res = await sendContact({ name, email, topic, message });
      setState({ status: "ok", detail: res.detail });
      setMessage("");
    } catch (err) {
      setState({
        status: "error",
        detail: err instanceof Error ? err.message : "Could not send.",
      });
    }
  }

  const valid =
    name.trim().length >= 2 && /.+@.+\..+/.test(email) && message.trim().length >= 10;

  return (
    <div className="grid gap-6">
      <Hero lede="Corrections, data questions, benchmark citations, privacy requests — anything about DELU lands in one inbox and is read by the person who runs the pipeline. Expect a reply within 2 working days."
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Send className="size-4 text-brand" />
              Send a message
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="grid gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="ct-name">Name</Label>
                  <Input
                    id="ct-name"
                    autoComplete="name"
                    placeholder="Ada Lovelace"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="ct-email">Email</Label>
                  <Input
                    id="ct-email"
                    type="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="ct-topic">Topic</Label>
                <div className="flex flex-wrap gap-1.5">
                  {TOPICS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTopic(t)}
                      className={
                        t === topic
                          ? "rounded-full bg-brand px-3 py-1.5 text-xs font-medium text-white"
                          : "rounded-full border border-line bg-card px-3 py-1.5 text-xs text-ink-soft hover:bg-paper"
                      }
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="ct-message">
                  Message{" "}
                  <span className="font-normal text-ink-faint">
                    — include the forecast date + run (05:30 / 11:30) for data questions
                  </span>
                </Label>
                <textarea
                  id="ct-message"
                  rows={6}
                  maxLength={4000}
                  placeholder="What did you see, and what did you expect?"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  className="w-full rounded-md border border-line bg-card px-3 py-2 text-sm placeholder:text-ink-faint focus:border-brand"
                />
                <p className="text-right text-xs text-ink-faint tnum">
                  {message.length}/4000
                </p>
              </div>
              {state.status === "ok" ? (
                <p className="flex items-center gap-2 rounded-md bg-brand-tint px-3 py-2 text-sm text-brand-deep">
                  <CheckCircle2 className="size-4" />
                  {state.detail}
                </p>
              ) : null}
              {state.status === "error" ? (
                <p className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
                  <AlertCircle className="size-4" />
                  {state.detail}
                </p>
              ) : null}
              <div>
                <Button type="submit" disabled={state.status === "busy" || !valid}>
                  {state.status === "busy" ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Send />
                  )}
                  {state.status === "busy" ? "Sending…" : "Send message"}
                </Button>
              </div>
              <p className="text-xs leading-relaxed text-ink-faint">
                Your name, email and message are used only to reply (GDPR Art.
                6(1)(f)) and sent via Resend. Prefer email?{" "}
                <a className="underline" href={`mailto:${CONTACT_EMAIL}`}>
                  {CONTACT_EMAIL}
                </a>
                .
              </p>
            </form>
          </CardContent>
        </Card>

        <div className="grid content-start gap-4">
          <Card>
            <CardContent className="grid gap-2 pt-6 text-sm">
              <p className="flex items-center gap-2 font-medium text-ink">
                <Mail className="size-4 text-brand" />
                Direct inbox
              </p>
              <a
                className="font-mono text-[13px] break-all underline"
                href={`mailto:${CONTACT_EMAIL}`}
              >
                {CONTACT_EMAIL}
              </a>
              <Button asChild variant="outline" size="sm" className="mt-1">
                <a href={`mailto:${CONTACT_EMAIL}`}>
                  Write an email
                  <ArrowUpRight />
                </a>
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="grid gap-2 pt-6 text-sm text-ink-soft">
              <p className="font-medium text-ink">Deletion requests</p>
              <p>
                Signed in? Delete everything instantly under API &amp; keys →
                Delete account. Locked out? Email from your account address and
                it is removed.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export function Attribution() {
  return (
    <div className="grid gap-6">
      <Hero lede="DELU forecasts stand on open public data. Everything measured below belongs to its publishers — only the P10 / P50 / P90 bands are ours. Please credit sources the same way when you reuse them."
      />

      <div className="grid gap-4">
        <Section n="01" icon={Database} title="ENTSO-E Transparency Platform">
          <p>
            Day-ahead prices and realised load come from the ENTSO-E
            Transparency Platform (
            <a
              className="underline"
              href="https://transparency.entsoe.eu"
              target="_blank"
              rel="noreferrer"
            >
              transparency.entsoe.eu
            </a>
            ), republished here under their{" "}
            <a
              className="underline"
              href="https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions"
              target="_blank"
              rel="noreferrer"
            >
              terms of use
            </a>
            : cite ENTSO-E as the source, reuse in good faith, and check their
            open-data list before each reuse — some series need the primary
            owner's prior agreement. Load actuals arrive with a delay of
            several hours, which is why the white actuals line on the chart
            ends before the forecast begins.
          </p>
        </Section>

        <Section n="02" icon={Database} title="SMARD · Bundesnetzagentur">
          <p>
            Realised wind, solar and total generation come from SMARD, the
            Bundesnetzagentur market data platform (
            <a
              className="underline"
              href="https://www.smard.de/en/datennutzung"
              target="_blank"
              rel="noreferrer"
            >
              smard.de
            </a>
            ), freely available under §111d EnWG and licensed{" "}
            <a
              className="underline"
              href="https://creativecommons.org/licenses/by/4.0/"
              target="_blank"
              rel="noreferrer"
            >
              CC BY 4.0
            </a>
            . Required credit:{" "}
            <span className="rounded bg-paper px-1.5 py-0.5 font-mono text-[13px] text-ink">
              Bundesnetzagentur | SMARD.de
            </span>{" "}
            — share and adapt freely with attribution, a licence link, and a
            note of any changes. The Bundesnetzagentur gives no warranty on
            correctness or completeness.
          </p>
        </Section>

        <Section n="03" icon={BadgeCheck} title="What is ours">
          <p>
            The P10 / P50 / P90 forecast bands are produced by the DELU pipeline
            (gradient-boosted model, two runs a day) and are original model
            output — the citation rules on the{" "}
            <span className="text-ink">Terms</span> page apply to them: state
            which run (05:30 or 11:30) a result is based on, and don't submit
            competing forecasts of the same targets to public leaderboards.
          </p>
        </Section>
      </div>
    </div>
  );
}

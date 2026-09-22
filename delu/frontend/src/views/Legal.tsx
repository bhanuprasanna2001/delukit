import {
  AlertCircle,
  ArrowUpRight,
  BadgeCheck,
  CheckCircle2,
  Database,
  KeyRound,
  Loader2,
  Lock,
  Mail,
  Quote,
  Scale,
  Send,
  ShieldCheck,
} from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { sendContact } from "../lib/api";
import { cn } from "../lib/utils";

export const CONTACT_EMAIL = "bhanu.prasanna2001@gmail.com";
const UPDATED = "September 2026";

function Hero({ lede }: { lede: string }) {
  return (
    <div className="grid gap-3">
      <p className="max-w-2xl text-base leading-relaxed text-ink-soft">{lede}</p>
      <p className="flex items-center gap-1.5 text-xs text-ink-faint">
        <BadgeCheck className="size-3.5" />
        Last updated {UPDATED}
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
      <Hero lede="DELU stores only what accounts and the forecast API need. No analytics, no trackers, no ads."
      />

      <div className="grid gap-4">
        <Section n="01" icon={Database} title="What we store, and why">
          <DataTable
            rows={[
              ["Email address", "Account identity, verification, replies", "Contract · Art. 6(1)(b)"],
              ["Password hash (PBKDF2, 200k rounds)", "Sign-in. The password itself is never stored", "Contract · Art. 6(1)(b)"],
              ["Email confirmed? + API key id", "One key per verified account", "Contract · Art. 6(1)(b)"],
              ["API call counters (per min / per day)", "Rate limits. Counts only, never call contents", "Legitimate interest · Art. 6(1)(f)"],
              ["Session cookie (7 days, HttpOnly)", "Keeps you signed in. No tracking data", "Strictly necessary"],
              ["Contact messages", "Replies, kept only while the thread is open", "Legitimate interest · Art. 6(1)(f)"],
            ]}
          />
          <p>
            Controller: DELU, run by Bhanu Prasanna,{" "}
            <a className="underline" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>
            . An email address is required: without one there is no account
            to verify or key to issue.
          </p>
        </Section>

        <Section n="02" icon={Send} title="Third parties">
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
            processing terms. No analytics, no trackers, no advertising, no
            sale of personal data.
          </p>
        </Section>

        <Section n="03" icon={Lock} title="How long we keep it">
          <ul className="grid gap-1.5">
            {[
              "Account, key and usage counters: until you delete the account. Deletion applies immediately.",
              "Sessions: expire after 7 days. Verification links: expire after 24 hours.",
              "Contact messages: kept while the conversation is open, deleted on request.",
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
            Access, rectification, erasure, restriction, portability, objection:
            write to{" "}
            <a className="underline" href={`mailto:${CONTACT_EMAIL}`}>
              {CONTACT_EMAIL}
            </a>{" "}
            from your account email. Requests are answered within one month.
            Self-serve deletion is under API &amp; keys → Delete account
            (password confirmation required). If you cannot sign in, email from
            your account address and the account is deleted.
          </p>
          <p className="text-[13px] text-ink-faint">
            You can also complain to your national data protection authority.
            This service does no automated decision-making or profiling.
          </p>
        </Section>
      </div>
    </div>
  );
}

export function Terms() {
  return (
    <div className="grid gap-6">
      <Hero lede="Use the forecasts for research and operations, cite the run you used, keep your key secret. The forecasts may not feed competing entries on public benchmarks."
      />

      <div className="grid gap-4">
        <Section n="01" icon={Database} title="The service">
          <p>
            DELU publishes day-ahead and 10-day point and probabilistic (P10 /
            P50 / P90) forecasts for the German–Luxembourgian bidding zone:
            load, solar, onshore and offshore wind, total generation, and the
            day-ahead price. Runs rebuild twice daily at 05:30 and 11:30
            Europe/Berlin. Each verified account gets one API key with 5,000
            calls a day; per-minute limits also apply. Calls made with your key
            count as yours. Rotate the key under API &amp; keys if it is
            exposed.
          </p>
        </Section>

        <Section n="02" icon={BadgeCheck} title="Citation and fair use">
          <p>
            The forecasts may be used as a benchmark or baseline, including in
            publications. Cite this work once the paper reference is published,
            and always state which run (05:30 or 11:30) a result is based on.
            One restriction: the forecasts may not be used to build competing
            forecasts of the same target quantities for public benchmarks or
            leaderboards.
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
            Circumventing rate limits, sharing keys, attacking the service, or
            unlawful use leads to blocked accounts. You can delete your account
            at any time. Liability is limited to the extent permitted by law.
            Material changes to these terms are noted here with a new date;
            continued use means acceptance.
          </p>
        </Section>
      </div>
    </div>
  );
}

const EMAIL_RE = /.+@.+\..+/;

const TOPICS = [
  { value: "Data correction", hint: "Wrong values, gaps, delays", icon: AlertCircle },
  { value: "Data question", hint: "Sources, methods, coverage", icon: Database },
  { value: "Benchmark citation", hint: "Using DELU in a publication", icon: Quote },
  { value: "Privacy / deletion request", hint: "Access, erasure, portability", icon: ShieldCheck },
  { value: "API problem", hint: "Keys, limits, downloads", icon: KeyRound },
  { value: "Something else", hint: "Anything not covered", icon: Mail },
] as const;

type Topic = (typeof TOPICS)[number]["value"];

interface FieldErrors {
  name?: string;
  email?: string;
  message?: string;
}

function nameError(v: string): string | undefined {
  return v.trim().length >= 2 ? undefined : "Tell us your name.";
}

function emailError(v: string): string | undefined {
  return EMAIL_RE.test(v.trim()) ? undefined : "Enter a valid email address.";
}

function messageError(v: string): string | undefined {
  if (v.trim().length < 10) return "Write a message of 10+ characters.";
  if (v.length > 4000) return "Keep it under 4000 characters.";
  return undefined;
}

function FieldError({ id, message }: { id: string; message: string | undefined }) {
  return message ? (
    <p id={id} className="flex items-center gap-1.5 text-[13px] text-red-700">
      <AlertCircle aria-hidden="true" className="size-3.5 shrink-0" />
      {message}
    </p>
  ) : null;
}

function StatusMessage({ status, detail }: { status: "ok" | "error"; detail: string }) {
  return status === "ok" ? (
    <p
      role="status"
      className="flex items-center gap-2 rounded-md bg-brand-tint px-3 py-2 text-sm text-brand-deep"
    >
      <CheckCircle2 aria-hidden="true" className="size-4 shrink-0" />
      {detail}
    </p>
  ) : (
    <p
      role="alert"
      className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      <AlertCircle aria-hidden="true" className="size-4 shrink-0" />
      {detail}
    </p>
  );
}

export function Contact() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [topic, setTopic] = useState<Topic>(TOPICS[0].value);
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [state, setState] = useState<
    { status: "idle" } | { status: "busy" } | { status: "ok"; detail: string } | { status: "error"; detail: string }
  >({ status: "idle" });
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const messageRef = useRef<HTMLTextAreaElement>(null);

  function onNameChange(v: string) {
    setName(v);
    if (errors.name) setErrors((e) => ({ ...e, name: nameError(v) }));
  }

  function onEmailChange(v: string) {
    setEmail(v);
    if (errors.email) setErrors((e) => ({ ...e, email: emailError(v) }));
  }

  function onMessageChange(v: string) {
    setMessage(v);
    if (errors.message) setErrors((e) => ({ ...e, message: messageError(v) }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const next: FieldErrors = {
      name: nameError(name),
      email: emailError(email),
      message: messageError(message),
    };
    setErrors(next);
    const refs = { name: nameRef, email: emailRef, message: messageRef } as const;
    const first = (["name", "email", "message"] as const).find((k) => next[k]);
    if (first) {
      refs[first].current?.focus();
      return;
    }
    setState({ status: "busy" });
    try {
      const res = await sendContact({
        name: name.trim(),
        email: email.trim(),
        topic,
        message: message.trim(),
      });
      setState({ status: "ok", detail: res.detail });
      setMessage("");
    } catch (err) {
      setState({
        status: "error",
        detail: err instanceof Error ? err.message : "Could not send.",
      });
    }
  }

  return (
    <div className="grid gap-6">
      <Hero lede="One inbox for corrections, data questions, citations, and privacy requests. Replies within 2 working days."
      />

      <div className="grid gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Send aria-hidden="true" className="size-4 text-brand" />
              Send a message
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} noValidate className="grid gap-5">
              <div className="grid gap-1.5">
                <Label htmlFor="ct-name">Name</Label>
                <Input
                  id="ct-name"
                  name="name"
                  autoComplete="name"
                  placeholder="Ada Lovelace…"
                  value={name}
                  onChange={(e) => onNameChange(e.target.value)}
                  onBlur={() => {
                    if (name !== "") setErrors((e) => ({ ...e, name: nameError(name) }));
                  }}
                  aria-invalid={errors.name ? true : undefined}
                  aria-describedby={errors.name ? "ct-name-error" : undefined}
                  ref={nameRef}
                  className="h-11 text-base sm:text-sm"
                />
                <FieldError id="ct-name-error" message={errors.name} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="ct-email">Email</Label>
                <Input
                  id="ct-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  spellCheck={false}
                  placeholder="you@example.com…"
                  value={email}
                  onChange={(e) => onEmailChange(e.target.value)}
                  onBlur={() => {
                    if (email !== "") setErrors((e) => ({ ...e, email: emailError(email) }));
                  }}
                  aria-invalid={errors.email ? true : undefined}
                  aria-describedby={errors.email ? "ct-email-error" : undefined}
                  ref={emailRef}
                  className="h-11 text-base sm:text-sm"
                />
                <FieldError id="ct-email-error" message={errors.email} />
              </div>
              <div className="grid gap-1.5">
                <span id="ct-topic-label" className="text-sm font-medium text-ink">
                  Topic
                </span>
                <div
                  role="radiogroup"
                  aria-labelledby="ct-topic-label"
                  className="grid gap-2 sm:grid-cols-2"
                >
                  {TOPICS.map((t) => {
                    const selected = t.value === topic;
                    return (
                      <label
                        key={t.value}
                        className={cn(
                          "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors touch-manipulation focus-within:ring-2 focus-within:ring-brand focus-within:ring-offset-1",
                          selected
                            ? "border-brand bg-brand-tint/50"
                            : "border-line bg-card hover:border-ink-faint",
                        )}
                      >
                        <input
                          type="radio"
                          name="topic"
                          value={t.value}
                          checked={selected}
                          onChange={() => setTopic(t.value)}
                          className="sr-only"
                        />
                        <t.icon
                          aria-hidden="true"
                          className={cn(
                            "mt-0.5 size-4 shrink-0",
                            selected ? "text-brand-deep" : "text-ink-faint",
                          )}
                        />
                        <span className="grid gap-0.5">
                          <span className="text-sm font-medium text-ink">{t.value}</span>
                          <span className="text-xs text-ink-faint">{t.hint}</span>
                        </span>
                        {selected ? (
                          <CheckCircle2
                            aria-hidden="true"
                            className="ml-auto size-4 shrink-0 text-brand"
                          />
                        ) : null}
                      </label>
                    );
                  })}
                </div>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="ct-message">Message</Label>
                <textarea
                  id="ct-message"
                  name="message"
                  rows={5}
                  maxLength={4000}
                  placeholder="What did you see, and what did you expect?…"
                  value={message}
                  onChange={(e) => onMessageChange(e.target.value)}
                  onBlur={() => {
                    if (message !== "")
                      setErrors((e) => ({ ...e, message: messageError(message) }));
                  }}
                  aria-invalid={errors.message ? true : undefined}
                  aria-describedby={errors.message ? "ct-message-error" : undefined}
                  ref={messageRef}
                  className="min-h-28 w-full rounded-md border border-line bg-card px-3 py-2.5 text-base placeholder:text-ink-faint focus:border-brand sm:text-sm"
                />
                <div className="flex items-start justify-between gap-2">
                  <FieldError id="ct-message-error" message={errors.message} />
                  <p className="ml-auto text-xs text-ink-faint tnum">
                    {message.length}/4000
                  </p>
                </div>
              </div>
              {state.status === "ok" || state.status === "error" ? (
                <StatusMessage status={state.status} detail={state.detail} />
              ) : null}
              <div className="grid gap-3">
                <div>
                  <Button
                    type="submit"
                    disabled={state.status === "busy"}
                    className="h-11 w-full touch-manipulation px-6 sm:w-auto"
                  >
                    {state.status === "busy" ? (
                      <Loader2 aria-hidden="true" className="animate-spin" />
                    ) : (
                      <Send aria-hidden="true" />
                    )}
                    {state.status === "busy" ? "Sending…" : "Send message"}
                  </Button>
                </div>
                <p className="text-xs leading-relaxed text-ink-faint">
                  Used only to reply (GDPR Art. 6(1)(f)), sent via Resend.
                </p>
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardContent className="grid gap-2 pt-6 text-sm">
              <p className="flex items-center gap-2 font-medium text-ink">
                <Mail aria-hidden="true" className="size-4 text-brand" />
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
                  <ArrowUpRight aria-hidden="true" />
                </a>
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="grid gap-2 pt-6 text-sm text-ink-soft">
              <p className="font-medium text-ink">Deletion requests</p>
              <p>
                Signed in? Delete everything under API &amp; keys → Delete
                account. Locked out? Email from your account address and it is
                removed.
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
      <Hero lede="Measured data below belongs to its publishers and is reused under their licences. Only the P10 / P50 / P90 bands are DELU model output."
      />

      <div className="grid gap-4">
        <Section n="01" icon={Database} title="ENTSO-E Transparency Platform">
          <p>
            Realised load, the day-ahead load forecast, SDAC and EXAA auction
            prices, and realised and forecast generation come from the ENTSO-E
            Transparency Platform (
            <a
              className="underline"
              href="https://transparency.entsoe.eu"
              target="_blank"
              rel="noreferrer"
            >
              transparency.entsoe.eu
            </a>
            ), republished under their{" "}
            <a
              className="underline"
              href="https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions"
              target="_blank"
              rel="noreferrer"
            >
              terms of use
            </a>
            . Cite ENTSO-E as the source and check their open-data list before
            each reuse: some series need the primary data owner's prior
            agreement. Load actuals arrive with a delay of several hours, which
            is why the actuals line on the chart ends before the forecast
            begins.
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
            ), published under §111d EnWG and licensed{" "}
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
            </span>
            , with a licence link and a note of any changes. No warranty on
            correctness or completeness.
          </p>
        </Section>

        <Section n="03" icon={Database} title="Energy-Charts · Fraunhofer ISE">
          <p>
            Day-ahead auction prices for the DE-LU bidding zone come from the
            Energy-Charts API (
            <a
              className="underline"
              href="https://www.energy-charts.info"
              target="_blank"
              rel="noreferrer"
            >
              energy-charts.info
            </a>
            ), operated by Fraunhofer ISE and largely licensed{" "}
            <a
              className="underline"
              href="https://creativecommons.org/licenses/by/4.0/"
              target="_blank"
              rel="noreferrer"
            >
              CC BY 4.0
            </a>
            . Credit: Fraunhofer ISE, energy-charts.info.
          </p>
        </Section>

        <Section n="04" icon={Database} title="Open-Meteo · ECMWF IFS">
          <p>
            Weather inputs (2 m temperature, 100 m wind speed and direction,
            shortwave radiation, cloud cover over the DE-LU zone and the North
            and Baltic Seas) come from the Open-Meteo API (
            <a
              className="underline"
              href="https://open-meteo.com"
              target="_blank"
              rel="noreferrer"
            >
              open-meteo.com
            </a>
            ), ECMWF IFS 00:00 UTC runs, licensed{" "}
            <a
              className="underline"
              href="https://open-meteo.com/en/licence"
              target="_blank"
              rel="noreferrer"
            >
              CC BY 4.0
            </a>
            . These are model inputs, not displayed values. Free-tier use is
            non-commercial.
          </p>
        </Section>

        <Section n="05" icon={BadgeCheck} title="What is ours">
          <p>
            The P10 / P50 / P90 forecast bands are produced by the DELU pipeline
            (gradient-boosted model, two runs a day) and are original model
            output. The citation rules on the{" "}
            <span className="text-ink">Terms</span> page apply: state which run
            (05:30 or 11:30) a result is based on.
          </p>
        </Section>
      </div>
    </div>
  );
}

import { Mail } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";

// Set the inbox that receives contact, deletion and data requests.
export const CONTACT_EMAIL = "hello@delu.energy";

function Prose({ children }: { children: React.ReactNode }) {
  return <div className="grid gap-4 text-sm leading-relaxed text-ink-soft">{children}</div>;
}

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="font-display text-lg font-semibold text-ink">{children}</h2>;
}

export function Privacy() {
  return (
    <Prose>
      <section className="grid gap-2">
        <H>What we store</H>
        <p>
          An account holds your email address, a salted password hash (PBKDF2,
          never the password itself), whether the email is confirmed, and your
          single API key identifier. To enforce rate limits we count API calls
          per key per minute and per day — nothing about the call contents.
        </p>
      </section>
      <section className="grid gap-2">
        <H>Cookies</H>
        <p>
          One cookie keeps you signed in. It is HttpOnly, lasts 7 days, and
          carries no tracking data. There are no analytics scripts, no
          third-party trackers, and no advertising on this site.
        </p>
      </section>
      <section className="grid gap-2">
        <H>Deletion</H>
        <p>
          Write to <a className="text-brand underline" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>{" "}
          from your account email and the account, key and usage counters are
          removed.
        </p>
      </section>
    </Prose>
  );
}

export function Terms() {
  return (
    <Prose>
      <section className="grid gap-2">
        <H>The service</H>
        <p>
          DELU publishes day-ahead and 10-day forecasts for the DE-LU bidding
          zone, twice daily, for research and operational use. Each account gets
          one API key with 5,000 calls a day. Keep the key secret — calls made
          with it count as yours.
        </p>
      </section>
      <section className="grid gap-2">
        <H>Citation and fair use</H>
        <p>
          You may use the forecasts as a benchmark or baseline, including in
          publications; please cite this work once the paper reference is
          published, and always state which run (05:30 or 11:30) a result is
          based on. The one restriction: the forecasts may not be used to build
          competing forecasts of the same target quantities submitted to public
          benchmarks or leaderboards.
        </p>
      </section>
      <section className="grid gap-2">
        <H>No warranty</H>
        <p>
          Forecasts are model output, not financial advice. No warranty on
          completeness, accuracy or availability; the service may change or stop
          at any time. Accounts that abuse the API — scraping around rate
          limits, sharing keys, attacking the service — are blocked.
        </p>
      </section>
    </Prose>
  );
}

export function Contact() {
  return (
    <div className="grid gap-4">
      <p className="text-sm leading-relaxed text-ink-soft">
        Corrections, data questions, benchmark citations, deletion requests —
        anything about DELU lands in one inbox and is read by the person who
        runs the pipeline.
      </p>
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 pt-6">
          <Mail className="size-4 text-brand" />
          <a className="font-mono text-sm underline" href={`mailto:${CONTACT_EMAIL}`}>
            {CONTACT_EMAIL}
          </a>
          <span className="ml-auto">
            <Button asChild>
              <a href={`mailto:${CONTACT_EMAIL}`}>Write an email</a>
            </Button>
          </span>
        </CardContent>
      </Card>
    </div>
  );
}

export function Attribution() {
  return (
    <Prose>
      <section className="grid gap-2">
        <H>ENTSO-E Transparency Platform</H>
        <p>
          Day-ahead prices and realised load come from the ENTSO-E Transparency
          Platform (<a className="text-brand underline" href="https://transparency.entsoe.eu" target="_blank" rel="noreferrer">transparency.entsoe.eu</a>),
          republished here under their terms of use. Load actuals arrive with a
          delay of several hours — that is why the white actuals line on the
          chart ends before the forecast begins.
        </p>
      </section>
      <section className="grid gap-2">
        <H>SMARD</H>
        <p>
          Realised wind, solar and total generation come from SMARD, the
          Bundesnetzagentur market data platform (<a className="text-brand underline" href="https://www.smard.de" target="_blank" rel="noreferrer">smard.de</a>).
        </p>
      </section>
      <section className="grid gap-2">
        <H>What is ours</H>
        <p>
          The P10/P50/P90 forecast bands are produced by the DELU pipeline and
          are original model output — the citation rules on the{" "}
          <span className="text-ink">Terms</span> page apply to them.
        </p>
      </section>
    </Prose>
  );
}

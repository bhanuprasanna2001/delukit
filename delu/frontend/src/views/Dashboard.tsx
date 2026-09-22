import { KeyRound } from "lucide-react";
import { useState } from "react";
import SwaggerUI from "swagger-ui-react";
import "swagger-ui-react/swagger-ui.css";
import { KeyReveal } from "../components/KeyReveal";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { berlinLong, refreshKey, resend, type Me } from "../lib/api";

export function Dashboard({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [freshKey, setFreshKey] = useState<string | null>(null);
  const [arming, setArming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [resent, setResent] = useState("");

  async function refresh() {
    if (!arming) {
      setArming(true);
      return;
    }
    setPending(true);
    setError("");
    try {
      const res = await refreshKey();
      setFreshKey(res.api_key);
      setArming(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed.");
    } finally {
      setPending(false);
    }
  }

  async function sendAgain() {
    try {
      const res = await resend();
      setResent(res.detail);
    } catch (err) {
      setResent(err instanceof Error ? err.message : "Could not resend.");
    }
  }

  if (!me.verified) {
    return (
      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Confirm your email</CardTitle>
          <CardDescription>
            Your API key unlocks once the email is confirmed.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <p className="text-sm text-ink-soft">
            {resent || "Check your inbox for the confirmation link."}
          </p>
          <div>
            <Button variant="outline" onClick={sendAgain}>
              Send it again
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const pct = me.key
    ? Math.min(100, Math.round((me.key.used_today / me.key.daily_limit) * 100))
    : 0;

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>API key</CardTitle>
            {me.key ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-tint px-2.5 py-0.5 text-xs font-medium text-brand-deep">
                <span className="relative flex size-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-60" />
                  <span className="relative inline-flex size-1.5 rounded-full bg-brand" />
                </span>
                active
              </span>
            ) : null}
          </div>
          <CardDescription>
            One active key. Refreshing replaces it — the old one stops working
            immediately.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          {me.key ? (
            <div className="grid gap-2">
              <div className="flex items-center gap-2.5 rounded-lg border border-line bg-paper px-3.5 py-3">
                <KeyRound className="size-4 shrink-0 text-ink-faint" />
                <code className="font-mono text-sm tnum">{me.key.prefix}…</code>
              </div>
              <p className="text-xs text-ink-faint">
                Created {berlinLong(me.key.created)}
                {me.key.last_used
                  ? ` · Last used ${berlinLong(me.key.last_used)}`
                  : " · Not used yet"}
              </p>
              <div>
                <div className="flex items-end justify-between gap-3">
                  <p className="tnum">
                    <span className="font-display text-4xl font-bold tracking-tight">
                      {me.key.used_today.toLocaleString()}
                    </span>{" "}
                    <span className="text-sm text-ink-soft">
                      / {me.key.daily_limit.toLocaleString()} calls
                    </span>
                  </p>
                  <p className="pb-1.5 text-xs text-ink-faint">
                    Today · resets 00:00 UTC
                  </p>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-paper">
                  <div
                    className="h-full rounded-full bg-brand transition-[width]"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-ink-soft">No key yet. Refresh to create one.</p>
          )}
          {error ? <p className="text-sm text-red-700">{error}</p> : null}
          {freshKey ? (
            <div className="grid gap-2">
              <p className="text-sm font-medium">
                New key — shown once, then never again:
              </p>
              <KeyReveal value={freshKey} />
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              onClick={refresh}
              disabled={pending}
              className={
                arming ? "border-red-300 text-red-700 hover:bg-red-50" : undefined
              }
            >
              {pending
                ? "Refreshing…"
                : arming
                  ? "Click again to replace the key"
                  : me.key
                    ? "Refresh key"
                    : "Create key"}
            </Button>
            {arming ? (
              <button
                type="button"
                className="cursor-pointer text-sm text-ink-soft underline"
                onClick={() => setArming(false)}
              >
                Keep the current one
              </button>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Forecast API</CardTitle>
          <CardDescription>
            Just the forecast endpoint. Authorize with your key and try it
            right here.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-lg border border-line">
            <SwaggerUI
              url="/openapi-forecast.json"
              docExpansion="list"
              tryItOutEnabled
              persistAuthorization
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

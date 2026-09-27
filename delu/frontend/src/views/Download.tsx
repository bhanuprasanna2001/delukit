import type { View } from "../App";
import { Card, CardContent } from "../components/ui/card";
import type { Me } from "../lib/api";
import { AccountAccess } from "./Auth";
import { ExportForm } from "./ExportForm";

export function Download({
  me,
  onSignedIn,
  go,
}: {
  me: Me | null | undefined;
  onSignedIn: () => void;
  go: (v: View) => void;
}) {
  if (me === undefined) {
    return <div className="h-40 animate-pulse rounded-lg bg-line" aria-label="Loading account" />;
  }

  if (!me) {
    return (
      <div className="grid gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">Download Forecasts</h1>
          <p className="mt-1 text-sm text-ink-soft">
            Sign in to export forecasts. Your account also gives you an API key.
          </p>
        </div>
        <div className="pt-4">
          <AccountAccess
            description="Use your account to download forecasts."
            onSignedIn={onSignedIn}
            onCreateAccount={() => go("signup")}
          />
        </div>
      </div>
    );
  }

  if (!me.verified) {
    return (
      <div className="grid gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight">Download Forecasts</h1>
        </div>
        <Card className="max-w-xl">
          <CardContent className="pt-6">
            <p className="text-sm text-ink-soft">
              Confirm your email to unlock downloads. Check your inbox for the confirmation link.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <ExportForm go={go} />;
}

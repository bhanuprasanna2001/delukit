import { useState } from "react";
import { deleteAccount } from "../lib/api";
import { Button } from "./ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

export function DeleteAccountCard({ onDeleted }: { onDeleted: () => void }) {
  const [arming, setArming] = useState(false);
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setPending(true);
    setError("");
    try {
      await deleteAccount(password);
      onDeleted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deletion failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Delete account</CardTitle>
        <CardDescription>
          Removes the account, API key, sessions and usage counters immediately. This cannot be
          undone.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {arming ? (
          <>
            <div className="grid gap-1.5">
              <Label htmlFor="delete-password">Confirm with your password</Label>
              <Input
                id="delete-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error ? <p className="text-sm text-red-700">{error}</p> : null}
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="outline"
                onClick={confirm}
                disabled={pending || !password}
                className="border-red-300 text-red-700 hover:bg-red-50"
              >
                {pending ? "Deleting…" : "Delete everything"}
              </Button>
              <button
                type="button"
                className="cursor-pointer text-sm text-ink-soft underline"
                onClick={() => {
                  setArming(false);
                  setPassword("");
                  setError("");
                }}
              >
                Keep my account
              </button>
            </div>
          </>
        ) : (
          <div>
            <Button
              variant="outline"
              onClick={() => setArming(true)}
              className="border-red-300 text-red-700 hover:bg-red-50"
            >
              Delete account
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

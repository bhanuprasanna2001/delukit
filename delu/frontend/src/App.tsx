import { Download as DownloadIcon, Info, KeyRound, LineChart, LogOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { KeyReveal } from "./components/KeyReveal";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { TooltipProvider } from "./components/ui/tooltip";
import { getMe, logout, verifyEmail, type Me } from "./lib/api";
import { cn } from "./lib/utils";
import { About } from "./views/About";
import { LoginForm, SignupForm } from "./views/Auth";
import { Dashboard } from "./views/Dashboard";
import { Download } from "./views/Download";
import { Forecasts } from "./views/Forecasts";
import { Attribution, Contact, Privacy, Terms } from "./views/Legal";

export type View =
  | "forecasts"
  | "login"
  | "signup"
  | "dashboard"
  | "verify"
  | "download"
  | "about"
  | "privacy"
  | "terms"
  | "contact"
  | "attribution";

const verifyTokenFromUrl = new URLSearchParams(window.location.search).get("verify") ?? "";

function VerifyPanel({ token, onDone }: { token: string; onDone: () => void }) {
  const attempted = useRef<string | null>(null);
  const [state, setState] = useState<
    | { status: "pending" }
    | { status: "ok"; detail: string; apiKey?: string }
    | { status: "error"; detail: string }
  >({ status: "pending" });

  useEffect(() => {
    if (attempted.current === token) return;
    attempted.current = token;
    verifyEmail(token)
      .then((res) => {
        setState({ status: "ok", detail: res.detail, apiKey: res.api_key });
        onDone();
      })
      .catch((err: Error) => setState({ status: "error", detail: err.message }));
  }, [token, onDone]);

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Email confirmation</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {state.status === "pending" ? <p className="text-sm">Confirming…</p> : null}
        {state.status === "error" ? (
          <p className="text-sm text-red-700">{state.detail}</p>
        ) : null}
        {state.status === "ok" ? (
          <div className="grid gap-3">
            <p className="text-sm">{state.detail}</p>
            {state.apiKey ? <KeyReveal value={state.apiKey} /> : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function App() {
  const [view, setView] = useState<View>(verifyTokenFromUrl ? "verify" : "forecasts");
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [signedUp, setSignedUp] = useState("");

  async function refreshMe() {
    try {
      setMe(await getMe());
    } catch {
      setMe(null);
    }
  }

  useEffect(() => {
    window.history.replaceState({}, "", window.location.pathname);
    let active = true;
    getMe()
      .then((account) => {
        if (active) setMe(account);
      })
      .catch(() => {
        if (active) setMe(null);
      });
    return () => {
      active = false;
    };
  }, []);

  async function signOut() {
    await logout().catch(() => undefined);
    setMe(null);
    setView("forecasts");
  }

  function accountDeleted() {
    setMe(null);
    setView("forecasts");
  }

  function center(content: React.ReactNode) {
    return <div className="flex justify-center pt-10">{content}</div>;
  }

  return (
    <TooltipProvider>
      <div
        className={
          view === "forecasts"
            ? "flex min-h-screen flex-col lg:h-dvh lg:overflow-hidden"
            : "flex min-h-screen flex-col"
        }
      >
        <header className="sticky top-0 z-40 h-14 flex-none border-b border-line bg-card/90 backdrop-blur">
          <div className="mx-auto flex h-14 w-full max-w-[1800px] items-center gap-2 px-4 sm:px-6">
            <button
              type="button"
              onClick={() => setView("forecasts")}
              className="flex cursor-pointer items-center gap-2"
            >
              <img src="/delu.svg" alt="DELU logo" className="size-8 rounded-md" />
              <span className="font-display text-lg font-bold tracking-tight">
                DELU
              </span>
            </button>
            <nav className="ml-6 flex items-center gap-1">
              <Button
                variant={view === "forecasts" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setView("forecasts")}
              >
                <LineChart />
                Forecasts
              </Button>
              <Button
                variant={view === "download" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setView("download")}
              >
                <DownloadIcon />
                Download
              </Button>
              <Button
                variant={view === "dashboard" || view === "verify" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setView(me ? "dashboard" : "login")}
              >
                <KeyRound />
                API &amp; keys
              </Button>
              <Button
                variant={view === "about" ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setView("about")}
              >
                <Info />
                About
              </Button>
            </nav>
            <div className="ml-auto flex items-center gap-2">
              {me === undefined ? null : me ? (
                <div className="flex items-center gap-2">
                  <span className="hidden text-sm text-ink-soft sm:inline">{me.email}</span>
                  <Button variant="outline" size="sm" onClick={signOut}>
                    <LogOut />
                    Sign out
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="sm" onClick={() => setView("login")}>
                    Sign in
                  </Button>
                  <Button size="sm" onClick={() => setView("signup")}>
                    Sign up
                  </Button>
                </div>
              )}
            </div>
          </div>
        </header>

        {view === "forecasts" ? (
          <main className="flex min-h-0 flex-1 flex-col">
            <Forecasts />
          </main>
        ) : (
          <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">
            {view === "login"
            ? center(
                <div className="grid w-full max-w-md gap-3">
                  <LoginForm
                    onDone={() => {
                      refreshMe();
                      setView("dashboard");
                    }}
                  />
                  <p className="text-center text-sm text-ink-soft">
                    New here?{" "}
                    <button
                      type="button"
                      className="cursor-pointer underline"
                      onClick={() => setView("signup")}
                    >
                      Create an account
                    </button>
                  </p>
                </div>,
              )
            : null}

          {view === "signup"
            ? center(
                signedUp ? (
                  <Card className="w-full max-w-md">
                    <CardHeader>
                      <CardTitle>Check your inbox</CardTitle>
                    </CardHeader>
                    <CardContent className="grid gap-3">
                      <p className="text-sm text-ink-soft">{signedUp}</p>
                      <p className="text-sm text-ink-soft">
                        Opening the link confirms the email and hands you the API key.
                      </p>
                    </CardContent>
                  </Card>
                ) : (
                  <div className="grid w-full max-w-md gap-3">
                    <SignupForm onDone={(detail) => setSignedUp(detail)} />
                    <p className="text-center text-sm text-ink-soft">
                      Already have an account?{" "}
                      <button
                        type="button"
                        className="cursor-pointer underline"
                        onClick={() => setView("login")}
                      >
                        Sign in
                      </button>
                    </p>
                  </div>
                ),
              )
            : null}

          {view === "verify"
            ? center(
                <VerifyPanel token={verifyTokenFromUrl} onDone={refreshMe} />,
              )
            : null}

          {view === "dashboard" ? (
            <div className="grid gap-4">
              <div>
                <h1 className="font-display text-2xl font-bold tracking-tight">
                  API & keys
                </h1>
                <p className="mt-1 text-sm text-ink-soft">
                  One key, full forecast access, 5,000 calls a day.
                </p>
              </div>
              {me === undefined ? (
                <div className="h-40 animate-pulse rounded-lg bg-line" />
              ) : me ? (
                <Dashboard
                  me={me}
                  onChanged={refreshMe}
                  onDeleted={accountDeleted}
                />
              ) : (
                <div className="grid gap-3">
                  <p className="text-sm text-ink-soft">Sign in to manage the API key.</p>
                  <div>
                    <Button onClick={() => setView("login")}>Sign in</Button>
                  </div>
                </div>
              )}
            </div>
          ) : null}
            {view === "download" ? (
              <Download me={me ?? null} onSignIn={() => setView("login")} go={setView} />
            ) : null}

            {view === "about" ? (
              <div className="grid gap-4">
                <div>
                  <h1 className="font-display text-2xl font-bold tracking-tight">
                    About DELU
                  </h1>
                </div>
                <About go={setView} />
              </div>
            ) : null}

            {(
              [
                ["privacy", "Privacy"],
                ["terms", "Terms of use"],
                ["contact", "Contact"],
                ["attribution", "Data attribution"],
              ] as const
            ).map(([v, label]) =>
              view === v ? (
                <div className="grid gap-4" key={v}>
                  <div>
                    <h1 className="font-display text-2xl font-bold tracking-tight">
                      {label}
                    </h1>
                  </div>
                  {v === "privacy" ? <Privacy /> : null}
                  {v === "terms" ? <Terms /> : null}
                  {v === "contact" ? <Contact /> : null}
                  {v === "attribution" ? <Attribution /> : null}
                </div>
              ) : null,
            )}
          </main>
        )}

        <footer className="h-12 flex-none border-t border-line">
          <div
            className={cn(
              "mx-auto flex h-full max-w-[1800px] flex-wrap items-center gap-x-5 gap-y-1 px-4 text-xs text-ink-faint sm:px-6",
            )}
          >
            <span className="flex items-center gap-1.5 font-medium text-ink-soft">
              <img src="/delu.svg" alt="DELU logo" className="size-5 rounded" />
              DELU
              <span className="font-normal text-ink-faint">
                © {new Date().getFullYear()}
              </span>
            </span>
            <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-1">
              {(
                [
                  ["attribution", "Data attribution"],
                  ["privacy", "Privacy"],
                  ["terms", "Terms"],
                  ["contact", "Contact"],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setView(v)}
                  className="cursor-pointer hover:text-ink-soft"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </footer>
      </div>
    </TooltipProvider>
  );
}

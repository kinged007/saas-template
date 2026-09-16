import { useState } from "react";
import { useLogin } from "@refinedev/core";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_URL, httpClient } from "@/providers/dataProvider";
import { identityStore, tokenStore, workspaceStore } from "@/utils/storage";
import { clearAllCaches, queryClient } from "@/providers/queryClient";

export function LoginPage() {
  const { mutate: login, isPending } = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const storeTokens = (tokens: { access_token: string; refresh_token: string }) => {
    workspaceStore.clear();
    identityStore.set(null);
    clearAllCaches(queryClient);
    tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (challenge) {
      httpClient
        .post(`${API_URL}/auth/2fa/login`, { challenge_token: challenge, code })
        .then(({ data }) => {
          storeTokens(data);
          window.location.assign("/");
        })
        .catch(() => {
          setChallenge(null);
          setCode("");
          setError("Verification failed. Sign in again.");
        });
      return;
    }
    login(
      { email, password },
      {
        onError: (err) => {
          // 2FA challenge arrives as "2fa_required:<token>" (see authProvider).
          const msg = (err as Error)?.message ?? "";
          const prefix = "2fa_required:";
          if (msg.startsWith(prefix)) {
            setChallenge(msg.slice(prefix.length));
            setError(null);
          } else {
            setError(msg || "Login failed");
          }
        },
      },
    );
  };

  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <img src="/logo.svg" alt="SaaS Template" className="mx-auto mb-2 w-48" />
          <CardDescription>Sign in to your account</CardDescription>
        </CardHeader>
        <CardContent>
import { useState } from "react";
import { useLogin } from "@refinedev/core";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_URL, httpClient } from "@/providers/dataProvider";
import { identityStore, tokenStore, workspaceStore } from "@/utils/storage";
import { clearAllCaches, queryClient } from "@/providers/queryClient";

export function LoginPage() {
  const { mutate: login, isPending } = useLogin();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const storeTokens = (tokens: { access_token: string; refresh_token: string }) => {
    workspaceStore.clear();
    identityStore.set(null);
    clearAllCaches(queryClient);
    tokenStore.setTokens(tokens.access_token, tokens.refresh_token);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (challenge) {
      httpClient
        .post(`${API_URL}/auth/2fa/login`, { challenge_token: challenge, code })
        .then(({ data }) => {
          storeTokens(data);
          window.location.assign("/");
        })
        .catch((err) => setError(err?.response?.data?.detail ?? err?.message ?? "Login failed"));
      return;
    }
    login(
      { email, password },
      {
        onError: (err) => {
          // 2FA challenge arrives as "2fa_required:<token>" (see authProvider).
          const msg = (err as Error)?.message ?? "";
          const prefix = "2fa_required:";
          if (msg.startsWith(prefix)) {
            setChallenge(msg.slice(prefix.length));
            setError(null);
          } else {
            setError(msg || "Login failed");
          }
        },
      },
    );
  };

  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <img src="/logo.svg" alt="SaaS Template" className="mx-auto mb-2 w-48" />
          <CardDescription>Sign in to your account</CardDescription>
        </CardHeader>
        <CardContent>
          {challenge ? (
            <form onSubmit={submit} className="flex flex-col gap-4">
              <p className="text-muted-foreground text-sm">
                Enter the 6-digit code from your authenticator app (or a backup code).
              </p>
              <div className="flex flex-col gap-2">
                <Label htmlFor="code">Two-factor code</Label>
                <Input
                  id="code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  required
                />
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              <Button type="submit" disabled={isPending || !code}>
                Verify
              </Button>
              <Button type="button" variant="ghost" onClick={() => { setChallenge(null); setCode(""); }}>
                Back
              </Button>
            </form>
          ) : (
            <form onSubmit={submit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              <Button type="submit" disabled={isPending}>
                {isPending ? "Signing in…" : "Sign in"}
              </Button>
              <p className="text-muted-foreground text-center text-sm">
                <Link to="/forgot-password" className="text-primary underline underline-offset-4">
                  Forgot password?
                </Link>
              </p>
            </form>
          )}
        </CardContent>
        <CardFooter className="justify-center">
          <p className="text-muted-foreground text-sm">
            No account?{" "}
            <Link to="/register" className="text-primary underline underline-offset-4">
              Register
            </Link>
          </p>
        </CardFooter>
      </Card>
    </div>
  );
}
        </CardContent>
        <CardFooter className="justify-center">
          <p className="text-muted-foreground text-sm">
            No account?{" "}
            <Link to="/register" className="text-primary underline underline-offset-4">
              Register
            </Link>
          </p>
        </CardFooter>
      </Card>
    </div>
  );
}

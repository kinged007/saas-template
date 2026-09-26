import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SsoButtons, fetchAuthConfig, type AuthConfig } from "@/components/AuthConfig";
import { APP_NAME } from "@/config";
import { authProvider, seedWorkspace } from "@/providers/authProvider";
import { API_URL, httpClient } from "@/providers/dataProvider";
import { identityStore, tokenStore, workspaceStore } from "@/utils/storage";
import { clearAllCaches, queryClient } from "@/providers/queryClient";

export function LoginPage() {
  const [pending, setPending] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [passwordChanged, setPasswordChanged] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchAuthConfig().then(setConfig);
    const params = new URLSearchParams(window.location.search);
    const challengeParam = params.get("challenge");
    if (challengeParam) setChallenge(challengeParam);
    const err = params.get("error");
    if (err) setError(err === "registration is disabled" ? "Registration is disabled." : "Sign-in failed.");
    // Set by the change-password redirect: that flow revokes every session,
    // so the user lands here instead of staying on the settings page.
    if (params.get("password_changed") === "1") setPasswordChanged(true);
  }, []);

  useEffect(() => {
    if (challenge) codeRef.current?.focus();
  }, [challenge]);

  // Same token + identity + workspace seeding as a normal login (see
  // authProvider): without this the identity query settles with no
  // workspace selected and the app mounts behind a blank gate.
  // Access token only — the refresh token lives in the HttpOnly cookie.
  const storeTokens = async (tokens: { access_token: string }) => {
    workspaceStore.clear();
    identityStore.set(null);
    clearAllCaches(queryClient);
    tokenStore.setTokens(tokens.access_token);
    try {
      const { data: identity } = await httpClient.get(`${API_URL}/auth/me`);
      await seedWorkspace(identity);
    } catch {
      identityStore.set(null);
    }
  };

  // Call authProvider directly instead of useLogin: refine's useLogin shows
  // an error toast for every success:false result, which would leak the
  // challenge token and never reach a per-call onError branch.
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (challenge) {
      setPending(true);
      try {
        const { data } = await httpClient.post(`${API_URL}/auth/2fa/login`, {
          challenge_token: challenge,
          code,
          use_cookies: true,
        });
        await storeTokens(data);
        window.location.assign("/");
      } catch {
        setChallenge(null);
        setCode("");
        setError("Verification failed. Sign in again.");
      } finally {
        setPending(false);
      }
      return;
    }
    setPending(true);
    try {
      const res = await authProvider.login({ email, password });
      if (res.success) {
        window.location.assign(res.redirectTo ?? "/");
        return;
      }
      // 2FA challenge arrives as "2fa_required:<token>" (see authProvider).
      const msg = (res.error as Error)?.message ?? "";
      const prefix = "2fa_required:";
      if (msg.startsWith(prefix)) {
        setChallenge(msg.slice(prefix.length));
        setError(null);
      } else {
        setError(msg || "Login failed");
      }
    } finally {
      setPending(false);
    }
  };

  const passwordEnabled = config?.password_enabled ?? true;
  const ssoProviders = config?.providers ?? [];
  const registrationEnabled = config?.registration_enabled ?? true;

  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <img src="/logo.svg" alt={APP_NAME} className="mx-auto mb-2 w-48" />
          <CardDescription>Sign in to your account</CardDescription>
          {passwordChanged && (
            <Badge variant="success" className="mt-2 w-fit self-center bg-green-800 hover:bg-green-900">
              Password changed — sign in with your new password
            </Badge>
          )}
        </CardHeader>
        <CardContent>
          {ssoProviders.length > 0 && !challenge && (
            <div className="mb-4">
              <SsoButtons providers={ssoProviders} disabled={pending} />
            </div>
          )}
          {(!passwordEnabled && ssoProviders.length > 0 && !challenge) ? null : (
          <>
          {challenge ? (
            <form onSubmit={submit} className="flex flex-col gap-4">
              <p className="text-muted-foreground text-sm">
                Enter the 6-digit code from your authenticator app (or a backup code).
              </p>
              <div className="flex flex-col gap-2">
                <Label htmlFor="code">Two-factor code</Label>
                <Input
                  id="code"
                  ref={codeRef}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  required
                />
              </div>
              {error && <p className="text-destructive text-sm">{error}</p>}
              <Button type="submit" disabled={pending || !code}>
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
                  autoFocus
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
              <Button type="submit" disabled={pending}>
                {pending ? "Signing in…" : "Sign in"}
              </Button>
              <p className="text-muted-foreground text-center text-sm">
                <Link to="/forgot-password" className="text-primary underline underline-offset-4">
                  Forgot password?
                </Link>
              </p>
            </form>
          )}
          </>
          )}
        </CardContent>
        {registrationEnabled && (
        <CardFooter className="justify-center">
          <p className="text-muted-foreground text-sm">
            No account?{" "}
            <Link to="/register" className="text-primary underline underline-offset-4">
              Register
            </Link>
          </p>
        </CardFooter>
        )}
      </Card>
    </div>
  );
}

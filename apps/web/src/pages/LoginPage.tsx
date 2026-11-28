import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { SsoButtons, fetchAuthConfig, type AuthConfig } from "@/components/AuthConfig";
import { afterAuthRedirect, authProvider, seedWorkspace } from "@/providers/authProvider";
import { API_URL, httpClient } from "@/providers/dataProvider";
import { identityStore, tokenStore } from "@/utils/storage";
import { postCredentials } from "@/utils/credentialPost";
import { clearAllCaches, queryClient } from "@/providers/queryClient";

export function LoginPage() {
  const [pending, setPending] = useState(false);
  const [step, setStep] = useState<"email" | "password">("email");
  const [showAlt, setShowAlt] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [passwordChanged, setPasswordChanged] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  // Client-side on purpose: the access token exists only in module memory
  // (tokenStore), so a hard load would drop it and make the new document
  // re-authenticate through /auth/refresh.
  const navigate = useNavigate();

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

  useEffect(() => {
    if (step === "password" && !challenge) passwordRef.current?.focus();
  }, [step, challenge]);

  // Same reset + workspace seed as authProvider.login, except the reset runs in
  // postCredentials() ahead of the POST, so the verify request is not scoped to
  // the outgoing session. The app must still mount with a workspace selected or
  // the identity query settles behind a blank gate.
  // Access token only — the refresh token lives in the HttpOnly cookie.
  const storeTokens = async (tokens: { access_token: string }) => {
    clearAllCaches(queryClient);
    tokenStore.setTokens(tokens.access_token);
    try {
      const { data: identity } = await httpClient.get(`${API_URL}/auth/me`);
      await seedWorkspace(identity);
    } catch {
      identityStore.clear();
    }
  };

  // Call authProvider directly instead of useLogin: refine's useLogin shows
  // an error toast for every success:false result, which would leak the
  // challenge token and never reach a per-call onError branch.
  // Email-first routing: when OAuth providers are configured, the domain
  // decides — a mapped domain jumps straight to its provider, anything else
  // falls through to the password step (a failed lookup degrades to it too,
  // since the lookup is an enhancement and its budget is separate).
  const continueWithEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.trim()) return;
    if (ssoProviders.length === 0) {
      setStep("password");
      return;
    }
    setPending(true);
    try {
      const { data } = await httpClient.post<{ provider: string | null }>(
        `${API_URL}/auth/sign-in/method`,
        { email: email.trim() },
      );
      if (data.provider) {
        window.location.assign(`${API_URL}/auth/oauth/${data.provider}/authorize`);
        return;
      }
      setStep("password");
    } catch {
      setStep("password");
    } finally {
      setPending(false);
    }
  };

  const submit = async (e: React.FormEvent) => {    e.preventDefault();
    setError(null);
    if (challenge) {
      setPending(true);
      try {
        const { data } = await postCredentials(() =>
          httpClient.post(`${API_URL}/auth/2fa/login`, {
            challenge_token: challenge,
            code,
            use_cookies: true,
          }),
        );
        await storeTokens(data);
        // replace: Back must not return to a spent sign-in form.
        navigate(afterAuthRedirect(), { replace: true });
      } catch {
        // The challenge survives a wrong code (the API consumes it only on
        // success), so stay on the code form for a retry with the same token.
        setCode("");
        setError("Verification failed. Try again.");
        codeRef.current?.focus();
      } finally {
        setPending(false);
      }
      return;
    }
    setPending(true);
    try {
      const res = await authProvider.login({ email, password });
      if (res.success) {
        navigate(res.redirectTo ?? "/", { replace: true });
        return;
      }
      // 2FA challenge arrives as "2fa_required:<token>" (see authProvider).
      const msg = (res.error as Error)?.message ?? "";
      const prefix = "2fa_required:";
      if (msg.startsWith(prefix)) {
        setChallenge(msg.slice(prefix.length));
        setError(null);
      } else {
        // Stay on the password step so the email is kept and only the
        // password needs retyping.
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
    <div className="bg-gradient-to-br from-primary/10 via-background to-muted flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <img src="/logo.svg" alt="SaaS Template" className="mx-auto mb-2 w-48" />
          <CardDescription>Sign in to your account</CardDescription>
          {passwordChanged && (
            <Badge variant="success" className="mt-2 w-fit self-center bg-green-800 hover:bg-green-900">
              Password changed — sign in with your new password
            </Badge>
          )}
        </CardHeader>
        <CardContent>
          {ssoProviders.length > 0 && !passwordEnabled && !challenge && (
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
          ) : step === "email" ? (
            <form onSubmit={continueWithEmail} className="flex flex-col gap-4">
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
              {error && <p className="text-destructive text-sm">{error}</p>}
              <Button type="submit" disabled={pending}>
                {pending ? "Checking…" : "Continue"}
              </Button>
            </form>
          ) : (
            <form onSubmit={submit} className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
                <span className="text-muted-foreground truncate">
                  Signing in as <span className="text-foreground font-medium">{email}</span>
                </span>
                <Button type="button" variant="ghost" size="sm" onClick={() => { setStep("email"); setError(null); }}>
                  Change
                </Button>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  ref={passwordRef}
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
          {passwordEnabled && ssoProviders.length > 0 && !challenge && (
            <div className="mt-4">
              <div className="flex items-center gap-3">
                <Separator className="flex-1" />
                <span className="text-muted-foreground text-xs">or</span>
                <Separator className="flex-1" />
              </div>
              <Button
                type="button"
                variant="outline"
                className="mt-4 w-full"
                disabled={pending}
                onClick={() => setShowAlt((v) => !v)}
              >
                {showAlt ? "Back to email sign-in" : "Sign in another way"}
              </Button>
              {showAlt && (
                <div className="mt-4">
                  <SsoButtons providers={ssoProviders} disabled={pending} />
                </div>
              )}
            </div>
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

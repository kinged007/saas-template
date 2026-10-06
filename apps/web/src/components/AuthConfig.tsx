import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";

import { OAUTH_CALLBACK_TIMEOUT_MS, oauthCallbackLoginHref, oauthCodeConsumed } from "./oauthCallback";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { afterAuthRedirect, authProvider, seedWorkspace } from "@/providers/authProvider";
import { API_URL, httpClient } from "@/providers/dataProvider";
import { identityStore, tokenStore } from "@/utils/storage";
import { postCredentials } from "@/utils/credentialPost";
import { clearAllCaches, queryClient } from "@/providers/queryClient";

export type AuthConfig = {
  registration_enabled: boolean;
  password_enabled: boolean;
  oauth_enabled: boolean;
  providers: Array<{ id: string; display_name: string }>;
};

let cached: AuthConfig | null = null;

export async function fetchAuthConfig(): Promise<AuthConfig> {
  if (cached) return cached;
  try {
    const { data } = await httpClient.get<AuthConfig>(`${API_URL}/auth/config`);
    cached = data;
  } catch {
    cached = { registration_enabled: false, password_enabled: false, oauth_enabled: false, providers: [] };
  }
  return cached;
}

export function useAuthConfig(): AuthConfig | null {
  const [config, setConfig] = useState<AuthConfig | null>(cached);
  useEffect(() => {
    if (!cached) fetchAuthConfig().then(setConfig);
  }, []);
  return config;
}

export function SsoButtons({ providers, disabled }: { providers: AuthConfig["providers"]; disabled?: boolean }) {
  if (!providers.length) return null;
  return (
    <div className="flex flex-col gap-2">
      {providers.map((p) => (
        <Button
          key={p.id}
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => {
            window.location.assign(`${API_URL}/auth/oauth/${p.id}/authorize`);
          }}
        >
          Continue with {p.display_name}
        </Button>
      ))}
    </div>
  );
}

/** Exchange the one-time OAuth code for tokens, then seed identity/workspace like login. */
export async function exchangeOAuthCode(code: string): Promise<{ twoFactor?: string }> {
  const { data } = await postCredentials(() =>
    httpClient.post(`${API_URL}/auth/oauth/token`, {
      code,
      use_cookies: true,
    }),
  );
  if (data.two_factor_required) return { twoFactor: data.challenge_token as string };
  clearAllCaches(queryClient);
  // Refresh token is in the HttpOnly cookie; only the access token is stored.
  tokenStore.setTokens(data.access_token);
  try {
    const { data: identity } = await httpClient.get(`${API_URL}/auth/me`);
    await seedWorkspace(identity);
  } catch {
    identityStore.clear();
  }
  return {};
}

// Module scope, not the ref below: the workspace provider leaves its loading
// gate as the identity settles, which unmounts and remounts this page with a
// fresh ref while the URL still carries the code — the ref alone resets with
// the instance and the code is exchanged twice.
let consumedCode: string | null = null;

const PENDING_STATUS = "Signing you in…";

export function OAuthCallbackPage() {
  const [status, setStatus] = useState(PENDING_STATUS);
  const [timedOut, setTimedOut] = useState(false);
  const pending = status === PENDING_STATUS;
  const navigate = useNavigate();
  // StrictMode runs this effect twice in dev and the code is single-use, so a
  // second exchange would race the first and report an expired code.
  const exchanged = useRef(false);
  useEffect(() => {
    if (exchanged.current) return;
    exchanged.current = true;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const error = params.get("error");
    if (error) {
      setStatus(error === "registration is disabled" ? "Registration is disabled." : "Sign-in failed.");
      return;
    }
    // Ahead of the missing-code branch: the workspace provider leaves its
    // loading gate as the identity settles, and that remount can land after
    // navigate() has rewritten the URL — code is null but it was ours, so
    // stopping here keeps a succeeding sign-in from painting an error.
    // Gated on the session: consumedCode is module state that no sign-out
    // clears, and the access token the exchange stored is in-memory only, so
    // logout and the 401 handler both drop it while the latch survives. Honoring
    // a latch with no session left it on "Signing you in…" forever.
    // Every terminal branch below links back to /login. The retry runs a
    // fresh authorize, so it carries a fresh single-use code and the latch
    // above stays correct.
    if (oauthCodeConsumed(code, consumedCode, tokenStore.getAccess() !== null)) return;
    if (!code) {
      setStatus("Missing sign-in code.");
      return;
    }
    consumedCode = code;
    exchangeOAuthCode(code)
      .then((res) => {
        if (res.twoFactor) {
          window.location.assign(`/login?challenge=${encodeURIComponent(res.twoFactor)}`);
          return;
        }
        // Client-side: the exchanged access token lives only in memory, so a
        // hard load would drop it and force a /auth/refresh round trip.
        // replace: this URL carries the now-consumed code — Back must not
        // return to it and re-fire the exchange.
        navigate(afterAuthRedirect(), { replace: true });
      })
      .catch(() => setStatus("Sign-in failed. The code may have expired."));
  }, [navigate]);
  // Bound the pending state: past this the page offers the escape instead of
  // hanging on "Signing you in…", which is otherwise indistinguishable from
  // the sessionAlive repeat path. Terminal states render the escape at once.
  useEffect(() => {
    const timer = window.setTimeout(() => setTimedOut(true), OAUTH_CALLBACK_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, []);
  void authProvider;
  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardContent className="flex flex-col items-center gap-4 pt-6 text-center text-sm">
          <p>{timedOut && pending ? "Sign-in is taking longer than expected." : status}</p>
          {(timedOut || !pending) && (
            <Button asChild>
              <Link to={oauthCallbackLoginHref(window.location.search)}>Back to sign-in</Link>
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

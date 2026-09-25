import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { authProvider, seedWorkspace } from "@/providers/authProvider";
import { API_URL, httpClient } from "@/providers/dataProvider";
import { identityStore, tokenStore, workspaceStore } from "@/utils/storage";
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

/** Exchange the one-time OAuth code for tokens, then seed identity/workspace like login.
 *  A `linked` result means the callback attached an identity to the already
 *  signed-in account: no tokens are minted, so just return to settings. */
export async function exchangeOAuthCode(code: string): Promise<{ twoFactor?: string; linked?: string }> {
  const { data } = await httpClient.post(`${API_URL}/auth/oauth/token`, {
    code,
    use_cookies: true,
  });
  if (data.linked) return { linked: data.provider as string };
  if (data.two_factor_required) return { twoFactor: data.challenge_token as string };
  workspaceStore.clear();
  identityStore.set(null);
  clearAllCaches(queryClient);
  // Refresh token is in the HttpOnly cookie; only the access token is stored.
  tokenStore.setTokens(data.access_token);
  try {
    const { data: identity } = await httpClient.get(`${API_URL}/auth/me`);
    await seedWorkspace(identity);
  } catch {
    identityStore.set(null);
  }
  return {};
}

export function OAuthCallbackPage() {
  const [status, setStatus] = useState("Signing you in…");
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const error = params.get("error");
    if (error) {
      const messages: Record<string, string> = {
        "registration is disabled": "Registration is disabled.",
        "this sign-in is already linked to another account":
          "That sign-in is already linked to a different account.",
      };
      setStatus(messages[error] ?? "Sign-in failed.");
      return;
    }
    if (!code) {
      setStatus("Missing sign-in code.");
      return;
    }
    exchangeOAuthCode(code)
      .then((res) => {
        if (res.twoFactor) {
          window.location.assign(`/login?challenge=${encodeURIComponent(res.twoFactor)}`);
          return;
        }
        if (res.linked) {
          window.location.assign("/settings/profile");
          return;
        }
        window.location.assign("/");
      })
      .catch(() => setStatus("Sign-in failed. The code may have expired."));
  }, []);
  void authProvider;
  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardContent className="pt-6 text-center text-sm">{status}</CardContent>
      </Card>
    </div>
  );
}

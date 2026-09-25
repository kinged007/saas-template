import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { API_URL, httpClient } from "../providers/dataProvider";

export type OAuthIdentity = {
  id: string;
  provider: string;
  email: string | null;
  created_at?: string;
};

export function useOAuthIdentities() {
  return useQuery({
    queryKey: ["oauth", "identities"],
    queryFn: async () => {
      const { data } = await httpClient.get<OAuthIdentity[]>(`${API_URL}/auth/oauth/identities`);
      return data ?? [];
    },
  });
}

export function useUnlinkOAuthIdentity() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await httpClient.delete(`${API_URL}/auth/oauth/identities/${id}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["oauth", "identities"] }),
  });
}

/** Mint a single-use ticket, then hand the browser to the provider. */
export async function startLinkProvider(provider: string) {
  const { data } = await httpClient.post<{ link_token: string }>(
    `${API_URL}/auth/oauth/identities/link-token`,
  );
  window.location.assign(
    `${API_URL}/auth/oauth/${encodeURIComponent(provider)}/authorize?link=${encodeURIComponent(
      data.link_token,
    )}`,
  );
}

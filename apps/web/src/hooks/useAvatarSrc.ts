import * as React from "react";

import { getAvatarSrc, isStoredFileUrl } from "@/lib/avatar";
import { API_URL, httpClient } from "@/providers/dataProvider";

/**
 * Resolve an avatar_url into something `<AvatarImage>` can actually render.
 *
 * `POST /files` hands back the resource address, and that endpoint requires a
 * bearer token plus X-Workspace-ID — headers a browser `<img>` never sends, so
 * the value would silently fall back to initials. Stored files are therefore
 * fetched with the app's authenticated client and passed on as an object URL.
 * Anything else (external https URL, data URL) is returned untouched.
 *
 * ponytail: one in-flight request per rendered avatar and no cross-render cache;
 * add a shared blob cache when a page renders enough of them to matter.
 */
export function useAvatarSrc(avatarUrl?: string | null): string | undefined {
  const direct = getAvatarSrc(avatarUrl);
  const stored = direct !== undefined && isStoredFileUrl(direct, API_URL);
  const [objectUrl, setObjectUrl] = React.useState<string>();

  React.useEffect(() => {
    if (!stored || !direct) {
      setObjectUrl(undefined);
      return;
    }
    let cancelled = false;
    let created: string | undefined;
    httpClient
      .get(direct, { responseType: "blob" })
      .then((resp) => {
        if (cancelled) return;
        created = window.URL.createObjectURL(resp.data as Blob);
        setObjectUrl(created);
      })
      .catch(() => setObjectUrl(undefined));
    return () => {
      cancelled = true;
      if (created) window.URL.revokeObjectURL(created);
    };
  }, [direct, stored]);

  return stored ? objectUrl : direct;
}
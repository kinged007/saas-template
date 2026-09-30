import { useCustom, useCustomMutation, useGetIdentity, useInvalidate } from "@refinedev/core";
import { useQuery } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import type { Identity, UserProfile } from "../types";
import { getProfileField } from "../types";
export { getProfileField };

import { API_URL, httpClient } from "../providers/dataProvider";
import { identityStore, tokenStore } from "../utils/storage";
import { clearAllCaches } from "../providers/queryClient";

export function useProfile() {
  const { data: identity } = useGetIdentity<Identity>();
  const custom = useCustom<UserProfile>({
    url: "me/profile",
    method: "get",
  });
  // `simple-rest` wraps a `custom` response as `{ data }`, so read the query
  // payload: `result.data` is a frozen, always-truthy `{}` until the request
  // settles, which is what left the form blank. `/auth/me`'s embed is only the
  // first-paint fallback — it can arrive with all-null fields.
  const data =
    (custom.query.data as { data?: UserProfile } | undefined)?.data ?? identity?.profile;
  const isLoading = custom.query.isPending as boolean;
  const isError = custom.query.isError as boolean;
  return {
    data,
    isLoading,
    isError,
    query: custom.query,
    refetch: custom.query.refetch,
  };
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const { mutate, mutateAsync, mutation } = useCustomMutation<UserProfile>();

  const update = useCallback(
    (
      values: Record<string, unknown>,
      opts?: { isPut?: boolean; onSuccess?: () => void; onError?: (e: unknown) => void }
    ) => {
      const isPut = opts?.isPut ?? false;
      mutate(
        {
          url: "me/profile",
          method: isPut ? "put" : "patch",
          values,
          successNotification: {
            message: "Profile updated",
            type: "success",
          },
          errorNotification: false,
        } as never,
        {
          onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["auth"] });
            queryClient.invalidateQueries({ queryKey: ["data"] });
            invalidate({ resource: "profile", invalidates: ["all"] });
            opts?.onSuccess?.();
          },
          onError: (e) => {
            opts?.onError?.(e);
          },
        }
      );
    },
    [mutate, queryClient, invalidate]
  );

  const updateAsync = useCallback(
    async (values: Record<string, unknown>, isPut = false) => {
      const res = await mutateAsync({
        url: "me/profile",
        method: isPut ? "put" : "patch",
        values,
        successNotification: {
          message: "Profile updated",
          type: "success",
        },
        errorNotification: false,
      } as never);
      queryClient.invalidateQueries({ queryKey: ["auth"] });
      queryClient.invalidateQueries({ queryKey: ["data"] });
      return res;
    },
    [mutateAsync, queryClient]
  );

  return { mutate: update, mutateAsync: updateAsync, mutation };
}

export function useExportProfile() {
  const exportMyData = useCallback(async () => {
    const resp = await httpClient.get(`${API_URL}/me/export`, {
      responseType: "blob",
    });
    const disposition = (resp.headers["content-disposition"] as string) || (resp.headers["Content-Disposition"] as string) || "";
    let filename = `export.json`;
    const match = disposition.match(/filename="?([^"]+)"?/);
    if (match) filename = match[1];
    const blob = new Blob([resp.data as BlobPart], { type: "application/json" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  }, []);

  const exportUserData = useCallback(async (userId: string) => {
    const resp = await httpClient.get(`${API_URL}/users/${userId}/export`, {
      responseType: "blob",
    });
    const disposition = (resp.headers["content-disposition"] as string) || (resp.headers["Content-Disposition"] as string) || "";
    let filename = `export-${userId}.json`;
    const match = disposition.match(/filename="?([^"]+)"?/);
    if (match) filename = match[1];
    const blob = new Blob([resp.data as BlobPart], { type: "application/json" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  }, []);

  return { exportMyData, exportUserData };
}

export function useDeleteAccount() {
  const queryClient = useQueryClient();
  const { mutate, mutateAsync, mutation } = useCustomMutation();

  const deleteMyAccount = useCallback(
    (values: { confirm: string; password?: string }, opts?: { onSuccess?: () => void; onError?: (e: unknown) => void }) => {
      mutate(
        {
          url: "me",
          method: "delete",
          values,
          successNotification: false,
          errorNotification: false,
        } as never,
        {
          onSuccess: () => {
            tokenStore.clear();
            identityStore.set(null);
            clearAllCaches(queryClient);
            opts?.onSuccess?.();
          },
          onError: (e) => opts?.onError?.(e),
        }
      );
    },
    [mutate, queryClient]
  );

  const deleteMyAccountAsync = useCallback(
    async (values: { confirm: string; password?: string }) => {
      const res = await mutateAsync({
        url: "me",
        method: "delete",
        values,
        successNotification: false,
        errorNotification: false,
      } as never);
      tokenStore.clear();
      identityStore.set(null);
      clearAllCaches(queryClient);
      return res;
    },
    [mutateAsync, queryClient]
  );

  return { mutate: deleteMyAccount, mutateAsync: deleteMyAccountAsync, mutation };
}

export function usePublicProfile(userId: string | null | undefined) {
  const enabled = Boolean(userId);
  const q = useQuery<UserProfile>({
    queryKey: ["public-profile", userId],
    enabled,
    queryFn: async () => {
      const res = await httpClient.get<UserProfile>(`${API_URL}/users/${userId}/profile`);
      return res.data;
    },
  });
  return { data: q.data, isLoading: q.isPending, isError: q.isError, query: q };
}

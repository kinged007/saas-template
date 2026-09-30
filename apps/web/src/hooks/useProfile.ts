import { useCustom, useCustomMutation, useGetIdentity, useInvalidate } from "@refinedev/core";
import { useQuery } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useParams } from "react-router";

import type { Identity, UserProfile } from "../types";
import { getProfileField } from "../types";
export { getProfileField };

/**
 * The member being edited, or null on the self-service routes.
 *
 * The target editor is routed as `users/:id/settings/*`; the self routes carry
 * no `:id`, so the route itself is the switch. Every section in a settings
 * registry reads it, which is what makes a new tab target-aware for free.
 *
 * Your own id is the self page, not a delegated editor: the editor's routes
 * manage other members and the entries are hidden on your own row.
 */
export function useTargetUserId(): string | null {
  const { data: identity } = useGetIdentity<Identity>();
  const id = useParams().id ?? null;
  return id && id !== identity?.id ? id : null;
}

import { API_URL, httpClient } from "../providers/dataProvider";
import { identityStore, tokenStore } from "../utils/storage";
import { clearAllCaches } from "../providers/queryClient";

/**
 * Self profile, or another member's when `userId` is given.
 *
 * The target routes are workspace-scoped and gated on `profile:update`; the
 * httpClient interceptor attaches X-Workspace-ID. `null`/`undefined` means the
 * signed-in user, which is the only shape `/me/profile` answers.
 */
export function useProfile(userId?: string | null) {
  const { data: identity } = useGetIdentity<Identity>();
  const isSelf = !userId;
  const enabled = isSelf ? !identity?.profile : true;
  const custom = useCustom<UserProfile>({
    url: isSelf ? "me/profile" : `users/${userId}/profile`,
    method: "get",
    queryOptions: { enabled },
  });
  const data =
    (isSelf ? (identity?.profile as UserProfile | undefined) : undefined) ??
    (custom.result?.data as UserProfile | undefined);
  const isLoading = enabled ? (custom.query.isPending as boolean) : false;
  const isError = enabled ? (custom.query.isError as boolean) : false;
  return {
    data,
    isLoading,
    isError,
    query: custom.query,
    result: custom.result,
    refetch: custom.query.refetch,
  };
}

export function useUpdateProfile(userId?: string | null) {
  const queryClient = useQueryClient();
  const invalidate = useInvalidate();
  const { mutate, mutateAsync, mutation } = useCustomMutation<UserProfile>();
  const url = userId ? `users/${userId}/profile` : "me/profile";

  const update = useCallback(
    (
      values: Record<string, unknown>,
      opts?: { isPut?: boolean; onSuccess?: () => void; onError?: (e: unknown) => void }
    ) => {
      const isPut = opts?.isPut ?? false;
      mutate(
        {
          url,
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
            // Only the self profile feeds the cached identity.
            if (!userId) {
              queryClient.invalidateQueries({ queryKey: ["auth"] });
              queryClient.invalidateQueries({ queryKey: ["data"] });
              invalidate({ resource: "profile", invalidates: ["all"] });
              queryClient.invalidateQueries({ queryKey: ["getIdentity"] });
            }
            opts?.onSuccess?.();
          },
          onError: (e) => {
            opts?.onError?.(e);
          },
        }
      );
    },
    [mutate, queryClient, invalidate, url, userId]
  );

  const updateAsync = useCallback(
    async (values: Record<string, unknown>, isPut = false) => {
      const res = await mutateAsync({
        url,
        method: isPut ? "put" : "patch",
        values,
        successNotification: {
          message: "Profile updated",
          type: "success",
        },
        errorNotification: false,
      } as never);
      if (!userId) {
        queryClient.invalidateQueries({ queryKey: ["auth"] });
        queryClient.invalidateQueries({ queryKey: ["data"] });
        queryClient.invalidateQueries({ queryKey: ["getIdentity"] });
      }
      return res;
    },
    [mutateAsync, queryClient, url, userId]
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

import { useList, useCustom } from "@refinedev/core";
import type {
  BaseRecord,
  HttpError,
  UseCustomProps,
  UseListProps,
} from "@refinedev/core";

import { useWorkspace } from "../contexts/WorkspaceContext";

/**
 * Workspace-scoped data hooks.
 *
 * refine's query keys are `[provider, resource, action, params]` with no
 * workspace segment: without scoping, workspace A's rows and workspace B's
 * rows share one cache entry and whichever was fetched last renders under
 * both switcher labels. These wrappers inject the active workspace id into
 * `meta` (folded into the key's `params` by refine's key builders), so each
 * workspace gets its own cache entry, and keep the query disabled until a
 * workspace is selected so no request fires without X-Workspace-ID.
 */

function scopedMeta(
  meta: Record<string, unknown> | undefined,
  workspaceId: string | undefined,
) {
  return workspaceId ? { ...meta, workspaceId } : meta;
}

function scopedEnabled<T extends { enabled?: unknown }>(
  queryOptions: T | undefined,
  workspaceId: string | undefined,
) {
  const enabled = (queryOptions as { enabled?: boolean } | undefined)?.enabled !== false;
  return { ...queryOptions, enabled: !!workspaceId && enabled };
}

export function useWorkspaceList<
  TQueryFnData extends BaseRecord = BaseRecord,
  TError extends HttpError = HttpError,
  TData extends BaseRecord = TQueryFnData,
>(props: UseListProps<TQueryFnData, TError, TData>) {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id;
  const { queryOptions, meta, ...rest } = props;
  return useList<TQueryFnData, TError, TData>({
    ...rest,
    meta: scopedMeta(meta, workspaceId),
    queryOptions: scopedEnabled(queryOptions, workspaceId),
  });
}

export function useWorkspaceCustom<
  TQueryFnData extends BaseRecord = BaseRecord,
  TError extends HttpError = HttpError,
  TQuery = unknown,
  TPayload = unknown,
  TData extends BaseRecord = TQueryFnData,
>(props: UseCustomProps<TQueryFnData, TError, TQuery, TPayload, TData>) {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id;
  const { queryOptions, meta, ...rest } = props;
  return useCustom<TQueryFnData, TError, TQuery, TPayload, TData>({
    ...rest,
    meta: scopedMeta(meta, workspaceId),
    queryOptions: scopedEnabled(queryOptions, workspaceId),
  });
}

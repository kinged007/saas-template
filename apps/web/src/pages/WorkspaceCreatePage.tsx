import { useState } from "react";
import { useCreate, useGetIdentity } from "@refinedev/core";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { PageHeader } from "../components/refine-ui/layout/page-header";
import { PendingInvitationsCard } from "../components/PendingInvitations";
import { IDENTITY_QUERY_OPTIONS, useWorkspace } from "../contexts/WorkspaceContext";
import { identityStore, setActiveWorkspaceId, workspaceStore } from "../utils/storage";
import type { Identity, Workspace } from "../types";
import type { QueryClient } from "@tanstack/react-query";

// Owner permissions mirror the backend owner role (see
// permissions_for_role("owner")): full access plus the "*" wildcard.
// POST /workspaces returns role: "owner" but no permissions array, so the
// seeded entry carries these until the identity refetch replaces it.
// "*" alone is enough: every permission check is
// `permissions.includes("*") || permissions.includes(required)`.
const OWNER_PERMISSIONS = ["*"];

// Latest seeded entry for the created workspace, read back after the
// refetch so the painted selection matches the identity entry exactly
// (no resync wipe from a permissions mismatch).
let lastSeed: Workspace | null = null;

function seedIdentityCache(client: QueryClient, created: Workspace) {
  lastSeed = { ...created, role: "owner", permissions: OWNER_PERMISSIONS };
  client.setQueryData<Identity & { workspaces: Workspace[] }>(["auth", "identity"], (old) => {
    if (!old) return old;
    const workspaces = [lastSeed as Workspace, ...old.workspaces.filter((w) => w.id !== created.id)];
    const seeded = { ...old, workspaces };
    identityStore.set(seeded);
    return seeded;
  });
}

export function WorkspaceCreatePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { mutate, mutation } = useCreate();
  const { refetch } = useGetIdentity<Identity>({
    queryOptions: IDENTITY_QUERY_OPTIONS,
  });
  const { data: identity } = useGetIdentity<Identity>({
    queryOptions: IDENTITY_QUERY_OPTIONS,
  });
  const { setWorkspace } = useWorkspace();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  if (identity?.single_workspace === true) {
    return <Navigate to="/" replace />;
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    mutate(
      {
        resource: "workspaces",
        values: { name, slug: slug || undefined, description: description || undefined },
        successNotification: { message: "Workspace created", type: "success" },
      },
      {
        onSuccess: async (data) => {
          const created = data.data as Workspace;
          // The provider auto-selects workspaces[0] when the selection is
          // missing from the identity list, so committing the new workspace
          // before the refetch lands gets overwritten with the old one.
          // Seed the stores + identity cache synchronously (with the
          // owner's full permissions, which the POST response omits), then
          // refetch: whichever identity payload wins, it resolves to the
          // new workspace and the selection sticks without a cache wipe.
          const userId = identity?.id
            ?? (identityStore.get() as Identity | null)?.id
            ?? null;
          workspaceStore.set(created.id, userId);
          setActiveWorkspaceId(created.id);
          seedIdentityCache(queryClient, created);
          const { data: fresh } = await refetch();
          // Prefer the refetched entry (authoritative role/permissions);
          // fall back to the seeded one if the refetch failed.
          const entry = fresh?.workspaces?.find((w) => w.id === created.id)
            ?? (lastSeed?.id === created.id ? lastSeed : created);
          setWorkspace(entry);
          navigate("/");
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Create workspace" />
      <PendingInvitationsCard />
      <Card className="max-w-lg">
        <CardContent className="pt-6">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              placeholder="Acme Corp"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="slug">Slug</Label>
            <Input
              id="slug"
              placeholder="acme-corp (optional)"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              placeholder="What is this workspace for?"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={mutation.isPending || !name.trim()}>
            {mutation.isPending ? "Creating…" : "Create workspace"}
          </Button>
        </form>
      </CardContent>
      </Card>
    </div>
  );
}

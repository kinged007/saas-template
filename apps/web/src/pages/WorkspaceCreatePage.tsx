import { useState } from "react";
import { useCreate, useGetIdentity } from "@refinedev/core";
import { Navigate, useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { PageHeader } from "../components/refine-ui/layout/page-header";
import { IDENTITY_QUERY_OPTIONS, useWorkspace } from "../contexts/WorkspaceContext";
import type { Identity, Workspace } from "../types";

export function WorkspaceCreatePage() {
  const navigate = useNavigate();
  const { mutate, mutation } = useCreate();
  const { refetch } = useGetIdentity();
  const { data: identity } = useGetIdentity<Identity>({ queryOptions: IDENTITY_QUERY_OPTIONS });
  if (identity?.single_workspace === true) {
    return <Navigate to="/" replace />;
  }
  const { setWorkspace } = useWorkspace();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    mutate(
      {
        resource: "workspaces",
        values: { name, slug: slug || undefined, description: description || undefined },
        successNotification: { message: "Workspace created", type: "success" },
      },
      {
        onSuccess: (data) => {
          // Jump straight into the new workspace: record it as current
          // before the identity refetch lands, so neither the provider nor
          // the previous workspace's stored id can re-select an old one.
          setWorkspace(data.data as Workspace);
          refetch();
          navigate("/");
        },
      },
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Create workspace" />
      <Card className="max-w-lg">
        <CardContent>
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

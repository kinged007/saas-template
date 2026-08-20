import { useState } from "react";
import { useCreate, useGetIdentity } from "@refinedev/core";
import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { PageHeader } from "../components/refine-ui/layout/page-header";

export function WorkspaceCreatePage() {
  const navigate = useNavigate();
  const { mutate, mutation } = useCreate();
  const { refetch } = useGetIdentity();
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
        onSuccess: () => {
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

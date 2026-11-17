import { useEffect, useRef, useState } from "react";
import { useIsAuthenticated, useCustomMutation } from "@refinedev/core";
import { Link, useNavigate, useSearchParams } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { useWorkspace } from "../contexts/WorkspaceContext";
import { pendingInvitationStore } from "../utils/storage";
import { errorMessage } from "@/utils/errorMessage";

/**
 * Landing page for the emailed invite link (`/invitations/accept?token=…`).
 *
 * Public on purpose: invitations go to unregistered recipients, so the
 * visitor may have no session. The token is kept in storage so the auth
 * provider can return here after sign in / registration.
 */
export function InvitationAcceptPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { data: auth, isPending: checkingAuth } = useIsAuthenticated();
  const authenticated = auth?.authenticated;
  const { refresh: refreshIdentity } = useWorkspace();
  const navigate = useNavigate();
  const { mutate: accept } = useCustomMutation();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (token) pendingInvitationStore.set(token);
  }, [token]);

  useEffect(() => {
    if (!token || authenticated !== true || started.current) return;
    started.current = true;
    accept(
      { url: `invitations/accept?token=${encodeURIComponent(token)}`, method: "post", values: {} },
      {
        onSuccess: () => {
          pendingInvitationStore.clear();
          refreshIdentity();
          navigate("/invitations", { replace: true });
        },
        onError: (err) => {
          pendingInvitationStore.clear();
          setError(errorMessage(err));
        },
      },
    );
  }, [token, authenticated, accept, navigate, refreshIdentity]);

  if (!token) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Invitation link incomplete</CardTitle>
          <CardDescription>This link is missing its invitation token.</CardDescription>
        </CardHeader>
        <CardFooter>
          <Link to="/invitations" className="text-primary text-sm underline underline-offset-4">
            Go to your invitations
          </Link>
        </CardFooter>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Could not accept invitation</CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
        <CardFooter>
          <Link to="/invitations" className="text-primary text-sm underline underline-offset-4">
            Go to your invitations
          </Link>
        </CardFooter>
      </Card>
    );
  }

  if (checkingAuth || authenticated === true) {
    return (
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Accepting invitation…</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">
            Hold on while we join you to the workspace.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>You have been invited</CardTitle>
        <CardDescription>
          Sign in or create an account with the invited email address to join the workspace.
        </CardDescription>
      </CardHeader>
      <CardFooter className="gap-2">
        <Link to="/register">
          <Button>Create account</Button>
        </Link>
        <Link to="/login">
          <Button variant="outline">Sign in</Button>
        </Link>
      </CardFooter>
    </Card>
  );
}

import { useState } from "react";
import { useCustom, useCustomMutation } from "@refinedev/core";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyRow, formatDate } from "@/components/ui";
import { useTargetUserId } from "@/hooks/useProfile";
import type { AuthSession } from "../../profile/sections/SecuritySection";
import { sessionsEmptyMessage } from "./sessions-empty";

/**
 * Security tab of the member editor (`users/:id/settings/security`).
 *
 * Deliberately narrower than the self-service security page: setting a
 * password and revoking sessions are delegated actions, while 2FA setup and
 * "change my password" require a credential only the account holder has.
 */
export function SecuritySection() {
  const userId = useTargetUserId();
  const base = `users/${userId}`;
  // Null on the self routes, so the query waits for a real target instead of
  // asking for `users/null`.
  const sessions = useCustom<AuthSession[]>({
    url: `${base}/sessions`,
    method: "get",
    queryOptions: { enabled: Boolean(userId) },
  });
  const { mutateAsync: setPasswordMutate, mutation: setPasswordMutation } = useCustomMutation();
  const { mutateAsync: revokeOneMutate, mutation: revokeOneMutation } = useCustomMutation();
  const { mutateAsync: revokeAllMutate, mutation: revokeAllMutation } = useCustomMutation();

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const call = (
    mutate: typeof setPasswordMutate,
    url: string,
    method: "post" | "delete",
    values?: unknown,
  ) =>
    mutate({ url, method, values, errorNotification: false } as never) as Promise<{
      data: unknown;
    }>;

  const list: AuthSession[] = Array.isArray(sessions.result?.data)
    ? (sessions.result.data as AuthSession[])
    : [];
  // `result` is undefined on error as well as on empty, so a failed query would
  // otherwise render as "No active sessions." — say what happened instead.
  const emptyMessage = sessionsEmptyMessage(list.length, sessions.query);

  const passwordValid =
    password.length >= 8 && password === confirmPassword && confirmPassword.length > 0;

  const setPasswordForMember = async () => {
    try {
      await call(setPasswordMutate, `${base}/password`, "post", { new_password: password });
      setPassword("");
      setConfirmPassword("");
      // Setting a password revokes every session of the target.
      sessions.query.refetch();
      toast.success("Password set. All of that member's sessions were revoked.");
    } catch (e) {
      toast.error((e as Error)?.message ?? "Could not set the password");
    }
  };

  const revokeOne = async (id: string) => {
    try {
      await call(revokeOneMutate, `${base}/sessions/${id}`, "delete");
      toast.success("Session revoked");
      sessions.query.refetch();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Revoke failed");
    }
  };

  const revokeAll = async () => {
    try {
      await call(revokeAllMutate, `${base}/sessions`, "delete");
      toast.success("All sessions revoked");
      sessions.query.refetch();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Revoke failed");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Set password</CardTitle>
          <CardDescription>
            Sets a new password and signs this member out everywhere. Minimum 8 characters.
            Two-factor authentication stays under the member&apos;s own control.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="member-new-password">New password</Label>
            <Input
              id="member-new-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="member-confirm-password">Confirm new password</Label>
            <Input
              id="member-confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
            {confirmPassword && password !== confirmPassword && (
              <p className="text-destructive text-sm">Passwords do not match.</p>
            )}
          </div>
          <div>
            <Button
              onClick={setPasswordForMember}
              disabled={!passwordValid || setPasswordMutation.isPending}
            >
              Set password
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Active sessions</CardTitle>
          <CardDescription>
            Devices this member is signed in to. Revoking stops that session from refreshing; an
            access token already issued stays valid until it expires.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Signed in</TableHead>
                  <TableHead>IP</TableHead>
                  <TableHead>Device</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {formatDate(s.created_at)}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{s.ip_address ?? "—"}</TableCell>
                    <TableCell
                      className="text-muted-foreground max-w-xs truncate text-xs"
                      title={s.user_agent ?? ""}
                    >
                      {s.user_agent ?? "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => revokeOne(s.id)}
                        disabled={revokeOneMutation.isPending}
                      >
                        Revoke
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {emptyMessage && <EmptyRow colSpan={4}>{emptyMessage}</EmptyRow>}
              </TableBody>
            </Table>
          </div>
          {list.length > 0 && (
            <div className="flex justify-end pt-4">
              <Button
                variant="destructive"
                size="sm"
                onClick={revokeAll}
                disabled={revokeAllMutation.isPending}
              >
                Revoke all sessions
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useCustom, useCustomMutation } from "@refinedev/core";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/CopyButton";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyRow, formatDate } from "@/components/ui";
import { useAuthConfig } from "@/components/AuthConfig";
import { errorMessage } from "@/utils/errorMessage";
import { useWorkspace } from "@/contexts/WorkspaceContext";

export type AuthSession = {
  id: string;
  created_at?: string | null;
  expires_at?: string | null;
  revoked_at?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  current?: boolean;
};

/**
 * One row's Revoke button. It owns the request itself (hooks cannot live in
 * the .map loop), so a pending revoke disables only its own row instead of
 * every other row's — the per-row pending fix #1354 shipped in the member
 * editor.
 */
function SessionRevokeButton({
  base,
  sessionId,
  onRevoked,
}: {
  base: string;
  sessionId: string;
  onRevoked: () => void;
}) {
  const { mutateAsync, mutation } = useCustomMutation();
  const revoke = async () => {
    try {
      await (mutateAsync({
        url: `${base}/sessions/${sessionId}`,
        method: "delete",
        errorNotification: false,
      } as never) as Promise<{ data: unknown }>);
      toast.success("Session revoked");
      onRevoked();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Revoke failed");
    }
  };
  return (
    <Button variant="outline" size="sm" onClick={revoke} disabled={mutation.isPending}>
      Revoke
    </Button>
  );
}

export function SecuritySection() {
  const sessions = useCustom<AuthSession[]>({ url: "auth/sessions", method: "get" });
  const status = useCustom<{ enabled: boolean }>({ url: "auth/2fa/status", method: "get" });
  const config = useAuthConfig();
  const { workspace } = useWorkspace();
  const { mutateAsync: changePasswordMutate, mutation: changePasswordMutation } = useCustomMutation();
  const { mutateAsync: setupMutate, mutation: setupMutation } = useCustomMutation();
  const { mutateAsync: enableMutate, mutation: enableMutation } = useCustomMutation();
  const { mutateAsync: disableMutate, mutation: disableMutation } = useCustomMutation();
  const { mutateAsync: revokeAllMutate, mutation: revokeAllMutation } = useCustomMutation();
  const call = (
    mutate: typeof changePasswordMutate,
    url: string,
    method: "post" | "delete",
    values?: unknown,
  ) =>
    mutate({ url, method, values, errorNotification: false } as never) as Promise<{ data: unknown }>;

  const list: AuthSession[] = Array.isArray(sessions.result?.data) ? (sessions.result.data as AuthSession[]) : [];
  const enabled = (status.result?.data as { enabled?: boolean } | undefined)?.enabled ?? false;
  // The deployment or the active workspace can require MFA; either one blocks
  // workspace access for accounts without an enrolled authenticator.
  const mfaRequired = config?.mfa_required === true || workspace?.mfa_required === true;

  const [setupUri, setSetupUri] = useState<string | null>(null);
  const [setupSecret, setSetupSecret] = useState<string | null>(null);
  const [setupToken, setSetupToken] = useState<string | null>(null);
  const [setupCode, setSetupCode] = useState("");
  const [copied, setCopied] = useState(false);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [password, setPassword] = useState("");
  const [disableOpen, setDisableOpen] = useState(false);
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [changeCode, setChangeCode] = useState("");

  // The copy confirmation is a 1.5 s window owned by one timer: a second click
  // restarts it rather than stacking a second one that ends it early, and the
  // pending timeout dies with the component instead of updating unmounted state.
  const copyTimer = useRef<number | undefined>(undefined);
  const clearCopied = () => {
    window.clearTimeout(copyTimer.current);
    setCopied(false);
  };
  useEffect(() => () => window.clearTimeout(copyTimer.current), []);

  const refresh = () => {
    sessions.query.refetch();
    status.query.refetch();
  };

  const revokeAll = async () => {
    try {
      await call(revokeAllMutate, "auth/sessions", "delete");
      toast.success("All other sessions revoked");
      sessions.query.refetch();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Revoke failed");
    }
  };

  const startSetup = async () => {
    try {
      const r = (await call(setupMutate, "auth/2fa/setup", "post")) as unknown as {
        data: { setup_token: string; otpauth_uri: string; secret: string };
      };
      const data = r.data;
      setSetupToken(data.setup_token);
      setSetupUri(data.otpauth_uri);
      setSetupSecret(data.secret);
      setSetupCode("");
      setBackupCodes(null);
      clearCopied();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Setup failed");
    }
  };

  const confirmSetup = async () => {
    if (!setupToken) return;
    try {
      const r = (await call(enableMutate, "auth/2fa/enable", "post", { setup_token: setupToken, code: setupCode })) as unknown as {
        data: { backup_codes: string[] };
      };
      setBackupCodes(r.data.backup_codes ?? []);
      setSetupUri(null);
      setSetupSecret(null);
      setSetupToken(null);
      clearCopied();
      toast.success("Two-factor enabled");
      refresh();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Invalid code");
    }
  };

  const disable = async () => {
    try {
      await call(disableMutate, "auth/2fa/disable", "post", { password });
      setDisableOpen(false);
      setPassword("");
      toast.success("Two-factor disabled");
      refresh();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Disable failed");
    }
  };

  const changePassword = async () => {
    try {
      await call(changePasswordMutate, "auth/change-password", "post", {
        current_password: currentPw,
        new_password: newPw,
        ...(enabled && changeCode ? { code: changeCode } : {}),
      });
      // All sessions are revoked server-side; the access token is dead.
      // The query flag is read by LoginPage — a toast here is torn down by
      // the navigation below, so the confirmation has to live on /login.
      window.location.assign("/login?password_changed=1");
    } catch (e) {
      toast.error((e as Error)?.message ?? "Change failed");
    }
  };

  const changeValid =
    currentPw.length >= 8 && newPw.length >= 8 && newPw === confirmPw && (!enabled || changeCode.length >= 6);

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>
            {enabled
              ? "Confirm with your current password and a 2FA code. All sessions are revoked."
              : "Confirm with your current password. All sessions are revoked."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="change-current">Current password</Label>
            <Input id="change-current" type="password" autoComplete="current-password" value={currentPw} onChange={(e) => setCurrentPw(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="change-new">New password</Label>
            <Input id="change-new" type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="change-confirm">Confirm new password</Label>
            <Input id="change-confirm" type="password" autoComplete="new-password" value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} />
            {confirmPw && newPw !== confirmPw && (
              <p className="text-sm text-destructive">Passwords do not match.</p>
            )}
          </div>
          {enabled && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="change-code">Two-factor code</Label>
              <Input id="change-code" maxLength={10} value={changeCode} onChange={(e) => setChangeCode(e.target.value)} placeholder="123456" />
            </div>
          )}
          <div>
            <Button onClick={changePassword} disabled={!changeValid || changePasswordMutation.isPending}>
              Change password
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Two-factor authentication</CardTitle>
          <CardDescription>
            {enabled ? "TOTP is enabled. Login requires a code from your authenticator app." : "Add a second factor with any authenticator app (TOTP)."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {mfaRequired && !enabled && (
            <p className="rounded-md border border-yellow-500/40 bg-yellow-500/10 px-3 py-2 text-sm">
              Two-factor authentication is required
              {config?.mfa_required === true
                ? " for this deployment"
                : ` for ${workspace?.name ?? "your workspace"}`}
              {" "}— set up your authenticator to keep workspace access.
            </p>
          )}
          {!enabled && !setupUri && (
            <div>
              <Button variant="outline" onClick={startSetup} disabled={setupMutation.isPending}>
                Set up authenticator
              </Button>
            </div>
          )}
          {!enabled && setupUri && (
            <div className="flex flex-col gap-3">
              <p className="text-sm">Scan this code in your authenticator app, then enter the 6-digit code:</p>
              <QRCodeSVG value={setupUri} size={192} className="rounded border bg-white p-2" />
              <div className="flex flex-col gap-1">
                <p className="text-sm text-muted-foreground">Can&apos;t scan? Enter this key manually:</p>
                <div className="flex items-center gap-2">
                  <code className="bg-muted block flex-1 rounded p-2 font-mono text-xs break-all">{setupSecret}</code>
                  <CopyButton
                    copied={copied}
                    label="Copy setup key"
                    onClick={async () => {
                      if (!setupSecret) return;
                      // Clear before the write so the previous window dies even if
                      // this one never reaches the clipboard.
                      clearCopied();
                      try {
                        await navigator.clipboard.writeText(setupSecret);
                        setCopied(true);
                        copyTimer.current = window.setTimeout(() => setCopied(false), 1500);
                      } catch (e) {
                        // A denied write must not leave a stale confirmation:
                        // `clearCopied` above already reset `copied`, so only
                        // the toast is left to show.
                        toast.error("Could not copy setup key", {
                          description: errorMessage(e),
                        });
                      }
                    }}
                  />
                </div>
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="totp-code">Code</Label>
                <Input id="totp-code" inputMode="numeric" maxLength={8} value={setupCode} onChange={(e) => setSetupCode(e.target.value)} placeholder="123456" />
              </div>
              <div className="flex gap-2">
                <Button onClick={confirmSetup} disabled={!setupCode || enableMutation.isPending}>Enable</Button>
                <Button variant="outline" onClick={() => { setSetupUri(null); setSetupSecret(null); setSetupToken(null); clearCopied(); }}>Cancel</Button>
              </div>
            </div>
          )}
          {backupCodes && (
            <div className="flex flex-col gap-2">
              <p className="text-sm font-medium">Backup codes — store these now, each works once:</p>
              <code className="bg-muted block rounded p-2 font-mono text-xs">{backupCodes.join("  ")}</code>
              <Button variant="outline" size="sm" className="self-start" onClick={() => setBackupCodes(null)}>Done</Button>
            </div>
          )}
          {enabled && (
            <div>
              <Separator className="mb-4" />
              <Button variant="destructive" onClick={() => setDisableOpen(true)}>Disable two-factor</Button>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Active sessions</CardTitle>
          <CardDescription>Devices signed in to your account. Revoking stops that session refreshing.</CardDescription>
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
                      <span className="flex items-center gap-2">
                        {formatDate(s.created_at)}
                        {s.current && <Badge variant="secondary">Current</Badge>}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{s.ip_address ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground max-w-xs truncate text-xs" title={s.user_agent ?? ""}>
                      {s.user_agent ?? "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      {!s.current && (
                        // Revoking a session cannot change 2FA state, so the
                        // refetch here is sessions-only; the dual refresh
                        // stays with the 2FA actions (#1391).
                        <SessionRevokeButton base="auth" sessionId={s.id} onRevoked={() => sessions.query.refetch()} />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {list.length === 0 && <EmptyRow colSpan={4}>No active sessions.</EmptyRow>}
              </TableBody>
            </Table>
          </div>
          {list.some((s) => !s.current) && (
            <div className="flex justify-end pt-4">
              <Button variant="destructive" size="sm" onClick={revokeAll} disabled={revokeAllMutation.isPending}>
                Revoke other sessions
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={disableOpen} onOpenChange={setDisableOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disable two-factor</DialogTitle>
            <DialogDescription>Confirm with your password. Your account will no longer require a code.</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="disable-password">Password</Label>
            <Input id="disable-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDisableOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={disable} disabled={!password || disableMutation.isPending}>Disable</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

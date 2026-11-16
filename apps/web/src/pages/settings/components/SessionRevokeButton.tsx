import { useCustomMutation } from "@refinedev/core";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

/**
 * One row's Revoke button. It owns the request itself (hooks cannot live in
 * the .map loop), so a pending revoke disables only its own row instead of
 * every other row's.
 */
export function SessionRevokeButton({
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

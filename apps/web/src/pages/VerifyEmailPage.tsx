import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { API_URL } from "@/providers/dataProvider";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"pending" | "done" | "error">("pending");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setState("error");
      setError("Missing verification token — use the link from your email.");
      return;
    }
    fetch(`${API_URL}/auth/verify-email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (resp) => {
        if (!resp.ok) {
          const detail = (await resp.json().catch(() => null))?.detail;
          throw new Error(detail || "Verification failed — the link may have expired");
        }
        setState("done");
      })
      .catch((err) => {
        setState("error");
        setError((err as Error)?.message ?? "Verification failed");
      });
  }, [token]);

  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardDescription>Email verification</CardDescription>
        </CardHeader>
        <CardContent>
          {state === "pending" && <p className="text-sm">Verifying…</p>}
          {state === "done" && (
            <p className="text-sm">
              Email verified.{" "}
              <Link to="/login" className="text-primary underline underline-offset-4">
                Sign in
              </Link>
            </p>
          )}
          {state === "error" && <p className="text-destructive text-sm">{error}</p>}
        </CardContent>
      </Card>
    </div>
  );
}

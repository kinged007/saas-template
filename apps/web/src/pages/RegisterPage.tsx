import { useState } from "react";
import { useRegister } from "@refinedev/core";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function RegisterPage() {
  const { mutate: register, isPending } = useRegister();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    register(
      { first_name: firstName, last_name: lastName, email, password },
      { onError: (err) => setError((err as Error)?.message ?? "Registration failed") },
    );
  };

  return (
    <div className="bg-background flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">Create account</CardTitle>
          <CardDescription>Create your account</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="first_name">First name</Label>
                <Input
                  id="first_name"
                  placeholder="Ada"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  required
                  maxLength={100}
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="last_name">Last name</Label>
                <Input
                  id="last_name"
                  placeholder="Lovelace"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  required
                  maxLength={100}
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="At least 8 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </div>
            {error && <p className="text-destructive text-sm">{error}</p>}
            <Button type="submit" disabled={isPending}>
              {isPending ? "Creating account…" : "Register"}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="justify-center">
          <p className="text-muted-foreground text-sm">
            Already registered?{" "}
            <Link to="/login" className="text-primary underline underline-offset-4">
              Sign in
            </Link>
          </p>
        </CardFooter>
      </Card>
    </div>
  );
}

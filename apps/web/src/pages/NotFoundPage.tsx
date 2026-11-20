import { Link, useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-[50vh] items-center justify-center p-4">
      <Card className="w-full max-w-md text-center">
        <CardHeader>
          <CardTitle>Page not found</CardTitle>
          <CardDescription>The page you are looking for does not exist or was moved.</CardDescription>
        </CardHeader>
        <CardFooter className="justify-center gap-2">
          <Button asChild>
            <Link to="/">Back to dashboard</Link>
          </Button>
          <Button variant="outline" onClick={() => navigate(-1)}>
            Go back
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
